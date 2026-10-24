"""Event-sourced replay engine loop.

Authority: docs/ENGINE_SPEC.md section 1, docs/CONTRACT.md invariants I-6, I-7, I-9.
Processes a merged timeline of:
- OUTCOME_KNOWN (priority 0)
- LICENCE_REVIEW (priority 1)
- RETRAIN (priority 2)
- SITUATION (priority 3)
"""

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from probation.config import settings
from probation.core.clock import Clock, timestamp_key, use_clock
from probation.core.enums import GateDecision, LedgerKind
from probation.core.hashing import canonical_json
from probation.core.history import HistoryView
from probation.core.types import Features, Outcome, Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger
from probation.db.proposals import persist_proposal
from probation.engine.baselines import BaselineB0, BaselineB2
from probation.engine.caps import is_recallable
from probation.engine.drift import check_family_shift
from probation.engine.evidence import aggregate_evidence
from probation.engine.exam import run_exam
from probation.engine.habits import mine_habits
from probation.engine.licence import (
    derive_and_cache_licences,
    derive_licences,
    family_for_class,
    find_exam_candidates,
)
from probation.engine.novelty import EmbeddingProvider, NoveltyDetector, NoveltyUnavailable
from probation.engine.policy import Policy
from probation.engine.prediction import PredictionSnapshot, evaluate_prediction, policy_inputs
from probation.engine.proposal_data import proposal_parameters
from probation.engine.report import generate_report_card
from probation.packs.base import ExecutorIO, WorldView
from probation.packs.calendar.resolver import resolve_calendar_outcome
from probation.packs.chains.mining import mine_chains
from probation.packs.chains.proposer import create_chain_situations_and_proposals
from probation.packs.identity import persisted_or_configured_owner, world_user_addresses
from probation.packs.mail.resolver import MailResolverIndex, resolve_mail_outcome
from probation.packs.registry import registry
from probation.web.view import WebFactsView
from probation.workers.brain import build_reader_client, extract_features_for_situations
from probation.workers.drift import review_outcome_events
from probation.workers.executor import Executor

PRIORITY_OUTCOME_KNOWN = 0
PRIORITY_LICENCE_REVIEW = 1
PRIORITY_RETRAIN = 2
PRIORITY_SITUATION = 3

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReplayEvent:
    """An atomic point of occurrence on the merged replay timeline."""

    timestamp: str
    priority: int
    kind: str
    payload: Any = None
    tie_id: str = ""

    def sort_key(self) -> tuple[datetime, int, str]:
        """Compute sort key guaranteeing non-decreasing time and tie-break ordering.

        `tie_id` makes the order total. Without it, two events at the same instant and
        priority fall back to list position, which is whatever the producing SQL query
        returned; SQLite does not guarantee that order for equal keys, so an index or
        planner change could silently reorder a replay and change its ledger head.
        """
        dt = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return (dt, self.priority, self.tie_id)


