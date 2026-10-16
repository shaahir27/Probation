"""Engine package: Replay, featurization, policy, evidence, licences, gate, and examination.

Authority: docs/ENGINE_SPEC.md and docs/CONTRACT.md.
"""

from probation.engine.caps import (
    ACTION_CATALOG,
    BASE_ACTION_CAPS,
    get_action_cap,
    get_action_loss,
    get_conditional_cap,
    get_economic_bar,
    is_recallable,
)
from probation.engine.drift import (
    CUSUMTracker,
    check_family_shift,
    compute_psi,
)
from probation.engine.evidence import (
    ClassStats,
    aggregate_evidence,
    lower_bound,
)
from probation.engine.gate import (
    GateResult,
    compute_audit_draw,
    decide_gate,
    evaluate_gate,
)
from probation.engine.handsoff import is_hands_off
from probation.engine.licence import (
    check_exam_ok,
    derive_and_cache_licences,
    derive_licence_level,
)

__all__ = [
    "ACTION_CATALOG",
    "BASE_ACTION_CAPS",
    "CUSUMTracker",
    "ClassStats",
    "GateResult",
    "aggregate_evidence",
    "check_exam_ok",
    "check_family_shift",
    "compute_audit_draw",
    "compute_psi",
    "decide_gate",
    "derive_and_cache_licences",
    "derive_licence_level",
    "evaluate_gate",
    "get_action_cap",
    "get_action_loss",
    "get_conditional_cap",
    "get_economic_bar",
    "is_hands_off",
    "is_recallable",
    "lower_bound",
]
