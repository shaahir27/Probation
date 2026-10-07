"""Deterministic, pure gate function deciding autonomous execution level.

Authority: docs/CONTRACT.md invariant I-3 and docs/ENGINE_SPEC.md section 7.
"""

from probation.core.enums import GateDecision


def evaluate_gate(
    budget_ok: bool,
    reader_ok: bool,
    deterministic_ok: bool,
    hands_off_reason: str | None,
    licence_level: int,
    cap: int,
    novel: bool,
    p_max: float,
    audit_holdout: bool = False,
) -> GateDecision:
    """Evaluate pure gate logic to determine autonomous action permission.

    Enforces fail-closed semantics across all failure modes.
    """
    # Fail closed on budget, reader failure, or fact conflict
    if not budget_ok or not reader_ok or not deterministic_ok:
        return GateDecision.ASK

    # Safety hands-off block
    if hands_off_reason is not None:
        return GateDecision.SHADOW

    # Effective licence level capped by hard-coded and web caps
    effective_level = min(licence_level, cap)

    # Watch mode or novel situation
    if effective_level == 0 or novel:
        return GateDecision.SHADOW

    # Audit holdout forces suggestion to gather unbiased human ground truth
    if audit_holdout:
        return GateDecision.SUGGEST

    # Autonomy level dispatch
    if effective_level == 1:
        return GateDecision.SUGGEST
    elif effective_level == 2:
        return GateDecision.HOLD_THEN_EXECUTE
    elif effective_level == 3:
        return GateDecision.EXECUTE_IMMEDIATELY

    return GateDecision.SHADOW
