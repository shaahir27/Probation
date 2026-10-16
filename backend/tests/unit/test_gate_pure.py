"""Test T-GATE: Table-driven pure gate function evaluation.

Authority: docs/CONTRACT.md I-3, I-20, docs/ENGINE_SPEC.md section 7, and docs/TEST_PLAN.md section 3.2.
"""

import pytest

from probation.core.enums import GateDecision
from probation.engine.gate import decide_gate


@pytest.mark.parametrize(
    (
        "case_name",
        "kwargs",
        "expected_gate",
        "expected_reason",
        "expected_audit_holdout",
    ),
    [
        # 1. Budget exhausted -> ASK (fail_closed)
        (
            "Budget exhausted",
            {"budget_ok": False},
            GateDecision.ASK,
            "fail_closed",
            False,
        ),
        # 2. Reader failed, reader required -> ASK (fail_closed)
        (
            "Reader failed, reader required",
            {"reader_required": True, "reader_ok": False},
            GateDecision.ASK,
            "fail_closed",
            False,
        ),
        # 3. Reader and header facts disagree -> ASK (fail_closed)
        (
            "Reader and header facts disagree",
            {"deterministic_ok": False},
            GateDecision.ASK,
            "fail_closed",
            False,
        ),
        # 4. Hands-off file -> SHADOW (hands_off)
        (
            "Hands-off file",
            {"hands_off": "executable"},
            GateDecision.SHADOW,
            "hands_off",
            False,
        ),
        # 5. Level 0 -> SHADOW
        (
            "Level 0",
            {"licence_level": 0},
            GateDecision.SHADOW,
            None,
            False,
        ),
        # 6. Level 1 -> SUGGEST
        (
            "Level 1",
            {"licence_level": 1},
            GateDecision.SUGGEST,
            None,
            False,
        ),
        # 7. Cap below licence -> SUGGEST
        (
            "Cap below licence",
            {"licence_level": 3, "cap": 1},
            GateDecision.SUGGEST,
            None,
            False,
        ),
        # 8. Novel item -> ASK (novel)
        (
            "Novel item",
            {"licence_level": 2, "cap": 2, "novel": True},
            GateDecision.ASK,
            "novel",
            False,
        ),
        # 9. Economic test fails: REPLY (loss 40), p=0.95, licence_level=2 -> ASK (economic_test)
        # (1 - 0.95) * 40 = 2.0 >= attention_cost 1.0 -> asks
        (
            "Economic test fails",
            {
                "action": "REPLY",
                "loss": 40.0,
                "p": 0.95,
                "licence_level": 2,
                "cap": 2,
                "recallable": False,
            },
            GateDecision.ASK,
            "economic_test",
            False,
        ),
        # 10. Economic test passes, not recallable: REPLY, p=0.99, licence_level=2 -> HOLD_THEN_EXECUTE
        # (1 - 0.99) * 40 = 0.4 < 1.0 -> passes economic test, not recallable -> HOLD_THEN_EXECUTE
        (
            "Economic test passes, not recallable",
            {
                "action": "REPLY",
                "loss": 40.0,
                "p": 0.99,
                "licence_level": 2,
                "cap": 2,
                "recallable": False,
            },
            GateDecision.HOLD_THEN_EXECUTE,
            None,
            False,
        ),
        # 11. Economic test passes, recallable: ARCHIVE (loss 5), p=0.9, licence_level=2 -> EXECUTE_UNDO
        # (1 - 0.90) * 5 = 0.5 < 1.0 -> passes economic test, recallable -> EXECUTE_UNDO
        (
            "Economic test passes, recallable",
            {
                "action": "ARCHIVE",
                "loss": 5.0,
                "p": 0.90,
                "licence_level": 2,
                "cap": 3,
                "recallable": True,
            },
            GateDecision.EXECUTE_UNDO,
            None,
            False,
        ),
        # 12. Audit draw selected: licence_level=2, ARCHIVE, p=0.9, audit_draw=0.05 -> SUGGEST (audit_holdout=True)
        (
            "Audit draw selected",
            {
                "action": "ARCHIVE",
                "loss": 5.0,
                "p": 0.90,
                "licence_level": 2,
                "cap": 3,
                "recallable": True,
                "audit_draw": 0.05,
                "audit_fraction": 0.10,
            },
            GateDecision.SUGGEST,
            "audit_holdout",
            True,
        ),
        # 13. Level 3: ARCHIVE, licence_level=3, p=0.9, cap=3 -> EXECUTE_SILENT
        (
            "Level 3",
            {
                "action": "ARCHIVE",
                "loss": 5.0,
                "p": 0.90,
                "licence_level": 3,
                "cap": 3,
                "recallable": True,
            },
            GateDecision.EXECUTE_SILENT,
            None,
            False,
        ),
        # 14. Predicted no-op: action=LEAVE -> SHADOW
        (
            "Predicted no-op",
            {
                "action": "LEAVE",
                "cap": 0,
                "licence_level": 2,
            },
            GateDecision.SHADOW,
            None,
            False,
        ),
    ],
)
def test_t_gate_golden_table(
    case_name: str,
    kwargs: dict[str, object],
    expected_gate: GateDecision,
    expected_reason: str | None,
    expected_audit_holdout: bool,
) -> None:
    """Validate all cases in TEST_PLAN.md Golden Table 3.2."""
    # Base defaults matching table
    params: dict[str, object] = {
        "action": "ARCHIVE",
        "p": 0.95,
        "novel": False,
        "licence_level": 0,
        "cap": 3,
        "hands_off": None,
        "reader_required": False,
        "reader_ok": True,
        "deterministic_ok": True,
        "loss": 5.0,
        "attention_cost": 1.0,
        "recallable": True,
        "audit_draw": 0.5,
        "audit_fraction": 0.10,
        "budget_ok": True,
    }
    params.update(kwargs)

    res = decide_gate(
        action=str(params["action"]),
        p=float(params["p"]),  # type: ignore[arg-type]
        novel=bool(params["novel"]),
        licence_level=int(params["licence_level"]),  # type: ignore[arg-type]
        cap=int(params["cap"]),  # type: ignore[arg-type]
        hands_off=params["hands_off"] if params["hands_off"] is not None else None,  # type: ignore[arg-type]
        reader_required=bool(params["reader_required"]),
        reader_ok=bool(params["reader_ok"]),
        deterministic_ok=bool(params["deterministic_ok"]),
        loss=float(params["loss"]),  # type: ignore[arg-type]
        attention_cost=float(params["attention_cost"]),  # type: ignore[arg-type]
        recallable=bool(params["recallable"]),
        audit_draw=float(params["audit_draw"]),  # type: ignore[arg-type]
        audit_fraction=float(params["audit_fraction"]),  # type: ignore[arg-type]
        budget_ok=bool(params["budget_ok"]),
    )

    assert res.decision == expected_gate, (
        f"Case '{case_name}' failed decision: got {res.decision}, expected {expected_gate}"
    )
    if expected_reason is not None:
        assert res.reason == expected_reason, (
            f"Case '{case_name}' failed reason: got {res.reason}, expected {expected_reason}"
        )
    assert res.audit_holdout == expected_audit_holdout, (
        f"Case '{case_name}' failed audit_holdout: got {res.audit_holdout}, expected {expected_audit_holdout}"
    )
