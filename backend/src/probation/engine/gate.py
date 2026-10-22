"""Deterministic, pure gate function deciding autonomous execution level.

Authority: docs/CONTRACT.md invariant I-3, I-20 and docs/ENGINE_SPEC.md section 7.
"""

import hashlib
import math
from dataclasses import dataclass
from typing import Final

from probation.core.enums import GateDecision

DEFAULT_AUDIT_SEED: Final[str] = "probation-audit-v1"


@dataclass(frozen=True, slots=True)
class GateResult:
    """Outcome of pure gate decision evaluation."""

    decision: GateDecision
    reason: str | None = None
    audit_holdout: bool = False


def compute_audit_draw(situation_id: str, seed: str = DEFAULT_AUDIT_SEED) -> float:
    """Compute reproducible uniform [0, 1) float for audit holdout.

    Authority: docs/ENGINE_SPEC.md section 7:
    audit_draw = int(sha256(situation_id + "|" + AUDIT_SEED)[:8], 16) / 2**32
    """
    digest = hashlib.sha256(f"{situation_id}|{seed}".encode()).hexdigest()
    return int(digest[:8], 16) / float(2**32)


def decide_gate(
    *,
    action: str = "ARCHIVE",
    p: float = 1.0,
    novel: bool = False,
    licence_level: int = 0,
    cap: int = 3,
    hands_off: str | None = None,
    reader_required: bool = False,
    reader_ok: bool = True,
    deterministic_ok: bool = True,
    loss: float = 0.0,
    attention_cost: float = 1.0,
    recallable: bool = False,
    audit_draw: float = 0.5,
    audit_fraction: float = 0.10,
    budget_ok: bool = True,
) -> GateResult:
    """Evaluate pure gate logic to determine autonomous action permission.

    Enforces fail-closed semantics across all failure modes in exact contract order:
    1. Fail closed on budget exhaustion, reader failure, or deterministic fact conflict.
    2. Hands-off safety veto.
    3. Effective licence level cap = min(licence_level, cap).
    4. Level 0 -> SHADOW; Level 1 -> SUGGEST.
    5. Level >= 2:
       - Novelty -> ASK("novel")
       - Strict economic test: (1 - p) * loss >= attention_cost -> ASK("economic_test")
       - Audit holdout draw < audit_fraction -> SUGGEST("audit_holdout")
       - Level 3 -> EXECUTE_SILENT
       - Level 2 -> EXECUTE_UNDO (if recallable) else HOLD_THEN_EXECUTE
    """
    # 1. Fail closed on budget, reader failure, or fact conflict
    if not budget_ok or not deterministic_ok or (reader_required and not reader_ok):
        return GateResult(decision=GateDecision.ASK, reason="fail_closed")
    if (
        type(p) not in {int, float}
        or not math.isfinite(p)
        or not 0 <= p <= 1
        or type(licence_level) is not int
        or not 0 <= licence_level <= 3
        or type(cap) is not int
        or not 0 <= cap <= 3
        or not all(
            type(value) in {int, float} and math.isfinite(value)
            for value in (loss, attention_cost, audit_draw, audit_fraction)
        )
        or loss < 0
        or attention_cost < 0
        or not 0 <= audit_draw < 1
        or not 0 <= audit_fraction <= 1
    ):
        return GateResult(decision=GateDecision.ASK, reason="invalid_gate_input")

    # 2. Safety hands-off block
    if hands_off is not None:
        return GateResult(decision=GateDecision.SHADOW, reason="hands_off")

    # 3. Effective licence level capped by hard-coded and contextual caps
    effective_level = min(licence_level, cap)

    # Watch mode or predicted no-op (cap 0)
    if effective_level == 0:
        return GateResult(decision=GateDecision.SHADOW)

    # Level 1: Suggestion mode
    if effective_level == 1:
        return GateResult(decision=GateDecision.SUGGEST)

    # 4. Effective level >= 2: Autonomous execution tiers
    if novel:
        return GateResult(decision=GateDecision.ASK, reason="novel")

    # Strict economic test: only act alone if expected loss < attention_cost
    # At exactly p*, (1 - p) * loss == attention_cost -> asks!
    if (1.0 - p) * loss >= attention_cost:
        return GateResult(decision=GateDecision.ASK, reason="economic_test")

    # Audit holdout forces suggestion to gather unbiased human ground truth (Invariant I-11)
    if audit_draw < audit_fraction:
        return GateResult(
            decision=GateDecision.SUGGEST,
            reason="audit_holdout",
            audit_holdout=True,
        )

    # Autonomous execution
    if effective_level == 3:
        return GateResult(decision=GateDecision.EXECUTE_SILENT)

    if recallable:
        return GateResult(decision=GateDecision.EXECUTE_UNDO)
    else:
        return GateResult(decision=GateDecision.HOLD_THEN_EXECUTE)


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
    action: str = "ARCHIVE",
    loss: float = 5.0,
    recallable: bool = True,
    reader_required: bool = True,
) -> GateDecision:
    """Wrapper function preserving backward compatibility with Phase 4."""
    result = decide_gate(
        action=action,
        p=p_max,
        novel=novel,
        licence_level=licence_level,
        cap=cap,
        hands_off=hands_off_reason,
        reader_required=reader_required,
        reader_ok=reader_ok,
        deterministic_ok=deterministic_ok,
        loss=loss,
        recallable=recallable,
        audit_draw=0.0 if audit_holdout else 0.5,
        audit_fraction=0.10,
        budget_ok=budget_ok,
    )
    return result.decision
