"""Read-only bounded cohort queries and legacy immutable decision projection.

No new event schema or worker writes. Unknown event provenance fails closed.
"""

import json
import sqlite3
from typing import Any

from probation.core.clock import timestamp_key
from probation.db.guards import ReadConnection


def decision_projection(
    conn: sqlite3.Connection | ReadConnection, as_of: str
) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """SELECT seq,payload_json,created_at FROM ledger
           WHERE kind='outcome' AND created_at COLLATE UTC_TIMESTAMP <= ?
           ORDER BY created_at COLLATE UTC_TIMESTAMP,seq""",
        (as_of,),
    ).fetchall()
    decisions: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = json.loads(row["payload_json"])
        sid = payload.get("situation_id")
        known = payload.get("known_at")
        if not isinstance(sid, str) or not isinstance(known, str):
            continue
        if timestamp_key(known) > timestamp_key(as_of):
            continue
        action, source = payload.get("observed_action"), payload.get("source")
        if source not in {"footprint", "user_response", "window_close"} or action in {
            None,
            "UNDO",
            "OVERRIDE",
            "REJECT",
            "CANCEL",
            "ABSTAIN",
        }:
            decisions[sid] = {
                "situation_id": sid,
                "eligible": False,
                "reason": "correction_or_unknown_provenance",
                "known_at": known,
                "ledger_seq": row["seq"],
            }
            continue
        # Repeated/conflicting decisions without an explicit correction relationship
        # are ambiguous, never latest-row-wins manufactured training data.
        if sid in decisions:
            old = decisions[sid]
            if old.get("observed_action") != action:
                decisions[sid] = {
                    "situation_id": sid,
                    "eligible": False,
                    "reason": "ambiguous_decision_history",
                    "known_at": known,
                }
            continue
        decisions[sid] = {**payload, "eligible": True, "ledger_seq": row["seq"]}
    return decisions


def training_records(
    conn: sqlite3.Connection | ReadConnection, as_of: str, family: str
) -> list[dict[str, Any]]:
    # Current item/features are explicit read capabilities; history cutoff applies
    # to situation, raw observation, immutable decision and feature creation.
    rows = conn.execute(
        """SELECT s.id,s.family,s.occurred_at,s.redacted_text,s.hands_off_reason,
                  f.deterministic_json,f.reader_json,f.reader_ok,f.featurizer_version,
                  f.features_hash,r.payload_json
           FROM situations s JOIN features f ON f.situation_id=s.id
           JOIN raw_items r ON r.id=s.raw_item_id
           WHERE s.family=? AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
             AND r.known_at COLLATE UTC_TIMESTAMP <= ?
             AND f.created_at COLLATE UTC_TIMESTAMP <= ?
           ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP,s.id""",
        (family, as_of, as_of, as_of),
    ).fetchall()
    decisions = decision_projection(conn, as_of)
    result: list[dict[str, Any]] = []
    for row in rows:
        decision = decisions.get(str(row["id"]))
        if decision is None:
            continue
        result.append({**dict(row), "decision": decision})
    return result
