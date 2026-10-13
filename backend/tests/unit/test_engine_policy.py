"""Test T-POLICY: Calibrated policy training, decay weights, cold start, and predictions.

Authority: docs/ENGINE_SPEC.md section 4, and docs/TEST_PLAN.md T-POLICY.
"""

from probation.engine.policy import Policy


def test_t_policy_cold_start() -> None:
    """Fewer than minimum situations or fewer than 2 distinct actions returns ABSTAIN."""
    policy = Policy(family="email_action", cold_start_min=10)

    # 1. Unfitted policy
    act, p_max, probs, reasons = policy.predict({"has_attachment": False})
    assert act == "ABSTAIN"
    assert p_max == 1.0
    assert probs == {"ABSTAIN": 1.0}
    assert "cold_start" in reasons

    # 2. Fewer than 10 rows
    rows = [{"looks_automated": True} for _ in range(5)]
    actions = ["ARCHIVE", "ARCHIVE", "REPLY", "ARCHIVE", "REPLY"]
    timestamps = ["2026-01-01T10:00:00Z"] * 5
    policy.fit(rows, actions, timestamps, as_of="2026-01-05T10:00:00Z")
    assert not policy.is_fitted
    act, _, _, reasons = policy.predict({"looks_automated": True})
    assert act == "ABSTAIN"
    assert "cold_start" in reasons

    # 3. >= 10 rows but only 1 distinct action
    rows_mono = [{"looks_automated": True} for _ in range(12)]
    actions_mono = ["ARCHIVE"] * 12
    timestamps_mono = ["2026-01-01T10:00:00Z"] * 12
    policy.fit(rows_mono, actions_mono, timestamps_mono, as_of="2026-01-05T10:00:00Z")
    assert not policy.is_fitted
    act, _, _, reasons = policy.predict({"looks_automated": True})
    assert act == "ABSTAIN"
    assert "cold_start" in reasons


def test_t_policy_fit_and_probabilities_sum_to_one() -> None:
    """Fitted policy probabilities sum to 1.0 and temperature stays within [0.5, 5.0]."""
    policy = Policy(family="email_action", cold_start_min=5)

    rows = []
    actions = []
    timestamps = []
    for i in range(120):
        is_news = i % 2 == 0
        rows.append(
            {
                "looks_automated": is_news,
                "sender_known": not is_news,
                "thread_length": 1 if is_news else 4,
            }
        )
        actions.append("ARCHIVE" if is_news else "REPLY")
        timestamps.append(f"2026-01-{(i % 28) + 1:02d}T10:00:00Z")

    policy.fit(rows, actions, timestamps, as_of="2026-02-01T10:00:00Z")
    assert policy.is_fitted
    assert len(policy.policy_version) == 12

    # Check temperature bounds [0.5, 5.0]
    assert 0.5 <= policy.temperature <= 5.0

    # Test prediction
    act, p_max, probs, reasons = policy.predict(
        {"looks_automated": True, "sender_known": False, "thread_length": 1}
    )
    assert act in ("ARCHIVE", "REPLY")
    assert 0.0 <= p_max <= 1.0
    assert abs(sum(probs.values()) - 1.0) < 1e-5
    assert reasons == []