def _parse_utc_dt(ts_str: str) -> datetime:
    """Parse timestamp into UTC datetime."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def run_replay(
    conn: sqlite3.Connection,
    clock: Clock | None = None,
    family: str | None = None,
    until: str | None = None,
    world: WorldView | None = None,
    reader_callable: Callable[[Situation], tuple[dict[str, Any] | None, bool]] | None = None,
    allow_live_llm: bool = False,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    """Own one clock context for every role participating in this replay."""
    if clock is None:
        first = conn.execute(
            "SELECT MIN(occurred_at COLLATE UTC_TIMESTAMP) FROM situations"
        ).fetchone()[0]
        start = (
            _parse_utc_dt(str(first)).replace(hour=0, minute=0, second=0, microsecond=0)
            if first
            else None
        )
        clock = Clock.replay(start)
    with use_clock(clock):
        return _run_replay(
            conn,
            clock,
            family,
            until,
            world,
            reader_callable,
            allow_live_llm=allow_live_llm,
            embedding_provider=embedding_provider,
        )


def _run_replay(
    conn: sqlite3.Connection,
    clock: Clock,
    family: str | None = None,
    until: str | None = None,
    world: WorldView | None = None,
    reader_callable: (Callable[[Situation], tuple[dict[str, Any] | None, bool]] | None) = None,
    allow_live_llm: bool = False,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    """Execute event-sourced replay over historical raw items up to until.

    Authority: docs/ENGINE_SPEC.md section 1.2:
    - Sets clock monotonically.
    - Trains strictly on history with known_at <= current_time.
    - Emits immutable proposals with gate=SHADOW (Phase 4).
    - Appends proposal records to the hash-chained ledger.
    """
    # 1. Build the reader once. Features are derived per situation inside the loop below,
    #    at that situation's own cutoff: history clues count prior outcomes, so a batch run
    #    here would read an empty outcomes table and collapse them to their defaults
    #    (plan section 6.3.3).
    reader_client = (
        None if reader_callable is not None else build_reader_client(clock, allow_live_llm, conn)
    )

    # 2. Query situations to replay
    query_sit = "SELECT s.* FROM situations s WHERE 1=1"
    params_sit: list[Any] = []
    if family is not None:
        query_sit += " AND s.family = ?"
        params_sit.append(family)
    if until is not None:
        query_sit += " AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?"
        params_sit.append(until)
    query_sit += " ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC;"

    cur = conn.cursor()
    cur.execute(query_sit, tuple(params_sit))
    sit_rows = cur.fetchall()

    if not sit_rows:
        return generate_report_card(conn, family=family, as_of=until)

    # 3. Outcomes already persisted, plus any still missing that the world can supply.
    #    The two sources are additive, never alternatives: a resumed replay has some
    #    outcomes stored and still needs the remainder staged. Treating the stored ones
    #    as sufficient silently dropped every outcome after the resume point (I-7).
    events: list[ReplayEvent] = []
    timestamps: list[str] = []

    # Situation events
    for s_row in sit_rows:
        occ = str(s_row["occurred_at"])
        timestamps.append(occ)
        events.append(
            ReplayEvent(
                timestamp=occ,
                priority=PRIORITY_SITUATION,
                kind="SITUATION",
                payload=s_row,
                tie_id=str(s_row["id"]),
            )
        )

    query_out = (
        "SELECT o.*, s.family FROM outcomes o JOIN situations s ON o.situation_id = s.id WHERE 1=1"
    )
    params_out: list[Any] = []
    if family is not None:
        query_out += " AND s.family = ?"
        params_out.append(family)
    if until is not None:
        query_out += " AND o.known_at COLLATE UTC_TIMESTAMP <= ?"
        params_out.append(until)
    query_out += " ORDER BY o.known_at COLLATE UTC_TIMESTAMP ASC;"

    cur.execute(query_out, tuple(params_out))
    for o_row in cur.fetchall():
        known = str(o_row["known_at"])
        timestamps.append(known)
        events.append(
            ReplayEvent(
                timestamp=known,
                priority=PRIORITY_OUTCOME_KNOWN,
                kind="OUTCOME_KNOWN",
                payload=o_row,
                tie_id=str(o_row["situation_id"]),
            )
        )

    # Every situation without a stored outcome is still owed one. Stage those from the
    # world without writing to the database or the ledger yet.
    cur.execute("SELECT situation_id FROM outcomes;")
    resolved_ids = {str(row[0]) for row in cur.fetchall()}
    unresolved = [row for row in sit_rows if str(row["id"]) not in resolved_ids]

    if unresolved:
        sim_world_instance: Any | None = None
        target_world: WorldView | None = world

        # The owner identity is resolved before any world is opened, so that a world this
        # function has to construct for itself is told whose world it is. Resolving afterwards
        # would leave the constructed world anonymous and no reply could be attributed.
        eff_addrs = persisted_or_configured_owner(cur)
        if world is not None and (w_addrs := world_user_addresses(world)) is not None:
            eff_addrs = w_addrs

        if target_world is None and settings.world_db_path.exists():
            from probation.synth.world import SimWorld

            sim_world_instance = SimWorld(settings.world_db_path, user_addresses=eff_addrs)
            target_world = sim_world_instance

        if target_world is not None:
            stage_sql = """
                SELECT s.*, r.payload_json
                FROM situations s
                LEFT JOIN raw_items r ON s.raw_item_id = r.id
                WHERE 1=1
            """
            stage_params: list[Any] = []
            if family is not None:
                stage_sql += " AND s.family = ?"
                stage_params.append(family)
            if until is not None:
                stage_sql += " AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?"
                stage_params.append(until)
            stage_sql += " ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC;"
            cur.execute(stage_sql, tuple(stage_params))
            sit_for_out = cur.fetchall()

            # Pre-index messages for high-speed resolution
            try:
                mail_index = MailResolverIndex(eff_addrs, target_world.get_messages())
            except Exception:
                # Without the index no reply can be attributed, so every mail situation would
                # resolve to a WEAK LEAVE. That is evidence-safe but silently hollow, so it is
                # logged rather than swallowed.
                logger.warning(
                    "Could not index world messages for outcome resolution", exc_info=True
                )
                mail_index = None

            eval_dt = datetime(2099, 1, 1, tzinfo=UTC)
            if until is not None:
                try:
                    eval_dt = _parse_utc_dt(until)
                except Exception:
                    pass

            for s_row in sit_for_out:
                sit = Situation(
                    id=s_row["id"],
                    raw_item_id=s_row["raw_item_id"],
                    pack=s_row["pack"],
                    family=s_row["family"],
                    variant=s_row["variant"],
                    occurred_at=s_row["occurred_at"],
                    sender_key=s_row["sender_key"],
                    content_hash=s_row["content_hash"],
                    redacted_text=s_row["redacted_text"],
                    hands_off_reason=s_row["hands_off_reason"],
                    created_at=s_row["created_at"],
                )
                raw_payload: dict[str, Any] | None = None
                if s_row["payload_json"]:
                    try:
                        raw_payload = json.loads(s_row["payload_json"])
                    except Exception:
                        pass

                out_obj: Outcome | None = None
                if sit.pack == "mail":
                    out_obj = resolve_mail_outcome(
                        sit,
                        target_world,
                        eval_dt,
                        raw_payload=raw_payload,
                        user_addresses=eff_addrs,
                        index=mail_index,
                    )
                elif sit.pack == "calendar":
                    out_obj = resolve_calendar_outcome(
                        sit,
                        target_world,
                        eval_dt,
                        raw_payload=raw_payload,
                        user_addresses=eff_addrs,
                    )
                else:
                    try:
                        p_adapter = registry.get_descriptor(sit.pack)
                        # A Situation carries hashes and redacted text only, so the source
                        # identity a resolver needs (a file's rel_path, a link's url) lives in the
                        # raw payload, which is already parsed here and must be handed over.
                        out_obj = p_adapter.resolve_observed_outcome(
                            sit, target_world, eval_dt, raw_payload
                        )
                    except KeyError:
                        continue

                if out_obj is not None:
                    if until is not None and _parse_utc_dt(out_obj.known_at) > _parse_utc_dt(until):
                        continue
                    timestamps.append(out_obj.known_at)
                    events.append(
                        ReplayEvent(
                            timestamp=out_obj.known_at,
                            priority=PRIORITY_OUTCOME_KNOWN,
                            kind="OUTCOME_KNOWN",
                            payload=out_obj,
                            tie_id=str(out_obj.situation_id),
                        )
                    )

            if sim_world_instance is not None:
                sim_world_instance.close()

    # Date range for LICENCE_REVIEW and RETRAIN ticks
    dt_list = [_parse_utc_dt(ts) for ts in timestamps]
    min_dt = min(dt_list).replace(hour=0, minute=0, second=0, microsecond=0)
    max_dt = max(dt_list)
    if until is not None:
        max_dt = max(max_dt, _parse_utc_dt(until))

    current_day = min_dt
    day_idx = 0
    retrain_interval = settings.retrain_interval_days

    while current_day <= max_dt:
        day_iso = current_day.strftime("%Y-%m-%dT00:00:00Z")

        # LICENCE_REVIEW daily tick (priority 1)
        events.append(
            ReplayEvent(
                timestamp=day_iso,
                priority=PRIORITY_LICENCE_REVIEW,
                kind="LICENCE_REVIEW",
            )
        )

        # RETRAIN tick (priority 2) every retrain_interval days
        if day_idx % retrain_interval == 0:
            events.append(
                ReplayEvent(
                    timestamp=day_iso,
                    priority=PRIORITY_RETRAIN,
                    kind="RETRAIN",
                )
            )

        current_day += timedelta(days=1)
        day_idx += 1

    # Sort merged timeline
    timeline = sorted(events, key=lambda ev: ev.sort_key())

    # 6. Initialize per-family models and baselines
    distinct_families = sorted({str(r["family"]) for r in sit_rows})
    policies: dict[str, Policy] = {
        fam: Policy(
            family=fam,
            cold_start_min=settings.cold_start_min_situations,
            train_half_life_days=settings.train_half_life_days,
            files_topk=settings.files_topk_folders,
        )
        for fam in distinct_families
    }
    if embedding_provider is None and settings.embedding_model_dir.exists():
        from probation.local_embeddings import LocalMiniLM

        try:
            embedding_provider = LocalMiniLM(
                settings.embedding_model_dir, settings.embedding_manifest_path
            )
        except NoveltyUnavailable:
            logger.warning("Local embedding provider unavailable; autonomous decisions fail closed")
    novelties: dict[str, NoveltyDetector] = {
        fam: (
            NoveltyDetector(
                k=settings.novelty_k, percentile=settings.novelty_pctl, embedder=embedding_provider
            )
            if embedding_provider is not None
            else NoveltyDetector(k=settings.novelty_k, percentile=settings.novelty_pctl)
        )
        for fam in distinct_families
    }
    training_cohorts: dict[str, Any] = {}
    training_manifests: list[dict[str, Any]] = []
    b0_baselines: dict[str, BaselineB0] = {fam: BaselineB0(family=fam) for fam in distinct_families}
    b0_predictions: dict[str, str] = {}
    b2_predictions: dict[str, str] = {}

    brain_access = RoleAccess(conn, Role.BRAIN)
    resolver_access = RoleAccess(conn, Role.RESOLVER)
    executor_io: ExecutorIO | None = world if isinstance(world, ExecutorIO) else None
    executor = Executor(conn, world=executor_io, clock=clock)
    web_view = WebFactsView(conn)

    # 7. Execute replay loop
    for ev in timeline:
        ev_dt = ev.sort_key()[0]

        # Monotonically advance clock
        clock.set_time(ev_dt)

        if ev.kind == "OUTCOME_KNOWN":
            payload = ev.payload
            if isinstance(payload, Outcome):
                sit_id = payload.situation_id
                obs_act = payload.observed_action
                strength = str(payload.strength)
                known_at = payload.known_at
                source = payload.source
                observed_at = payload.observed_at
                details = payload.details

                cur.execute("SELECT family FROM situations WHERE id = ?;", (sit_id,))
                s_fam_row = cur.fetchone()
                fam = str(s_fam_row["family"]) if s_fam_row else ""

                # Write to ledger first, then table (Contract I-7)
                cur.execute("SELECT ledger_seq FROM outcomes WHERE situation_id = ?;", (sit_id,))
                existing_out = cur.fetchone()
                if not existing_out:
                    seq = append_ledger(
                        conn,
                        kind=LedgerKind.OUTCOME,
                        ref_id=sit_id,
                        payload={
                            "situation_id": sit_id,
                            "observed_action": obs_act,
                            "strength": strength,
                            "source": source,
                            "observed_at": observed_at,
                            "known_at": known_at,
                            "details": details,
                        },
                        created_at=known_at,
                    )
                    resolver_access.execute_write(
                        "outcomes",
                        """
                        INSERT OR IGNORE INTO outcomes
                        (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            sit_id,
                            obs_act,
                            strength,
                            source,
                            observed_at,
                            known_at,
                            canonical_json(details),
                            seq,
                        ),
                    )
                    conn.commit()
            else:
                out_row = payload
                fam = str(out_row["family"])
                obs_act = str(out_row["observed_action"])
                strength = str(out_row["strength"])
                known_at = str(out_row["known_at"])
                source = str(out_row["source"])
                sit_id = str(out_row["situation_id"])

            if strength == "STRONG":
                if fam in b0_baselines:
                    b0_baselines[fam].update(obs_act)

            review_outcome_events(conn, as_of=known_at)
            conn.commit()

        elif ev.kind == "RETRAIN":
            as_of_iso = clock.now_iso()

            # All eligibility and historical projection is owned by HistoryView.
            from probation.engine.training import build_cohort, fit_cohort
            from probation.llm.feature_pipeline import semantic_feature_version

            for fam in distinct_families:
                cohort = build_cohort(
                    HistoryView(conn, as_of_iso),
                    fam,
                    semantic_feature_version(stub=reader_callable is not None),
                )
                training_cohorts[fam] = cohort
                fit_cohort(policies[fam], cohort, as_of_iso)
                refs = [r for r in cohort.rows if r.redacted_text.strip()]
                try:
                    novelties[fam].fit(
                        [r.redacted_text for r in refs],
                        reference_ids=[r.situation_id for r in refs],
                        family=fam,
                    )
                except NoveltyUnavailable:
                    logger.warning("Novelty fitting unavailable for family %s", fam)
                training_manifests.append(
                    {
                        "family": fam,
                        "as_of": as_of_iso,
                        "eligible_rows": len(cohort.rows),
                        "excluded": cohort.excluded,
                        "policy_version": policies[fam].policy_version,
                        "policy_digest": policies[fam].policy_digest,
                        "cohort_digest": policies[fam].cohort_digest,
                        "calibration": policies[fam].calibration,
                        "temperature": policies[fam].temperature,
                        "embedding_identity": getattr(novelties[fam].embedder, "identity", None),
                        "novelty_status": novelties[fam].status,
                        "novelty_references": len(novelties[fam].reference_ids),
                    }
                )

            # Weekly PSI check and habit/chain mining
            sim_day_idx = (ev_dt.date() - min_dt.date()).days
            if sim_day_idx % 7 == 0:
                for fam in distinct_families:
                    check_family_shift(conn, family=fam, as_of=as_of_iso)
                mine_habits(conn, as_of=as_of_iso, clock=clock)
                mine_chains(conn, as_of=as_of_iso, clock=clock)

        elif ev.kind == "LICENCE_REVIEW":
            day_iso = ev.timestamp
            stats = aggregate_evidence(
                conn, as_of=day_iso, evidence_window_days=settings.evidence_window_days
            )
            conn.commit()
            candidates = find_exam_candidates(
                conn, as_of=day_iso, max_candidates=settings.exam_max_per_day
            )
            for cand_ck, cand_act, cand_lvl in candidates:
                cand_fam = family_for_class(cand_ck)
                from probation.engine.exam_prediction import ExamPredictionContext
                from probation.llm.consumers import RegisteredConsumer, offline_consumer
                from probation.llm.gateway import JobGateway, transport_authority

                exam_consumer = (
                    offline_consumer(conn)
                    if reader_client is None
                    else RegisteredConsumer(
                        JobGateway(reader_client, conn=conn),
                        transport_authority(reader_client, allow_live_dispatch=allow_live_llm),
                    )
                )
                exam_context = (
                    None
                    if cand_fam not in policies
                    else ExamPredictionContext(
                        PredictionSnapshot(
                            policies[cand_fam],
                            novelties[cand_fam],
                            settings.audit_seed,
                            settings.audit_fraction,
                            settings.attention_cost,
                        ),
                        HistoryView(conn, day_iso),
                        exam_consumer,
                        reader_callable,
                    )
                )
                run_exam(
                    conn,
                    class_key=cand_ck,
                    action=cand_act,
                    level_tested=cand_lvl,
                    as_of=day_iso,
                    policy=policies.get(cand_fam),
                    prediction_context=exam_context,
                    scheduled=True,
                    clock=clock,
                )
            derive_and_cache_licences(conn, as_of=day_iso, stats=stats)
            conn.commit()
            executor.process_queue(as_of=day_iso)

        elif ev.kind == "SITUATION":
            s_row = ev.payload
            sit_id = str(s_row["id"])
            fam = str(s_row["family"])

            # Check if proposal already written (idempotent)
            cur.execute("SELECT id FROM proposals WHERE situation_id = ?;", (sit_id,))
            if cur.fetchone() is not None:
                continue

            # Outcome-known events sort before situations at the same instant, so an outcome
            # can already be durable by the time this situation is reached. Proposing then
            # would make proposed_at >= known_at and land the proposal's ledger entry after
            # the outcome's, breaking I-7 both ways. That evidence is unusable: fail closed.
            cur.execute("SELECT known_at FROM outcomes WHERE situation_id = ?;", (sit_id,))
            prior_out = cur.fetchone()
            occurred_at = str(s_row["occurred_at"])
            if prior_out is not None and timestamp_key(str(prior_out["known_at"])) <= timestamp_key(
                occurred_at
            ):
                logger.warning(
                    "No proposal for situation %s: outcome known_at %s is not strictly after "
                    "occurred_at %s, so I-7 cannot hold",
                    sit_id,
                    prior_out["known_at"],
                    occurred_at,
                )
                continue

            # Derive this situation's features now, at its own historical cutoff, so reply
            # and folder history see exactly the outcomes that were durable when it occurred.
            extract_features_for_situations(
                conn,
                reader_callable=reader_callable,
                clock=clock,
                situation_id=sit_id,
                llm_client=reader_client,
                allow_live_llm=allow_live_llm,
            )
            conn.commit()

            # Fetch stored features for situation
            cur.execute("SELECT * FROM features WHERE situation_id = ?;", (sit_id,))
            f_row = cur.fetchone()

            if f_row is None:
                det_dict: dict[str, Any] = {}
                reader_dict: dict[str, Any] | None = None
                reader_ok = False
                features_hash = "missing"
                merged_features: dict[str, Any] = {}
            else:
                det_dict = json.loads(f_row["deterministic_json"])
                reader_dict = json.loads(f_row["reader_json"]) if f_row["reader_json"] else None
                from probation.llm.feature_pipeline import semantic_feature_version

                reader_ok = bool(f_row["reader_ok"]) and str(
                    f_row["featurizer_version"]
                ) == semantic_feature_version(stub=reader_callable is not None)
                if reader_ok:
                    # P06 #5: a row is reusable only when its full provenance matches the
                    # requested feature version and cutoff. An earlier cutoff counted fewer
                    # outcomes and so proves nothing about this situation, and a row with no
                    # parsable cutoff cannot be matched at all.
                    stored_cutoff: str | None = None
                    raw_prov = (
                        f_row["provenance_json"] if "provenance_json" in f_row.keys() else None
                    )
                    if raw_prov:
                        try:
                            loaded = json.loads(raw_prov).get("cutoff")
                            stored_cutoff = str(loaded) if loaded else None
                        except (ValueError, TypeError, AttributeError):
                            stored_cutoff = None
                    if stored_cutoff != str(s_row["occurred_at"]):
                        reader_ok = False
                if not reader_ok:
                    det_dict["__deterministic_ok"] = False
                features_hash = str(f_row["features_hash"])
                merged_features = {**det_dict, **(reader_dict or {})}

            sit = Situation(
                id=sit_id,
                raw_item_id=str(s_row["raw_item_id"]),
                pack=str(s_row["pack"]),
                family=fam,
                variant=str(s_row["variant"] or ""),
                occurred_at=str(s_row["occurred_at"]),
                sender_key=s_row["sender_key"],
                content_hash=str(s_row["content_hash"]),
                redacted_text=s_row["redacted_text"],
                hands_off_reason=s_row["hands_off_reason"],
                created_at=str(s_row["created_at"] or ""),
            )

            # Predict action from policy
            if not reader_ok:
                action = "ABSTAIN"
                p_max = 1.0
                probs: dict[str, float] = {"ABSTAIN": 1.0}
                reasons = ["featurization_failed"]
            else:
                action, p_max, probs, reasons = policies[fam].predict(merged_features)

            if sit.hands_off_reason is not None:
                reasons.append("hands_off")

            # Novelty assessment
            is_novel, novelty_dist = True, 1.0

            # Pack caps and class key
            try:
                pack = registry.get_descriptor(sit.pack)
                feat_obj = Features(
                    situation_id=sit.id,
                    deterministic=det_dict,
                    reader=reader_dict,
                    reader_ok=reader_ok,
                    featurizer_version=(str(f_row["featurizer_version"]) if f_row else "v1.0"),
                    features_hash=features_hash,
                )
                c_key = pack.class_key(sit, feat_obj)
                cap = pack.level_cap(action, sit, feat_obj)
            except Exception:
                c_key = f"{sit.pack}|unknown"
                cap = 0
                feat_obj = None

            # Web grounding veto (docs/TAVILY_AND_NEW_PACKS 5.6 and CONTRACT I-21)
            sender_domain = sit.sender_key.split("@")[-1].strip().lower() if sit.sender_key else ""
            web_facts = web_view.get_entity_facts(sender_domain)
            if web_facts:
                web_status = web_facts.status
                web_cap = web_facts.web_cap
                web_sources = [
                    s.get("url", "") if isinstance(s, dict) else str(s) for s in web_facts.sources
                ]
                if web_cap == 1:
                    cap = min(cap, web_cap)
                    reasons.extend(web_facts.reasons)
                web_dict = {
                    "status": web_status,
                    "cap": web_cap,
                    "source_ids": web_sources,
                }
            else:
                web_dict = {"status": "not_checked", "cap": 3, "source_ids": []}

            # Record baselines
            b0_act = b0_baselines[fam].predict()
            b0_predictions[sit.id] = b0_act

            b2_act, _ = BaselineB2.predict(sit, feat_obj)
            b2_predictions[sit.id] = b2_act

            # Re-derive current authority; a nightly cache is never permission truth.
            licence = derive_licences(conn, as_of_iso, pair=(c_key, action)).get((c_key, action))
            licence_level = int(licence.level) if licence else 0

            recallable = is_recallable(action)
            if feat_obj is not None:
                prediction = evaluate_prediction(
                    sit,
                    feat_obj,
                    pack,
                    PredictionSnapshot(
                        policies[fam], novelties[fam], settings.audit_seed, settings.audit_fraction
                    ),
                    licence_level=licence_level,
                    restriction_cap=int(str(web_dict["cap"])),
                )
                action, p_max, probs = prediction.action, prediction.p_max, prediction.probs
                reasons = list(prediction.reasons)
                c_key, cap = prediction.class_key, prediction.cap
                is_novel, novelty_dist = prediction.novel, prediction.novelty
                gate, audit_holdout = prediction.gate, int(prediction.audit_holdout)
            else:
                gate, audit_holdout = GateDecision.ASK, 0
                reasons.append("deterministic_clues_invalid")

            if action in {"ABSTAIN", "NONE"} and gate in {
                GateDecision.EXECUTE_UNDO,
                GateDecision.EXECUTE_SILENT,
                GateDecision.HOLD_THEN_EXECUTE,
            }:
                gate = GateDecision.SHADOW if reader_ok else GateDecision.ASK
                reasons.append("non_executable_prediction")
            try:
                example_scores = novelties[fam].similarity_scores(
                    str(det_dict.get("__novelty_text", sit.redacted_text or ""))[:4000]
                )
            except NoveltyUnavailable:
                example_scores = {}
            cohort_rows = training_cohorts[fam].rows if fam in training_cohorts else ()
            from probation.core.history_statistics import historical_examples

            similar_examples = historical_examples(
                [
                    {
                        "situation_id": r.situation_id,
                        "action": r.action,
                        "text": r.redacted_text[:250],
                        "known_at": r.known_at,
                    }
                    for r in cohort_rows
                ],
                example_scores,
                action,
            )
            # Generate/validate all available data before the single persistence unit.
            params, binding_errors = proposal_parameters(
                sit,
                action,
                HistoryView(conn, as_of=sit.occurred_at),
                reader_dict,
            )
            if binding_errors:
                gate = GateDecision.ASK
                reasons.extend(binding_errors)
            prop_id = f"prop-{sit.id}"
            final_proposal = Proposal(
                id=prop_id,
                situation_id=sit.id,
                family=fam,
                class_key=c_key,
                action=action,
                probs=probs,
                p_max=p_max,
                novelty=novelty_dist,
                novel=is_novel,
                licence_level=licence_level,
                cap=cap,
                gate=gate,
                reasons=reasons,
                params=params,
                explanation={
                    "features_hash": features_hash,
                    "policy_version": policies[fam].policy_version,
                    "evidence_as_of": sit.occurred_at,
                    "policy_explanation": policies[fam].explain(policy_inputs(feat_obj))
                    if feat_obj is not None
                    else {"available": False, "reason": "features_unavailable"},
                    "reasons": reasons,
                    "similar_examples": similar_examples,
                },
                web=web_dict,
                policy_version=policies[fam].policy_version,
                features_hash=features_hash,
                audit_holdout=bool(audit_holdout),
                proposed_at=sit.occurred_at,
            )
            draft = None
            if action == "REPLY" and feat_obj is not None:
                from probation.llm.consumers import RegisteredConsumer, offline_consumer
                from probation.llm.draft_persistence import prepare_reply_persistence
                from probation.llm.gateway import JobGateway, transport_authority
                from probation.llm.writer import generate_reply

                raw = HistoryView(conn, sit.occurred_at).get_raw_item(sit.raw_item_id)
                source = json.loads(raw["payload_json"]) if raw is not None else {}
                consumer = (
                    offline_consumer(conn)
                    if reader_client is None
                    else RegisteredConsumer(
                        JobGateway(reader_client, conn=conn),
                        transport_authority(reader_client, allow_live_dispatch=allow_live_llm),
                    )
                )
                from probation.llm.context import redaction_names
                from probation.llm.reply_examples import owner_reply_examples

                owner = persisted_or_configured_owner(conn.cursor())
                example_names = list(redaction_names(source.get("from", ""), source.get("to", "")))
                reply_examples = owner_reply_examples(
                    HistoryView(conn, sit.occurred_at),
                    current_raw_id=sit.raw_item_id,
                    owner_addresses=owner,
                    scores=example_scores,
                    display_names_out=example_names,
                )
                writer = generate_reply(
                    consumer,
                    incoming=str(source.get("body", "")),
                    original_sender=str(source.get("from") or source.get("from_addr") or ""),
                    situation_id=sit.id,
                    examples=reply_examples,
                    display_names=example_names,
                    preview_warrants_reply=reader_ok and prediction.gate != GateDecision.SHADOW,
                )
                if writer.persistable and binding_errors == ["draft_unavailable"]:
                    final_proposal = final_proposal.model_copy(update={"gate": prediction.gate})
                final_proposal, draft = prepare_reply_persistence(
                    final_proposal, sit, HistoryView(conn, sit.occurred_at), writer
                )
                gate, params = final_proposal.gate, final_proposal.params
            persist_proposal(brain_access, final_proposal, draft=draft)
            # This replay is the transaction owner. No external consumer precedes this barrier.
            brain_access.commit()
            if gate in (
                GateDecision.HOLD_THEN_EXECUTE,
                GateDecision.EXECUTE_UNDO,
                GateDecision.EXECUTE_SILENT,
            ):
                level_req = 3 if gate == GateDecision.EXECUTE_SILENT else 2
                executor.create_action(
                    proposal_id=prop_id,
                    pack=sit.pack,
                    action_type=action,
                    params=params,
                    level_required=level_req,
                    recallable=recallable,
                    gate_decision=gate,
                    as_of=sit.occurred_at,
                )
                if world is not None:
                    executor.process_queue(as_of=sit.occurred_at)

            # Trigger chain follow-up situations and proposals for trigger situations
            if sit.pack != "chains":
                chain_results = create_chain_situations_and_proposals(
                    conn,
                    trigger_sit=sit,
                    trigger_class_key=c_key,
                    as_of=sit.occurred_at,
                    reader_features=reader_dict,
                )
                for c_sit, c_prop in chain_results:
                    if c_prop.gate in (
                        GateDecision.HOLD_THEN_EXECUTE,
                        GateDecision.EXECUTE_UNDO,
                        GateDecision.EXECUTE_SILENT,
                    ):
                        c_level_req = 3 if c_prop.gate == GateDecision.EXECUTE_SILENT else 2
                        c_recallable = is_recallable(c_prop.action)
                        executor.create_action(
                            proposal_id=c_prop.id,
                            pack=c_sit.pack,
                            action_type=c_prop.action,
                            params=c_prop.params,
                            level_required=c_level_req,
                            recallable=c_recallable,
                            gate_decision=c_prop.gate,
                            as_of=c_sit.occurred_at,
                        )
                        if world is not None:
                            executor.process_queue(as_of=c_sit.occurred_at)

    brain_access.commit()

    # Final pass for habits and chains up to replay clock
    mine_habits(conn, as_of=clock.now_iso(), clock=clock)
    mine_chains(conn, as_of=clock.now_iso(), clock=clock)
    conn.commit()

    # 8. Return comprehensive report card
    report = generate_report_card(
        conn,
        family=family,
        as_of=clock.now_iso(),
        b0_predictions=b0_predictions,
        b2_predictions=b2_predictions,
    )
    report["training_manifest"] = training_manifests
    return report
