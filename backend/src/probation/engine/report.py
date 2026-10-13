"""Report card aggregation and evaluation summaries.

Authority: docs/ENGINE_SPEC.md section 17 and docs/EVALUATION_PLAN.md section 4.
"""

import sqlite3
from typing import Any

from probation.core.enums import GateDecision


def generate_report_card(
    conn: sqlite3.Connection,
    family: str | None = None,
    as_of: str | None = None,
    b0_predictions: dict[str, str] | None = None,
    b2_predictions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate aggregate report card metrics across packs and families.

    Authority: docs/ENGINE_SPEC.md section 17:
    - same = proposals where action == observed_action (strong outcomes only)
    - different = strong outcome and action != observed_action
    - would_ask = proposals with gate == ASK or action == ABSTAIN
    - Items with no outcome (censored) are listed separately and excluded from same/different.
    """
    cur = conn.cursor()
    query = """
        SELECT
            p.id,
            p.situation_id,
            p.family,
            p.action,
            p.gate,
            p.proposed_at,
            o.observed_action,
            o.strength,
            o.known_at
        FROM proposals p
        LEFT JOIN outcomes o ON p.situation_id = o.situation_id
        WHERE 1=1
    """
    params: list[Any] = []
    if family is not None:
        query += " AND p.family = ?"
        params.append(family)
    if as_of is not None:
        query += " AND p.proposed_at <= ?"
        params.append(as_of)

    query += " ORDER BY p.proposed_at ASC;"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    same = 0
    different = 0
    would_ask = 0
    censored = 0

    b0_same = 0
    b2_same = 0

    for r in rows:
        sit_id = str(r["situation_id"])
        action = str(r["action"])
        gate = str(r["gate"])
        obs_action = r["observed_action"]
        strength = r["strength"]
        known_at = r["known_at"]

        # Check if censored (no outcome or outcome known in the future relative to as_of)
        if obs_action is None or (as_of is not None and known_at and known_at > as_of):
            censored += 1
            continue

        if strength != "STRONG":
            censored += 1
            continue

        obs_act_str = str(obs_action)
        if action == obs_act_str:
            same += 1
        else:
            different += 1

        if gate == GateDecision.ASK.value or action == "ABSTAIN":
            would_ask += 1

        if b0_predictions and sit_id in b0_predictions:
            if b0_predictions[sit_id] == obs_act_str:
                b0_same += 1

        if b2_predictions and sit_id in b2_predictions:
            if b2_predictions[sit_id] == obs_act_str:
                b2_same += 1

    total_evaluated = same + different
    accuracy = (same / total_evaluated) if total_evaluated > 0 else 0.0
    b0_acc = (b0_same / total_evaluated) if total_evaluated > 0 else 0.0
    b2_acc = (b2_same / total_evaluated) if total_evaluated > 0 else 0.0

    return {
        "as_of": as_of,
        "family": family or "all",
        "total_proposals": len(rows),
        "total_evaluated": total_evaluated,
        "same": same,
        "different": different,
        "would_ask": would_ask,
        "censored": censored,
        "accuracy": accuracy,
        "b0_accuracy": b0_acc,
        "b2_accuracy": b2_acc,
        "b0_same": b0_same,
        "b2_same": b2_same,
    }
