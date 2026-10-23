"""Pure eligibility and fitting adapter for HistoryView-owned bounded records."""

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from probation.core.history import HistoryView
from probation.core.training_labels import valid_label
from probation.engine.policy import Policy


@dataclass(frozen=True)
class TrainingRow:
    situation_id: str
    family: str
    occurred_at: str
    known_at: str
    action: str
    features: dict[str, Any]
    redacted_text: str
    semantic_version: str
    features_hash: str
    ledger_seq: int
    source: str
    strength: str
    observed_at: str | None


@dataclass(frozen=True)
class TrainingCohort:
    rows: tuple[TrainingRow, ...]
    excluded: dict[str, int]


def build_cohort(history: HistoryView, family: str, semantic_version: str) -> TrainingCohort:
    rows: list[TrainingRow] = []
    excluded: Counter[str] = Counter()
    for record in history.get_training_records(family):
        event = record["decision"]
        action = event.get("observed_action", "")
        reason = ""
        if not event.get("eligible"):
            reason = str(event.get("reason", "ineligible_decision"))
        elif event.get("strength") != "STRONG":
            reason = "weak_outcome"
        elif not record["reader_ok"] or record["hands_off_reason"] is not None:
            reason = "invalid_or_hands_off"
        elif record["featurizer_version"] != semantic_version:
            reason = "incompatible_features"
        elif not valid_label(family, action):
            reason = "unsupported_label"
        if reason:
            excluded[reason] += 1
            continue
        det, reader = (
            json.loads(record["deterministic_json"]),
            json.loads(record["reader_json"] or "{}"),
        )
        if det.get("__reader_required") is True and not reader:
            excluded["missing_required_reader"] += 1
            continue
        if not det.get("__deterministic_ok", True) or not det.get("__budget_ok", True):
            excluded["failed_feature_status"] += 1
            continue
        if set(det) & set(reader):
            excluded["feature_key_collision"] += 1
            continue
        features = {k: v for k, v in {**det, **reader}.items() if not k.startswith("__")}
        if family == "file_destination":
            # This raw current-item field was already bounded by HistoryView.
            from probation.core.file_tokens import tokenize_name

            payload = json.loads(record["payload_json"])
            features["name_tokens"] = sorted(tokenize_name(str(payload.get("filename", ""))))
        rows.append(
            TrainingRow(
                str(record["id"]),
                family,
                str(record["occurred_at"]),
                str(event["known_at"]),
                str(action),
                features,
                str(det.get("__novelty_text", record["redacted_text"]) or "")[:4000],
                semantic_version,
                str(record["features_hash"]),
                int(event["ledger_seq"]),
                str(event["source"]),
                str(event["strength"]),
                str(event["observed_at"]) if event.get("observed_at") is not None else None,
            )
        )
    return TrainingCohort(tuple(rows), dict(excluded))


def fit_cohort(policy: Policy, cohort: TrainingCohort, as_of: str) -> Policy:
    rows = cohort.rows
    return policy.fit(
        [r.features for r in rows],
        [r.action for r in rows],
        [r.occurred_at for r in rows],
        as_of,
        known_at=[r.known_at for r in rows],
        situation_ids=[r.situation_id for r in rows],
        provenance={
            "semantic_versions": sorted({r.semantic_version for r in rows}),
            "features": [[r.situation_id, r.features_hash] for r in rows],
            "decision_provenance": [
                [r.situation_id, r.ledger_seq, r.source, r.strength] for r in rows
            ],
        },
    )
