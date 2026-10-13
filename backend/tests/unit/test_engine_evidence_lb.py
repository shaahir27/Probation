"""Test T-LB: Beta quantile lower bound and golden numbers table.

Authority: docs/ENGINE_SPEC.md sections 6.2 and 16, and docs/TEST_PLAN.md T-LB.
"""

import pytest

from probation.engine.evidence import lower_bound


def test_t_lb_golden_numbers() -> None:
    """Assert all 10 cases in ENGINE_SPEC.md section 16 pass within exact tolerance."""
    # 1. No parent, k=n=58 -> LB >= 0.95
    lb1 = lower_bound(k=58, n=58)
    assert lb1 >= 0.95, f"Case 1 failed: {lb1}"

    # 2. No parent, k=n=57 -> LB < 0.95
    lb2 = lower_bound(k=57, n=57)
    assert lb2 < 0.95, f"Case 2 failed: {lb2}"

    # 3. No parent, k=n=148 -> LB >= 0.98
    lb3 = lower_bound(k=148, n=148)
    assert lb3 >= 0.98, f"Case 3 failed: {lb3}"

    # 4. No parent, k=n=147 -> LB < 0.98
    lb4 = lower_bound(k=147, n=147)
    assert lb4 < 0.98, f"Case 4 failed: {lb4}"

    # 5. No parent, k=n=60 -> 0.952 +/- 0.001
    lb5 = lower_bound(k=60, n=60)
    assert abs(lb5 - 0.952) <= 0.001, f"Case 5 failed: {lb5}"

    # 6. No parent, k=41, n=42 -> 0.894 +/- 0.003
    lb6 = lower_bound(k=41, n=42)
    assert abs(lb6 - 0.894) <= 0.003, f"Case 6 failed: {lb6}"

    # 7. Parent mean 0.99, kappa=10, k=n=48 -> LB < 0.95
    lb7 = lower_bound(k=48, n=48, parent_mean=0.99, kappa=10.0)
    assert lb7 < 0.95, f"Case 7 failed: {lb7}"

    # 8. Parent mean 0.99, kappa=10, k=n=49 -> LB >= 0.95
    lb8 = lower_bound(k=49, n=49, parent_mean=0.99, kappa=10.0)
    assert lb8 >= 0.95, f"Case 8 failed: {lb8}"

    # 9. Parent mean 0.99, kappa=10, k=n=40 -> 0.9417 +/- 0.002
    lb9 = lower_bound(k=40, n=40, parent_mean=0.99, kappa=10.0)
    assert abs(lb9 - 0.9417) <= 0.002, f"Case 9 failed: {lb9}"


def test_t_lb_edge_cases() -> None:
    """Test lower_bound edge cases and validation."""
    assert lower_bound(k=0, n=0) == 0.0

    with pytest.raises(ValueError):
        lower_bound(k=5, n=4)

    with pytest.raises(ValueError):
        lower_bound(k=-1, n=5)
