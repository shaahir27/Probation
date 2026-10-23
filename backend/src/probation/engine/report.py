"""Bounded report cohorts with explicit denominators (ENGINE_SPEC 17)."""

import sqlite3
from collections.abc import Mapping
from typing import Any

from probation.core.clock import get_clock, timestamp_key
from probation.core.history import HistoryView


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def summarize_proposals(
    proposals: list[dict[str, Any]],
    decisions: Mapping[str, Mapping[str, Any]],
    b0_predictions: dict[str, str] | None,
    b2_predictions: dict[str, str] | None,
) -> dict[str, Any]:
    same = different = weak = unresolved = ineligible = non_abstained = 0
    baseline = {
        "b0": {"numerator": 0, "denominator": 0, "missing": 0},
        "b2": {"numerator": 0, "denominator": 0, "missing": 0},
    }
    tasks: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for p in proposals:
        tasks.setdefault((str(p["family"]), str(p["class_key"]), str(p["action"])), []).append(p)
        decision = decisions.get(str(p["situation_id"]))
        if decision is None:
            unresolved += 1
            continue
        if not decision.get("eligible", False):
            ineligible += 1
            continue
        if decision.get("strength") != "STRONG":
            weak += 1
            continue
        agree = p["action"] != "ABSTAIN" and p["action"] == decision.get("observed_action")
        same += int(agree)
        different += int(not agree)
        non_abstained += int(p["action"] != "ABSTAIN")
        for name, predictions in (("b0", b0_predictions), ("b2", b2_predictions)):
            sid = str(p["situation_id"])
            if predictions is None or sid not in predictions:
                baseline[name]["missing"] += 1
                continue
            baseline[name]["denominator"] += 1
            baseline[name]["numerator"] += int(predictions[sid] == decision.get("observed_action"))
    total = same + different
    asked = sum(p["gate"] == "ASK" or p["action"] == "ABSTAIN" for p in proposals)
    all_agreement = rate(same, total)
    baselines = {
        name: {**rate(x["numerator"], x["denominator"]), "missing": x["missing"]}
        for name, x in baseline.items()
    }
    return {
        "total_proposals": len(proposals),
        "total_evaluated": total,
        "same": same,
        "different": different,
        "would_ask": asked,
        "unresolved": unresolved,
        "weak": weak,
        "ineligible": ineligible,
        "censored": unresolved + weak + ineligible,
        "accuracy": all_agreement["rate"],
        "agreement_all": all_agreement,
        "agreement_non_abstained": rate(same, non_abstained),
        "coverage": rate(non_abstained, total),
        "baselines": baselines,
        "b0_accuracy": baselines["b0"]["rate"],
        "b2_accuracy": baselines["b2"]["rate"],
        "b0_same": baseline["b0"]["numerator"],
        "b2_same": baseline["b2"]["numerator"],
    }


def generate_report_card(
    conn: sqlite3.Connection,
    family: str | None = None,
    as_of: str | None = None,
    b0_predictions: dict[str, str] | None = None,
    b2_predictions: dict[str, str] | None = None,
    *,
    since: str | None = None,
    class_key: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    cutoff = as_of if as_of is not None else get_clock().now_iso()
    if since is not None and timestamp_key(since) > timestamp_key(cutoff):
        raise ValueError("invalid_report_period")
    history = HistoryView(conn, cutoff)
    proposals = [
        dict(p)
        for p in history.get_proposals(class_key=class_key, action=action)
        if (family is None or p["family"] == family)
        and (since is None or timestamp_key(str(p["proposed_at"])) >= timestamp_key(since))
    ]
    decisions = history.get_decision_projection()
    summary = summarize_proposals(proposals, decisions, b0_predictions, b2_predictions)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for p in proposals:
        if p["action"] != "ABSTAIN":
            groups.setdefault((p["family"], p["class_key"], p["action"]), []).append(p)
    tasks = []
    for (fam, key, act), rows in sorted(groups.items()):
        item = summarize_proposals(rows, decisions, b0_predictions, b2_predictions)
        sufficient = item["total_evaluated"] >= 3
        # Preserve the legacy display heuristic, explicitly separate from permission.
        attention = sufficient and (item["accuracy"] < 0.9 or item["different"] > 1)
        tasks.append(
            {
                **item,
                "family": fam,
                "class_key": key,
                "action": act,
                "status": "not_enough_history"
                if not sufficient
                else "needs_attention"
                if attention
                else "stable",
                "needs_attention": attention,
                "lagging": attention,
            }
        )
    tasks.sort(
        key=lambda item: (
            not item["needs_attention"],
            -item["total_evaluated"],
            item["class_key"],
            item["action"],
        )
    )
    return {
        **summary,
        "as_of": cutoff,
        "since": since,
        "family": family or "all",
        "class_key": class_key,
        "action": action,
        "tasks": tasks,
    }
