"""Exam results and examiner-owned atomic persistence (no model or transport I/O)."""

import json
from dataclasses import dataclass, field
from typing import Any

from probation.core.hashing import canonical_json
from probation.db.access import Role, RoleAccess


@dataclass(frozen=True, slots=True)
class ExamRunResult:
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


def load_exam(access: RoleAccess, run_id: str) -> ExamRunResult | None:
    row = access.conn.execute("SELECT * FROM exam_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        return None
    return ExamRunResult(
        run_id=row["id"],
        class_key=row["class_key"],
        action=row["action"],
        level_tested=row["level_tested"],
        passed=bool(row["passed"]),
        n_cases=row["n_cases"],
        invariance_flip_rate=row["invariance_flip_rate"],
        critical_violations=row["directional_violations_critical"],
        other_violation_rate=row["directional_violation_rate_other"],
        details=json.loads(row["details_json"]),
    )


def persist_exam(
    access: RoleAccess,
    result: ExamRunResult,
    *,
    now_iso: str,
    model_id: str,
    cases: list[dict[str, Any]],
) -> ExamRunResult:
    if access.role != Role.EXAMINER:
        raise ValueError("Exam storage requires the examiner role")
    with access.transaction():
        existing = load_exam(access, result.run_id)
        if existing is not None:
            if existing != result:
                raise ValueError("An exam retry cannot change an existing result")
            return existing
        access.execute_write(
            "exam_runs",
            """INSERT INTO exam_runs
            (id, class_key, action, level_tested, started_at, finished_at, n_cases,
             invariance_flip_rate, directional_violations_critical, directional_violation_rate_other,
             passed, edit_model_id, details_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result.run_id,
                result.class_key,
                result.action,
                result.level_tested,
                now_iso,
                now_iso,
                result.n_cases,
                result.invariance_flip_rate,
                result.critical_violations,
                result.other_violation_rate,
                int(result.passed),
                model_id,
                canonical_json(result.details),
            ),
        )
        for case in cases:
            access.execute_write(
                "exam_cases",
                """INSERT INTO exam_cases
                (id,exam_run_id,base_situation_id,operator,expectation,edit_valid,
                 decision_before,decision_after,violated,critical) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    case["id"],
                    result.run_id,
                    case["situation_id"],
                    case["operator"],
                    case["expectation"],
                    case["edit_valid"],
                    case["decision_before"],
                    case["decision_after"],
                    case["violated"],
                    case["critical"],
                ),
            )
        access.append_ledger(
            "exam_run",
            result.run_id,
            {
                "exam_run_id": result.run_id,
                "class_key": result.class_key,
                "action": result.action,
                "level_tested": result.level_tested,
                "passed": result.passed,
                "n_cases": result.n_cases,
                "invariance_flip_rate": result.invariance_flip_rate,
                "critical_violations": result.critical_violations,
                "finished_at": now_iso,
            },
            now_iso,
        )
    return result
