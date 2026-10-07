"""Engine package: Replay, featurization, policy, evidence, licences, gate, and examination.

Authority: docs/ENGINE_SPEC.md and docs/CONTRACT.md.
"""

from probation.engine.caps import get_action_cap
from probation.engine.gate import evaluate_gate
from probation.engine.handsoff import is_hands_off

__all__ = [
    "evaluate_gate",
    "get_action_cap",
    "is_hands_off",
]
