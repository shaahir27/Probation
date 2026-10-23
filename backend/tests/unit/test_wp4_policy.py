"""WP4 regressions: temporal calibration, vocabulary, identity and encoding."""

import copy

import pytest

from probation.engine.features import FeatureEncoder, FeatureValidationError
from probation.engine.policy import Policy


def data(n: int = 240):
    from datetime import UTC, datetime, timedelta

    times = [(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i)).isoformat() for i in range(n)]
    rows = [{"z_number": float(i % 3), "a_category": "odd" if i % 2 else "even"} for i in range(n)]
    labels = ["REPLY" if i % 2 else "ARCHIVE" for i in range(n)]
    return rows, labels, times


def test_encoder_names_and_values_share_one_order():
    encoder = FeatureEncoder().fit([{"z": 1, "a": "one"}, {"z": 3, "a": "two"}])
    assert encoder.encoded_feature_names == ["z", "a=one", "a=two"]
    assert encoder.transform_row({"z": 3, "a": "two"}) == [1, 0, 1]
    encoder.fit([])
    assert encoder.encoded_feature_names == []
    assert encoder.transform_row({"z": 9}) == []


@pytest.mark.parametrize("values", [[1, "mixed"], [float("nan"), 1], [float("inf"), 1]])
def test_encoder_rejects_invalid_and_clears_old_state(values):
    encoder = FeatureEncoder().fit([{"x": 1}])
    with pytest.raises(FeatureValidationError):
        encoder.fit([{"x": v} for v in values])
    assert not encoder.fitted


def test_production_cold_start_is_200_and_refit_clears_state():
    rows, labels, times = data()
    policy = Policy("email_action")
    policy.fit(rows[:199], labels[:199], times[:199], times[-1])
    assert not policy.is_fitted
    policy.fit(rows[:200], labels[:200], times[:200], times[-1])
    assert policy.is_fitted
    policy.fit(rows[:1], labels[:1], times[:1], times[-1])
    assert not policy.is_fitted and policy.temperature == 1


def test_oof_is_temporal_purged_and_final_state_reproducible():
    rows, labels, times = data()
    original = copy.deepcopy(rows)
    known = times.copy()
    known[0] = times[-1]  # earlier arrival's answer is unavailable to every fold
    policy = Policy("email_action").fit(rows, labels, times, times[-1], known_at=known)
    assert rows == original and policy.is_fitted
    assert policy.calibration["usable_rows"] > 0
    for fold in policy.calibration["folds"]:
        if fold["status"] == "ok":
            assert fold["max_train_known_at"] <= fold["validation_start"]
            assert fold["max_train_occurred_at"] < fold["validation_start"]
            assert 0 not in fold["training_indices"]
    other = Policy("email_action").fit(rows, labels, times, times[-1], known_at=known)
    assert policy.policy_digest == other.policy_digest
    assert len(policy.policy_digest) == 64 and len(policy.policy_version) == 12
    action, p, probs, _ = policy.predict(rows[0])
    assert action in labels and 0 <= p <= 1 and sum(probs.values()) == pytest.approx(1)
    explanation = policy.explain(rows[0])
    assert explanation["intercept"] + sum(
        x["contribution"] for x in explanation["contributions"]
    ) == pytest.approx(explanation["logit"])


def test_delayed_labels_and_same_instant_fallback():
    rows, labels, times = data()
    p = Policy("email_action").fit(rows, labels, [times[0]] * len(rows), times[-1])
    assert p.temperature == 1 and p.calibration["status"] == "insufficient_time_groups"
    with pytest.raises(ValueError):
        p.fit(rows, labels, times, times[0])
    assert not p.is_fitted


def test_files_use_training_counts_case_and_other_abstention():
    rows = [
        {"name_tokens": ["Common", "Rare" if i == 0 else "Main"], "x": i % 2} for i in range(40)
    ]
    labels = ["MOVE_TO_FOLDER:Course/A"] * 20 + [f"MOVE_TO_FOLDER:Rare/{i}" for i in range(20)]
    times = ["2026-01-01T00:00:00Z"] * 40
    p = Policy("file_destination", cold_start_min=5).fit(rows, labels, times, times[0])
    assert p.is_fitted and p.classes == ["MOVE_TO_FOLDER:Course/A", "OTHER"]
    assert p.vocabulary.tokens[0] == "common"
    assert "DELETE" not in p.classes


def test_version_covers_coefficients_beyond_twenty():
    rows, labels, times = data()
    rows = [{**r, **{f"n{j}": float((i + j) % 7) for j in range(30)}} for i, r in enumerate(rows)]
    p = Policy("email_action").fit(rows, labels, times, times[-1])
    before = p.state_digest()
    p.model.coef_[0, 25] += 1e-10
    assert p.state_digest() != before


def test_optimizer_failure_is_reported_fallback(monkeypatch):
    from probation.engine import calibration

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic optimizer failure")

    monkeypatch.setattr(calibration, "minimize_scalar", fail)
    rows, labels, times = data()
    p = Policy("email_action").fit(rows, labels, times, times[-1])
    assert p.is_fitted and p.temperature == 1
    assert p.calibration["status"] == "optimizer_failed"
