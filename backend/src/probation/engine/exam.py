"""Examination board orchestration and counterfactual evaluation.

Authority: docs/CONTRACT.md invariants I-2, I-3, I-14, I-20 and docs/ENGINE_SPEC.md section 15.
Verdicts are computed strictly by deterministic code, never by an LLM.
"""

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import ClockMode, GateDecision, LedgerKind
from probation.core.hashing import canonical_json
from probation.core.types import ExamOperator
from probation.db.ledger import append_ledger
from probation.engine.caps import BASE_ACTION_CAPS, get_action_loss, is_recallable
from probation.engine.gate import compute_audit_draw, decide_gate
from probation.engine.policy import Policy
from probation.llm.redact import redact_text
from probation.packs.calendar.exam_ops import (
    CALENDAR_EXAM_OPERATORS,
    apply_calendar_operator,
    validate_calendar_operator_result,
)
from probation.packs.files.exam_ops import (
    FILES_EXAM_OPERATORS,
    apply_files_code_operator,
    validate_files_operator_result,
)
from probation.packs.mail.exam_ops import (
    MAIL_EXAM_OPERATORS,
    apply_mail_operator,
    validate_mail_operator_result,
)


def autonomy_rank(decision: GateDecision | str) -> int:
    """Return autonomy rank for a gate decision.

    Authority: docs/ENGINE_SPEC.md section 15.2:
    SHADOW=0, ASK=1, SUGGEST=1, HOLD_THEN_EXECUTE=2, EXECUTE_UNDO=2, EXECUTE_SILENT=3.
    """
    d = str(decision).upper()
    if d == "SHADOW":
        return 0
    elif d in ("ASK", "SUGGEST"):
        return 1
    elif d in ("HOLD_THEN_EXECUTE", "EXECUTE_UNDO"):
        return 2
    elif d in ("EXECUTE_SILENT", "EXECUTE_IMMEDIATELY"):
        return 3
    return 0


@dataclass(frozen=True, slots=True)
class ExamRunResult:
    """Structured result of an examination board run."""

    run_id: str
    class_key: str
    action: str
    level_tested: int
    passed: bool
    n_cases: int
    invariance_flip_rate: float | None
    critical_violations: int
    other_violation_rate: float | None
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_exam_run(
    class_key: str,
    action: str,
    level_tested: int,
    cases: list[dict[str, Any]],
    min_valid_cases: int | None = None,
    max_flip_rate: float | None = None,
    max_critical_violations: int | None = None,
    max_other_violation_rate: float | None = None,
) -> dict[str, Any]:
    """Evaluate invariance and directional checks across counterfactual exam cases.

    Authority: docs/ENGINE_SPEC.md section 15.1 Step 6.
    Verdicts are computed strictly by deterministic code, never by an LLM.
    """
    min_cases = min_valid_cases if min_valid_cases is not None else settings.exam_min_valid_cases
    flips_limit = max_flip_rate if max_flip_rate is not None else settings.exam_invariance_max_flip
    crit_limit = (
        max_critical_violations
        if max_critical_violations is not None
        else settings.exam_critical_max_violations
    )
    other_limit = (
        max_other_violation_rate
        if max_other_violation_rate is not None
        else settings.exam_other_max_violation_rate
    )

    n_cases = len(cases)
    if n_cases < min_cases:
        return {
            "passed": False,
            "reason": "insufficient_cases",
            "n_cases": n_cases,
            "min_valid_cases": min_cases,
            "invariance_flip_rate": None,
            "critical_violations": 0,
            "other_violation_rate": None,
        }

    invariance_cases = 0
    invariance_flips = 0
    critical_violations = 0
    other_cases = 0
    other_violations = 0

    for c in cases:
        expectation = str(c.get("expectation", ""))
        is_crit = bool(c.get("critical", False))
        violated = bool(c.get("violated", False))

        if expectation == "invariant":
            invariance_cases += 1
            if violated:
                invariance_flips += 1
                if is_crit:
                    critical_violations += 1
        elif expectation == "no_more_autonomous":
            if is_crit:
                if violated:
                    critical_violations += 1
            else:
                other_cases += 1
                if violated:
                    other_violations += 1

    flip_rate = float(invariance_flips) / float(invariance_cases) if invariance_cases > 0 else 0.0
    other_rate = float(other_violations) / float(other_cases) if other_cases > 0 else 0.0

    passed = (
        n_cases >= min_cases
        and flip_rate <= flips_limit
        and critical_violations <= crit_limit
        and other_rate <= other_limit
    )

    return {
        "passed": passed,
        "n_cases": n_cases,
        "invariance_cases": invariance_cases,
        "invariance_flips": invariance_flips,
        "invariance_flip_rate": flip_rate,
        "critical_violations": critical_violations,
        "other_cases": other_cases,
        "other_violations": other_violations,
        "other_violation_rate": other_rate,
    }


