"""Test T-CUSUM and T-PSI: Statistical drift monitoring and Population Stability Index.

Authority: docs/ENGINE_SPEC.md section 11 and docs/TEST_PLAN.md.
"""

from probation.engine.drift import CUSUMTracker, compute_psi


def test_t_cusum_successes_keep_zero() -> None:
    """A run of successes keeps S at 0."""
    tracker = CUSUMTracker(baseline_err=0.03, allowance=0.02, threshold=5.0)

    for _ in range(50):
        alarm = tracker.update(is_error=False, is_undo=False, timestamp="2026-03-01T12:00:00Z")
        assert not alarm
        assert tracker.s == 0.0


def test_t_cusum_burst_of_errors_triggers_alarm() -> None:
    """A burst of errors raises S and alarms when reaching threshold 5.0."""
    tracker = CUSUMTracker(baseline_err=0.03, allowance=0.02, threshold=5.0)
    # Each error adds 1 - (0.03 + 0.02) = 0.95
    # 6 errors will give 6 * 0.95 = 5.7 >= 5.0
    alarm_triggered = False
    for i in range(6):
        alarm = tracker.update(is_error=True, is_undo=False, timestamp=f"2026-03-01T12:0{i}:00Z")
        if alarm:
            alarm_triggered = True
            break

    assert alarm_triggered
    # On alarm, S is reset to 0.0 and last_alarm_at is recorded
    assert tracker.s == 0.0
    assert tracker.last_alarm_at is not None


def test_t_cusum_two_undos_in_30_days_hard_rule() -> None:
    """Two or more undo or override events for the same (c, a) within 30 days alarms immediately."""
    tracker = CUSUMTracker(baseline_err=0.03, allowance=0.02, threshold=5.0)

    # First undo on day 1
    alarm1 = tracker.update(is_error=True, is_undo=True, timestamp="2026-03-01T10:00:00Z")
    assert not alarm1
    assert tracker.last_alarm_at is None

    # Second undo on day 15 (within 30 days) -> immediate alarm
    alarm2 = tracker.update(is_error=True, is_undo=True, timestamp="2026-03-15T10:00:00Z")
    assert alarm2
    assert tracker.last_alarm_at == "2026-03-15T10:00:00Z"
    assert tracker.s == 0.0


def test_t_cusum_undos_apart_do_not_trigger_immediate_alarm() -> None:
    """Two undos spaced more than 30 days apart do not trigger the 2-undo immediate alarm rule."""
    tracker = CUSUMTracker(baseline_err=0.03, allowance=0.02, threshold=5.0)

    # Undo 1 on Jan 1
    alarm1 = tracker.update(is_error=True, is_undo=True, timestamp="2026-01-01T10:00:00Z")
    assert not alarm1

    # Undo 2 on Feb 15 (45 days later) -> only regular error increment, no 2-in-30d alarm
    alarm2 = tracker.update(is_error=True, is_undo=True, timestamp="2026-02-15T10:00:00Z")
    assert not alarm2


def test_t_psi_identical_distribution_near_zero() -> None:
    """Identical reference and current distributions give PSI near 0."""
    dist = [0.1, 0.2, 0.4, 0.2, 0.1]
    psi = compute_psi(expected_dist=dist, actual_dist=dist)
    assert psi < 1e-6


def test_t_psi_shifted_distribution_exceeds_threshold() -> None:
    """A substantially shifted distribution exceeds PSI alarm threshold 0.25."""
    ref_dist = [0.2, 0.2, 0.2, 0.2, 0.2]
    shifted_dist = [0.01, 0.04, 0.15, 0.35, 0.45]

    psi = compute_psi(expected_dist=ref_dist, actual_dist=shifted_dist)
    assert psi > 0.25


def test_t_psi_floored_shares_no_infinities() -> None:
    """Empty buckets do not cause division by zero or log(0) because shares are floored at 1e-4."""
    ref_dist = [0.5, 0.5, 0.0]
    actual_dist = [0.0, 0.5, 0.5]

    psi = compute_psi(expected_dist=ref_dist, actual_dist=actual_dist)
    assert psi > 0.0
    assert not (psi != psi)  # not NaN
    assert psi != float("inf")
