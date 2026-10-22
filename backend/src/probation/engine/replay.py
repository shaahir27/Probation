"""Event-sourced replay engine loop.

Authority: docs/ENGINE_SPEC.md section 1, docs/CONTRACT.md invariants I-6, I-7, I-9.
Processes a merged timeline of:
- OUTCOME_KNOWN (priority 0)
- LICENCE_REVIEW (priority 1)
- RETRAIN (priority 2)
- SITUATION (priority 3)
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from probation.config import settings
from probation.core.clock import Clock, use_clock
from probation.core.enums import GateDecision, LedgerKind
from probation.core.history import HistoryView
from probation.core.types import Features, Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger
from probation.db.proposals import persist_proposal
from probation.engine.baselines import BaselineB0, BaselineB2
from probation.engine.caps import get_action_loss, is_recallable
from probation.engine.drift import CUSUMTracker, check_family_shift
from probation.engine.evidence import aggregate_evidence
from probation.engine.exam import run_exam
from probation.engine.gate import compute_audit_draw, decide_gate
from probation.engine.habits import mine_habits
from probation.engine.licence import derive_and_cache_licences, find_exam_candidates
from probation.engine.novelty import NoveltyDetector
from probation.engine.policy import Policy
from probation.engine.proposal_data import proposal_parameters
from probation.engine.report import generate_report_card
from probation.packs.base import ExecutorIO, WorldView
from probation.packs.chains.mining import mine_chains
from probation.packs.chains.proposer import create_chain_situations_and_proposals
from probation.packs.registry import registry
from probation.web.view import WebFactsView
from probation.workers.brain import extract_features_for_situations
from probation.workers.executor import Executor
from probation.workers.resolver import resolve_outcomes

PRIORITY_OUTCOME_KNOWN = 0
PRIORITY_LICENCE_REVIEW = 1
PRIORITY_RETRAIN = 2
PRIORITY_SITUATION = 3


@dataclass(slots=True)
class ReplayEvent:
    """An atomic point of occurrence on the merged replay timeline."""

    timestamp: str
    priority: int
    kind: str
    payload: Any = None

    def sort_key(self) -> tuple[datetime, int]:
        """Compute sort key guaranteeing non-decreasing time and tie-break ordering."""
        dt = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return (dt, self.priority)


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
        return _run_replay(conn, clock, family, until, world, reader_callable)


def _run_replay(
    conn: sqlite3.Connection,
    clock: Clock,
    family: str | None = None,
    until: str | None = None,
    world: WorldView | None = None,
    reader_callable: (Callable[[Situation], tuple[dict[str, Any] | None, bool]] | None) = None,
) -> dict[str, Any]:
    """Execute event-sourced replay over historical raw items up to until.

    Authority: docs/ENGINE_SPEC.md section 1.2:
    - Sets clock monotonically.
    - Trains strictly on history with known_at <= current_time.
    - Emits immutable proposals with gate=SHADOW (Phase 4).
    - Appends proposal records to the hash-chained ledger.
    """
    # 1. Ensure features are extracted for any unfeaturized situations
    extract_features_for_situations(conn, reader_callable=reader_callable, clock=clock)

    # 2. Check if outcomes are present; if empty and world provided or available, resolve them
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM outcomes;")
    outcomes_count = cur.fetchone()[0]
    if outcomes_count == 0:
        if world is not None:
            resolve_outcomes(conn, world, clock=clock)
        elif settings.world_db_path.exists():
            from probation.synth.world import SimWorld

            with SimWorld(settings.world_db_path) as sim_world:
                resolve_outcomes(conn, sim_world, clock=clock)

    # 3. Query situations to replay
    query_sit = "SELECT s.* FROM situations s WHERE 1=1"
    params_sit: list[Any] = []
    if family is not None:
        query_sit += " AND s.family = ?"
        params_sit.append(family)
    if until is not None:
        query_sit += " AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?"
        params_sit.append(until)
    query_sit += " ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC;"

    cur.execute(query_sit, tuple(params_sit))
    sit_rows = cur.fetchall()

    if not sit_rows:
        return generate_report_card(conn, family=family, as_of=until)

    # 4. Query outcomes
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
    out_rows = cur.fetchall()

    # 5. Build timeline events
    events: list[ReplayEvent] = []

    # Situation events
    timestamps: list[str] = []
    for s_row in sit_rows:
        occ = str(s_row["occurred_at"])
        timestamps.append(occ)
        events.append(
            ReplayEvent(
                timestamp=occ,
                priority=PRIORITY_SITUATION,
                kind="SITUATION",
                payload=s_row,
            )
        )

    # Outcome events
    for o_row in out_rows:
        known = str(o_row["known_at"])
        timestamps.append(known)
        events.append(
            ReplayEvent(
                timestamp=known,
                priority=PRIORITY_OUTCOME_KNOWN,
                kind="OUTCOME_KNOWN",
                payload=o_row,
            )
        )

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
        fam: Policy(family=fam, cold_start_min=settings.cold_start_min_situations)
        for fam in distinct_families
    }
    novelties: dict[str, NoveltyDetector] = {
        fam: NoveltyDetector(k=settings.novelty_k, percentile=settings.novelty_pctl)
        for fam in distinct_families
    }
    b0_baselines: dict[str, BaselineB0] = {fam: BaselineB0(family=fam) for fam in distinct_families}
    b0_predictions: dict[str, str] = {}
    b2_predictions: dict[str, str] = {}

    brain_access = RoleAccess(conn, Role.BRAIN)
    executor_io: ExecutorIO | None = world if isinstance(world, ExecutorIO) else None
    executor = Executor(conn, world=executor_io, clock=clock)
    web_view = WebFactsView(conn)

    # 7. Execute replay loop
    for ev in timeline:
        ev_dt, _ = ev.sort_key()

        # Monotonically advance clock
        clock.set_time(ev_dt)

        if ev.kind == "OUTCOME_KNOWN":
            out_row = ev.payload
            fam = str(out_row["family"])
            obs_act = str(out_row["observed_action"])
            if str(out_row["strength"]) == "STRONG":
                if fam in b0_baselines:
                    b0_baselines[fam].update(obs_act)

            # Update CUSUM drift tracker per (c, a) (ENGINE_SPEC.md section 11.1)
            # x_t = 1 if disagreement else 0 (evidence items AND undo/override events)
            cur.execute(
                "SELECT class_key, action FROM proposals WHERE situation_id = ?;",
                (str(out_row["situation_id"]),),
            )
            p_row = cur.fetchone()
            if p_row:
                ck = str(p_row["class_key"])
                ac = str(p_row["action"])
                is_undo = str(out_row["source"]) in ("undo", "override")
                is_disagreement = (ac != obs_act) or is_undo

                cur.execute(
                    "SELECT * FROM drift_state WHERE class_key = ? AND action = ?;",
                    (ck, ac),
                )
                d_row = cur.fetchone()
                tracker = CUSUMTracker(
                    baseline_err=float(d_row["baseline_err"]) if d_row else 0.03,
                    initial_s=float(d_row["cusum"]) if d_row else 0.0,
                    last_alarm_at=d_row["last_alarm_at"] if d_row else None,
                )
                alarm = tracker.update(
                    is_error=is_disagreement, is_undo=is_undo, timestamp=str(out_row["known_at"])
                )
                cur.execute(
                    """
                    INSERT OR REPLACE INTO drift_state (class_key, action, cusum, baseline_err, last_alarm_at)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (ck, ac, tracker.s, tracker.baseline_err, tracker.last_alarm_at),
                )
                if alarm:
                    append_ledger(
                        conn,
                        kind=LedgerKind.DRIFT_ALARM,
                        ref_id=f"alarm-{ck}-{ac}",
                        payload={
                            "class_key": ck,
                            "action": ac,
                            "cusum": tracker.s,
                            "kind": "cusum",
                            "alarm_at": str(out_row["known_at"]),
                        },
                        created_at=str(out_row["known_at"]),
                    )
                conn.commit()

        elif ev.kind == "RETRAIN":
            as_of_iso = clock.now_iso()

            # Train each family using STRICTLY data with known_at <= as_of (Invariant I-6)
            for fam in distinct_families:
                cur.execute(
                    """
                    SELECT
                        s.id,
                        s.occurred_at,
                        s.redacted_text,
                        f.deterministic_json,
                        f.reader_json,
                        o.observed_action
                    FROM situations s
                    JOIN outcomes o ON s.id = o.situation_id
                    JOIN features f ON s.id = f.situation_id
                    WHERE s.family = ?
                      AND o.known_at COLLATE UTC_TIMESTAMP <= ?
                      AND o.strength = 'STRONG'
                      AND s.hands_off_reason IS NULL
                      AND f.reader_ok = 1
                    ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC;
                    """,
                    (fam, as_of_iso),
                )
                train_rows = cur.fetchall()

                if len(train_rows) >= settings.cold_start_min_situations:
                    feat_dicts: list[dict[str, Any]] = []
                    obs_acts: list[str] = []
                    timestamps_train: list[str] = []
                    redacted_texts: list[str] = []

                    for tr in train_rows:
                        det = json.loads(tr["deterministic_json"])
                        rdr = json.loads(tr["reader_json"]) if tr["reader_json"] else {}
                        feat_dicts.append({**det, **rdr})
                        obs_acts.append(str(tr["observed_action"]))
                        timestamps_train.append(str(tr["occurred_at"]))
                        if tr["redacted_text"]:
                            redacted_texts.append(str(tr["redacted_text"]))

                    policies[fam].fit(
                        feat_dicts,
                        obs_acts,
                        timestamps_train,
                        as_of=as_of_iso,
                    )
                    novelties[fam].fit(redacted_texts)

            # Weekly PSI check and habit/chain mining
            sim_day_idx = (ev_dt.date() - min_dt.date()).days
            if sim_day_idx % 7 == 0:
                for fam in distinct_families:
                    check_family_shift(conn, family=fam, as_of=as_of_iso)
                mine_habits(conn, as_of=as_of_iso, clock=clock)
                mine_chains(conn, as_of=as_of_iso, clock=clock)

        elif ev.kind == "LICENCE_REVIEW":
            day_iso = ev.timestamp
            stats = aggregate_evidence(conn, as_of=day_iso)
            candidates = find_exam_candidates(
                conn, as_of=day_iso, max_candidates=settings.exam_max_per_day
            )
            for cand_ck, cand_act, cand_lvl in candidates:
                pack_name = cand_ck.split("|")[0]
                cand_fam = (
                    "email_action"
                    if pack_name in ("mail", "email")
                    else "invite_rsvp"
                    if pack_name in ("cal", "calendar")
                    else "file_destination"
                )
                run_exam(
                    conn,
                    class_key=cand_ck,
                    action=cand_act,
                    level_tested=cand_lvl,
                    as_of=day_iso,
                    policy=policies.get(cand_fam),
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
                reader_ok = bool(f_row["reader_ok"])
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
            is_novel, novelty_dist = novelties[fam].score(sit.redacted_text or "")

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

            # Fetch derived licence level
            cur.execute(
                "SELECT level FROM licence_cache WHERE class_key = ? AND action = ?;",
                (c_key, action),
            )
            lic_row = cur.fetchone()
            licence_level = int(lic_row["level"]) if lic_row else 0

            loss = get_action_loss(action)
            recallable = is_recallable(action)
            audit_draw = compute_audit_draw(sit.id, seed=settings.audit_seed)

            # Gate in Phase 5: pure gate function with economic test and audit holdout
            gate_res = decide_gate(
                action=action,
                p=p_max,
                novel=is_novel,
                licence_level=licence_level,
                cap=cap,
                hands_off=sit.hands_off_reason,
                reader_required=False,
                reader_ok=reader_ok,
                deterministic_ok=True,
                loss=loss,
                attention_cost=1.0,
                recallable=recallable,
                audit_draw=audit_draw,
                audit_fraction=settings.audit_fraction,
                budget_ok=True,
            )
            gate = gate_res.decision
            if gate_res.reason:
                reasons.append(gate_res.reason)
            audit_holdout = 1 if gate_res.audit_holdout else 0

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
                    "reasons": reasons,
                },
                web=web_dict,
                policy_version=policies[fam].policy_version,
                features_hash=features_hash,
                audit_holdout=bool(audit_holdout),
                proposed_at=sit.occurred_at,
            )
            persist_proposal(brain_access, final_proposal)
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
    return generate_report_card(
        conn,
        family=family,
        as_of=clock.now_iso(),
        b0_predictions=b0_predictions,
        b2_predictions=b2_predictions,
    )
