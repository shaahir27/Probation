"""D3 family shift uses actual fitted coefficients and bounded observations."""

import json
from datetime import timedelta

import pytest

from probation.core.clock import format_timestamp, parse_timestamp
from probation.engine.policy import Policy
from probation.engine.shift import assess_shift, selected_features

T = "2026-06-01T00:00:00Z"


def fitted_policy():
    policy = Policy("email_action")
    policy.fit(
        [{"reader_intent": "fyi", **{f"decoy{i}": 0 for i in range(6)}}] * 120
        + [{"reader_intent": "request", **{f"decoy{i}": 0 for i in range(6)}}] * 120,
        ["ARCHIVE"] * 120 + ["REPLY"] * 120,
        ["2026-01-01T00:00:00Z"] * 240,
        as_of=T,
    )
    assert policy.is_fitted
    return policy


def test_reader_feature_is_selected_by_actual_coefficients_and_shifted():
    policy = fitted_policy()
    assert selected_features(policy)[0] == "reader_intent"
    result = assess_shift(
        policy, [{"reader_intent": "fyi"}] * 30, [{"reader_intent": "request"}] * 15
    )
    assert result["status"] == "available"
    assert result["alarm"] is True
    assert result["policy_version"] == policy.policy_version
    assert result["features"]["reader_intent"]["psi"] > 0.25


def test_identical_feature_populations_are_quiet():
    result = assess_shift(
        fitted_policy(), [{"reader_intent": "fyi"}] * 30, [{"reader_intent": "fyi"}] * 15
    )
    assert result["alarm"] is False
    assert result["max_psi"] == 0


@pytest.mark.parametrize("policy", [None, Policy("email_action")])
def test_missing_or_unfitted_policy_is_unavailable_not_no_shift(policy):
    result = assess_shift(policy, [{}] * 30, [{}] * 15)
    assert result["status"] == "policy_unavailable"
    assert result["alarm"] is None


def test_small_population_and_invalid_numbers_are_explicit():
    policy = fitted_policy()
    assert assess_shift(policy, [{}] * 19, [{}] * 15)["status"] == "insufficient_data"
    numeric = Policy("email_action")
    numeric.fit(
        [{"score": 0.0}] * 120 + [{"score": 1.0}] * 120,
        ["ARCHIVE"] * 120 + ["REPLY"] * 120,
        ["2026-01-01T00:00:00Z"] * 240,
        as_of=T,
    )
    result = assess_shift(numeric, [{"score": 0.0}] * 30, [{"score": float("nan")}] * 15)
    assert result["status"] == "invalid_features"
    assert result["alarm"] is None
    shifted = assess_shift(numeric, [{"score": 0.0}] * 30, [{"score": 1.0}] * 15)
    assert shifted["alarm"] is True


def test_family_shift_observations_are_known_bounded_and_windows_disjoint(memory_db):
    from probation.core.history import HistoryView

    memory_db.execute("INSERT INTO sources VALUES ('shift','mail','synthetic','shift',?)", (T,))
    for index, days in enumerate([120, 31, 30, 0, -1]):
        occurred = format_timestamp(parse_timestamp(T) - timedelta(days=days))
        known = T if index != 3 else "2026-06-02T00:00:00Z"
        key = f"shift-{index}"
        memory_db.execute(
            "INSERT INTO raw_items VALUES (?, 'shift','mail','mail_in',?,?,?,'{}','h')",
            (key, key, occurred, known),
        )
        memory_db.execute(
            "INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,content_hash,created_at) VALUES (?,?,'mail','email_action',?,'h',?)",
            (key, key, occurred, known),
        )
        memory_db.execute(
            "INSERT INTO features(situation_id,deterministic_json,reader_json,reader_ok,featurizer_version,features_hash,created_at) VALUES (?,'{}',?,1,'v','h',?)",
            (key, json.dumps({"reader_intent": "fyi"}), known),
        )
    memory_db.commit()
    reference, current = HistoryView(memory_db, T).shift_populations("email_action", "v")
    assert len(reference) == 2
    assert len(current) == 1