def _get_pack_operators(pack_name: str) -> list[ExamOperator]:
    """Retrieve registered operators for the given pack."""
    norm = pack_name.lower().strip()
    if norm in ("mail", "email"):
        return MAIL_EXAM_OPERATORS
    elif norm in ("cal", "calendar"):
        return CALENDAR_EXAM_OPERATORS
    elif norm in ("file", "files"):
        return FILES_EXAM_OPERATORS
    return []


def run_exam(
    conn: sqlite3.Connection,
    class_key: str,
    action: str,
    level_tested: int = 2,
    as_of: str | None = None,
    seed: int = 42,
    policy: Policy | Any = None,
    llm_client: Any = None,
    model_id: str | None = None,
    clock: Clock | None = None,
) -> ExamRunResult:
    """Execute counterfactual examination for a (class_key, action) pair.

    Authority: docs/ENGINE_SPEC.md section 15.
    1. Sample up to EXAM_N base situations from class c with proposal action a and known outcome.
    2. Filter to action-taking base cases (autonomy_rank >= 2 at licence_level = level_tested).
    3. Apply pack perturbation operators with code-side validators.
    4. Re-evaluate pipeline on valid edits: redact, clues, policy, gate.
    5. Compute deterministic verdicts: invariance flip rate, critical violations, other rate.
    6. Record exam_runs, exam_cases, and append hash-chained exam_run ledger entry.
    """
    cur = conn.cursor()
    if clock is not None:
        now_iso = clock.now_iso()
    elif as_of is not None:
        now_iso = as_of
    else:
        cur.execute("SELECT MAX(occurred_at) FROM situations;")
        max_row = cur.fetchone()
        if max_row and max_row[0]:
            now_iso = str(max_row[0])
        else:
            now_iso = Clock(mode=ClockMode.REPLAY).now_iso()
    run_id = f"exam-{uuid.uuid4().hex[:12]}"
    pack_name = class_key.split("|")[0]
    ops = _get_pack_operators(pack_name)

    # 1. Stratified sampling of base situations with known outcomes
    cur.execute(
        """
        SELECT s.id, s.raw_item_id, s.pack, s.family, s.occurred_at, s.sender_key,
               s.content_hash, s.redacted_text, s.hands_off_reason, s.variant,
               r.payload_json AS raw_payload_json
        FROM situations s
        JOIN outcomes o ON s.id = o.situation_id
        LEFT JOIN raw_items r ON s.raw_item_id = r.id
        WHERE s.occurred_at <= ?
        ORDER BY s.occurred_at ASC;
        """,
        (now_iso,),
    )
    all_situations = cur.fetchall()

    # Stratify by month (YYYY-MM)
    by_month: dict[str, list[Any]] = {}
    for row in all_situations:
        m = str(row["occurred_at"])[:7]
        by_month.setdefault(m, []).append(row)

    rng = random.Random(seed)
    sampled_rows: list[Any] = []
    months = sorted(by_month.keys())
    while len(sampled_rows) < settings.exam_n and any(by_month.values()):
        for m in months:
            if by_month[m]:
                idx = rng.randrange(len(by_month[m]))
                sampled_rows.append(by_month[m].pop(idx))
                if len(sampled_rows) >= settings.exam_n:
                    break

    loss = get_action_loss(action)
    recallable = is_recallable(action)
    cap = BASE_ACTION_CAPS.get(action.upper(), 3)

    # 2. Filter base cases where gate decision at level_tested is action-taking (rank >= 2)
    valid_bases: list[dict[str, Any]] = []
    for r in sampled_rows:
        sit_id = str(r["id"])
        sit_text = str(r["redacted_text"] or "")
        audit_draw = compute_audit_draw(sit_id, seed=settings.audit_seed)

        # Baseline gate prediction
        base_p = 0.99
        if policy is not None and hasattr(policy, "predict"):
            _, base_p, _, _ = policy.predict({"text": sit_text})

        base_gate_res = decide_gate(
            action=action,
            p=base_p,
            novel=False,
            licence_level=level_tested,
            cap=cap,
            hands_off=r["hands_off_reason"],
            reader_required=False,
            reader_ok=True,
            deterministic_ok=True,
            loss=loss,
            attention_cost=1.0,
            recallable=recallable,
            audit_draw=audit_draw,
            audit_fraction=settings.audit_fraction,
            budget_ok=True,
        )

        base_rank = autonomy_rank(base_gate_res.decision)
        if base_rank >= 2:
            valid_bases.append(
                {
                    "row": r,
                    "situation_id": sit_id,
                    "text": sit_text,
                    "gate": base_gate_res.decision.value,
                    "action": action,
                    "audit_draw": audit_draw,
                }
            )

    # Check minimum valid base cases
    if len(valid_bases) < settings.exam_min_valid_cases:
        details = {
            "reason": "insufficient_cases",
            "valid_cases": len(valid_bases),
            "min_required": settings.exam_min_valid_cases,
            "total_sampled": len(sampled_rows),
        }
        cur.execute(
            """
            INSERT INTO exam_runs
            (id, class_key, action, level_tested, started_at, finished_at, n_cases,
             invariance_flip_rate, directional_violations_critical, directional_violation_rate_other,
             passed, edit_model_id, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, 0, ?, ?);
            """,
            (
                run_id,
                class_key,
                action,
                level_tested,
                now_iso,
                now_iso,
                len(valid_bases),
                model_id or settings.model_exam_edits,
                canonical_json(details),
            ),
        )

        append_ledger(
            conn,
            kind=LedgerKind.EXAM_RUN,
            ref_id=run_id,
            payload={
                "exam_run_id": run_id,
                "class_key": class_key,
                "action": action,
                "level_tested": level_tested,
                "passed": False,
                "n_cases": len(valid_bases),
                "reason": "insufficient_cases",
                "finished_at": now_iso,
            },
            created_at=now_iso,
        )
        conn.commit()

        return ExamRunResult(
            run_id=run_id,
            class_key=class_key,
            action=action,
            level_tested=level_tested,
            passed=False,
            n_cases=len(valid_bases),
            invariance_flip_rate=None,
            critical_violations=0,
            other_violation_rate=None,
            details=details,
        )

    # 3 & 4. Apply operators and evaluate whole pipeline on perturbed edits
    case_records: list[dict[str, Any]] = []
    discarded_edits = 0

    for base in valid_bases:
        row = base["row"]
        sit_id = base["situation_id"]
        base_text = base["text"]
        base_act = base["action"]
        base_gate = base["gate"]
        audit_draw = base["audit_draw"]

        raw_payload: dict[str, Any] = {}
        if row["raw_payload_json"]:
            try:
                raw_payload = json.loads(row["raw_payload_json"])
            except Exception:
                raw_payload = {}

        for op in ops:
            case_id = f"case-{uuid.uuid4().hex[:12]}"
            mut_text = base_text
            mut_payload = dict(raw_payload)
            edit_valid = True

            # Apply perturbation & run validator
            if pack_name in ("mail", "email"):
                mut_text, mut_payload = apply_mail_operator(
                    op.name,
                    base_text,
                    raw_payload,
                    llm_client=llm_client,
                    model=model_id,
                )
                edit_valid = validate_mail_operator_result(
                    op.name,
                    base_text,
                    mut_text,
                    original_payload=raw_payload,
                    mutated_payload=mut_payload,
                )
            elif pack_name in ("cal", "calendar"):
                mut_payload = apply_calendar_operator(
                    op.name,
                    raw_payload,
                    llm_client=llm_client,
                    model=model_id,
                )
                edit_valid = validate_calendar_operator_result(op.name, raw_payload, mut_payload)
                mut_text = str(mut_payload.get("description") or mut_payload.get("title") or "")
            elif pack_name in ("file", "files"):
                mut_payload = apply_files_code_operator(op.name, raw_payload)
                edit_valid = validate_files_operator_result(op.name, raw_payload, mut_payload)
                mut_text = str(mut_payload.get("name") or "")

            if not edit_valid:
                discarded_edits += 1
                continue

            # Run pipeline on perturbed case: redaction -> policy -> gate
            redacted_mut, _, _ = redact_text(mut_text)

            pert_act = base_act
            pert_p = 0.99
            pert_novel = False
            hands_off = row["hands_off_reason"]

            # Hands-off checks for executable files
            if pack_name in ("file", "files") and op.name in (
                "executable_extension",
                "double_extension",
            ):
                hands_off = "executable_extension"

            if policy is not None and hasattr(policy, "predict"):
                pert_features: dict[str, Any] = {
                    "text": redacted_mut,
                    **mut_payload,
                }
                pert_act, pert_p, _, _ = policy.predict(pert_features)

            pert_gate_res = decide_gate(
                action=pert_act,
                p=pert_p,
                novel=pert_novel,
                licence_level=level_tested,
                cap=cap,
                hands_off=hands_off,
                reader_required=False,
                reader_ok=True,
                deterministic_ok=True,
                loss=loss,
                attention_cost=1.0,
                recallable=recallable,
                audit_draw=audit_draw,
                audit_fraction=settings.audit_fraction,
                budget_ok=True,
            )
            pert_gate = pert_gate_res.decision.value

            # Determine violation
            violated = False
            if op.expectation == "invariant":
                violated = (pert_act != base_act) or (pert_gate != base_gate)
            elif op.expectation == "no_more_autonomous":
                violated = autonomy_rank(pert_gate) > autonomy_rank(base_gate)

            case_records.append(
                {
                    "id": case_id,
                    "situation_id": sit_id,
                    "operator": op.name,
                    "expectation": op.expectation,
                    "edit_valid": 1,
                    "decision_before": f"{base_act}|{base_gate}",
                    "decision_after": f"{pert_act}|{pert_gate}",
                    "violated": 1 if violated else 0,
                    "critical": 1 if op.critical else 0,
                }
            )

    # 5. Evaluate pass/fail mark
    eval_stats = evaluate_exam_run(
        class_key=class_key,
        action=action,
        level_tested=level_tested,
        cases=case_records,
    )

    passed_int = 1 if eval_stats["passed"] else 0
    details = {
        **eval_stats,
        "discarded_invalid_edits": discarded_edits,
        "valid_base_cases": len(valid_bases),
    }

    # 6. Database and Ledger persistence
    cur.execute(
        """
        INSERT INTO exam_runs
        (id, class_key, action, level_tested, started_at, finished_at, n_cases,
         invariance_flip_rate, directional_violations_critical, directional_violation_rate_other,
         passed, edit_model_id, details_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            run_id,
            class_key,
            action,
            level_tested,
            now_iso,
            now_iso,
            len(case_records),
            eval_stats["invariance_flip_rate"],
            eval_stats["critical_violations"],
            eval_stats["other_violation_rate"],
            passed_int,
            model_id or settings.model_exam_edits,
            canonical_json(details),
        ),
    )

    for c in case_records:
        cur.execute(
            """
            INSERT INTO exam_cases
            (id, exam_run_id, base_situation_id, operator, expectation, edit_valid,
             decision_before, decision_after, violated, critical)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                c["id"],
                run_id,
                c["situation_id"],
                c["operator"],
                c["expectation"],
                c["edit_valid"],
                c["decision_before"],
                c["decision_after"],
                c["violated"],
                c["critical"],
            ),
        )

    append_ledger(
        conn,
        kind=LedgerKind.EXAM_RUN,
        ref_id=run_id,
        payload={
            "exam_run_id": run_id,
            "class_key": class_key,
            "action": action,
            "level_tested": level_tested,
            "passed": eval_stats["passed"],
            "n_cases": len(case_records),
            "invariance_flip_rate": eval_stats["invariance_flip_rate"],
            "critical_violations": eval_stats["critical_violations"],
            "finished_at": now_iso,
        },
        created_at=now_iso,
    )
    conn.commit()

    return ExamRunResult(
        run_id=run_id,
        class_key=class_key,
        action=action,
        level_tested=level_tested,
        passed=bool(eval_stats["passed"]),
        n_cases=len(case_records),
        invariance_flip_rate=eval_stats["invariance_flip_rate"],
        critical_violations=eval_stats["critical_violations"],
        other_violation_rate=eval_stats["other_violation_rate"],
        details=details,
    )
