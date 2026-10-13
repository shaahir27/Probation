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
from probation.core.clock import Clock
from probation.core.enums import ClockMode, GateDecision, LedgerKind
from probation.core.hashing import canonical_json
from probation.core.types import Features, Situation
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger
from probation.engine.baselines import BaselineB0, BaselineB2
from probation.engine.novelty import NoveltyDetector
from probation.engine.policy import Policy
from probation.engine.report import generate_report_card
from probation.packs.base import WorldView
from probation.packs.registry import registry
from probation.workers.brain import extract_features_for_situations
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
    reader_callable: (Callable[[Situation], tuple[dict[str, Any] | None, bool]] | None) = None,
) -> dict[str, Any]:
    """Execute event-sourced replay over historical raw items up to until.

    Authority: docs/ENGINE_SPEC.md section 1.2:
    - Sets clock monotonically.
    - Trains strictly on history with known_at <= current_time.
    - Emits immutable proposals with gate=SHADOW (Phase 4).
    - Appends proposal records to the hash-chained ledger.
    """
    if clock is None:
        clock = Clock(mode=ClockMode.REPLAY)

    # 1. Ensure features are extracted for any unfeaturized situations
    extract_features_for_situations(conn, reader_callable=reader_callable)

    # 2. Check if outcomes are present; if empty and world provided or available, resolve them
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM outcomes;")
    outcomes_count = cur.fetchone()[0]
    if outcomes_count == 0:
        if world is not None:
            resolve_outcomes(conn, world)
        elif settings.world_db_path.exists():
            from probation.synth.world import SimWorld

            with SimWorld(settings.world_db_path) as sim_world:
                resolve_outcomes(conn, sim_world)

    # 3. Query situations to replay
    query_sit = "SELECT s.* FROM situations s WHERE 1=1"
    params_sit: list[Any] = []
    if family is not None:
        query_sit += " AND s.family = ?"
        params_sit.append(family)
    if until is not None:
        query_sit += " AND s.occurred_at <= ?"
        params_sit.append(until)
    query_sit += " ORDER BY s.occurred_at ASC;"

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
        query_out += " AND o.known_at <= ?"
        params_out.append(until)
    query_out += " ORDER BY o.known_at ASC;"

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

    # 7. Execute replay loop
    for ev in timeline:
        ev_dt, _ = ev.sort_key()

        # Monotonically advance clock
        if clock._current_time < ev_dt:
            clock.set_time(ev_dt)

        if ev.kind == "OUTCOME_KNOWN":
            out_row = ev.payload
            fam = str(out_row["family"])
            obs_act = str(out_row["observed_action"])
            if str(out_row["strength"]) == "STRONG":
                if fam in b0_baselines:
                    b0_baselines[fam].update(obs_act)

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
                      AND o.known_at <= ?
                      AND o.strength = 'STRONG'
                      AND s.hands_off_reason IS NULL
                      AND f.reader_ok = 1
                    ORDER BY s.occurred_at ASC;
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

        elif ev.kind == "LICENCE_REVIEW":
            # Licence review tick (Phase 5 will calculate Beta lower bounds and level transitions)
            pass

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
                pack = registry.get(sit.pack)
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

            # Record baselines
            b0_act = b0_baselines[fam].predict()
            b0_predictions[sit.id] = b0_act

            b2_act, _ = BaselineB2.predict(sit, feat_obj)
            b2_predictions[sit.id] = b2_act

            # Gate in Phase 4 is SHADOW (Phase 5 activates autonomous gate logic and licences)
            gate = GateDecision.SHADOW

            # Append to immutable hash-chained ledger (Contract I-7)
            prop_id = f"prop-{sit.id}"
            seq = append_ledger(
                conn,
                kind=LedgerKind.PROPOSAL,
                ref_id=prop_id,
                payload={
                    "proposal_id": prop_id,
                    "situation_id": sit.id,
                    "family": fam,
                    "class_key": c_key,
                    "action": action,
                    "gate": gate.value,
                    "p_max": p_max,
                    "novel": is_novel,
                    "policy_version": policies[fam].policy_version,
                    "features_hash": features_hash,
                    "proposed_at": sit.occurred_at,
                },
                created_at=sit.occurred_at,
            )

            # Insert proposal record
            brain_access.execute_write(
                "proposals",
                """
                INSERT OR IGNORE INTO proposals
                (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel,
                 licence_level, cap, gate, reasons_json, params_json, explanation_json, web_json,
                 policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    prop_id,
                    sit.id,
                    fam,
                    c_key,
                    action,
                    canonical_json(probs),
                    p_max,
                    novelty_dist,
                    1 if is_novel else 0,
                    0,  # licence_level = 0 throughout Phase 4
                    cap,
                    gate.value,
                    canonical_json(reasons),
                    "{}",
                    "{}",
                    "{}",
                    policies[fam].policy_version,
                    features_hash,
                    0,
                    sit.occurred_at,
                    seq,
                ),
            )

    brain_access.commit()

    # 8. Return comprehensive report card
    return generate_report_card(
        conn,
        family=family,
        as_of=clock.now_iso(),
        b0_predictions=b0_predictions,
        b2_predictions=b2_predictions,
    )
