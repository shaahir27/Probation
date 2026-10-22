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
            p.class_key,
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
        query += " AND p.proposed_at COLLATE UTC_TIMESTAMP <= ?"
        params.append(as_of)

    query += " ORDER BY p.proposed_at COLLATE UTC_TIMESTAMP ASC;"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    same = 0
    different = 0
    would_ask = 0
    censored = 0

    b0_same = 0
    b2_same = 0

    task_groups: dict[tuple[str, str], dict[str, Any]] = {}

    for r in rows:
        sit_id = str(r["situation_id"])
        action = str(r["action"])
        gate = str(r["gate"])
        obs_action = r["observed_action"]
        strength = r["strength"]
        known_at = r["known_at"]
        class_key = str(r["class_key"]) if "class_key" in r.keys() else "unknown"
        task_family = str(r["family"])

        t_key = (class_key, action)
        if t_key not in task_groups:
            task_groups[t_key] = {
                "class_key": class_key,
                "action": action,
                "family": task_family,
                "same": 0,
                "different": 0,
                "would_ask": 0,
                "censored": 0,
            }

        # Check if censored (no outcome or outcome known in the future relative to as_of)
        if obs_action is None or (as_of is not None and known_at and known_at > as_of):
            censored += 1
            task_groups[t_key]["censored"] += 1
            continue

        if strength != "STRONG":
            censored += 1
            task_groups[t_key]["censored"] += 1
            continue

        obs_act_str = str(obs_action)
        if action == obs_act_str:
            same += 1
            task_groups[t_key]["same"] += 1
        else:
            different += 1
            task_groups[t_key]["different"] += 1

        if gate == GateDecision.ASK.value or action == "ABSTAIN":
            would_ask += 1
            task_groups[t_key]["would_ask"] += 1

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

    tasks_list: list[dict[str, Any]] = []
    for (ck, act), stats in task_groups.items():
        if act == "ABSTAIN":
            continue
        t_eval = stats["same"] + stats["different"]
        if t_eval < 3:
            status = "not_enough_history"
            needs_attention = False
            t_acc: float | None = None
        elif (stats["same"] / t_eval) >= 0.90 and stats["different"] <= 1:
            status = "stable"
            needs_attention = False
            t_acc = stats["same"] / t_eval
        else:
            status = "needs_attention"
            needs_attention = True
            t_acc = stats["same"] / t_eval

        tasks_list.append(
            {
                "class_key": ck,
                "action": act,
                "family": stats["family"],
                "total_evaluated": t_eval,
                "same": stats["same"],
                "different": stats["different"],
                "would_ask": stats["would_ask"],
                "censored": stats["censored"],
                "accuracy": t_acc,
                "needs_attention": needs_attention,
                "lagging": needs_attention,
                "status": status,
            }
        )

    # Sort attention-first, then by total evaluated descending
    tasks_list.sort(key=lambda x: (not x["needs_attention"], -x["total_evaluated"]))

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
        "tasks": tasks_list,
    }
