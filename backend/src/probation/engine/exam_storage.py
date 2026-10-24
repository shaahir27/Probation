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
        pending = access.conn.execute(
            "SELECT finished_at FROM exam_runs WHERE id=?", (result.run_id,)
        ).fetchone()
        if existing is not None and pending is not None and pending[0] is not None:
            if existing != result:
                raise ValueError("An exam retry cannot change an existing result")
            return existing
        values = (
            now_iso,
            result.n_cases,
            result.invariance_flip_rate,
            result.critical_violations,
            result.other_violation_rate,
            int(result.passed),
            model_id,
            canonical_json(result.details),
        )
        if pending is not None:
            access.execute_write(
                "exam_runs",
                """UPDATE exam_runs SET finished_at=?,n_cases=?,
                invariance_flip_rate=?,directional_violations_critical=?,directional_violation_rate_other=?,
                passed=?,edit_model_id=?,details_json=? WHERE id=? AND finished_at IS NULL""",
                (*values, result.run_id),
            )
        else:
            access.execute_write(
                "exam_runs",
                """INSERT INTO exam_runs
                (id,class_key,action,level_tested,started_at,finished_at,n_cases,invariance_flip_rate,
                 directional_violations_critical,directional_violation_rate_other,passed,edit_model_id,details_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    result.run_id,
                    result.class_key,
                    result.action,
                    result.level_tested,
                    now_iso,
                    *values,
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


def claim_exam(
    access: RoleAccess,
    run_id: str,
    class_key: str,
    action: str,
    level: int,
    now_iso: str,
    details: dict[str, Any],
    *,
    scheduled: bool,
) -> bool:
    """Persist attempt before inference. An interrupted attempt is not auto-reclaimed."""
    from probation.config import settings
    from probation.core.clock import format_timestamp, parse_timestamp

    if access.role != Role.EXAMINER:
        raise ValueError("Exam claim requires Examiner")
    with access.transaction():
        if access.conn.execute("SELECT id FROM exam_runs WHERE id=?", (run_id,)).fetchone():
            return False
        if scheduled:
            start = parse_timestamp(now_iso).replace(hour=0, minute=0, second=0, microsecond=0)
            used_row = access.conn.execute(
                """SELECT count(*) FROM exam_runs
                WHERE started_at COLLATE UTC_TIMESTAMP >= ? AND started_at COLLATE UTC_TIMESTAMP <= ?""",
                (format_timestamp(start), now_iso),
            ).fetchone()
            if used_row is None:
                return False
            used = int(used_row[0])
            if used >= settings.exam_max_per_day:
                return False
        access.execute_write(
            "exam_runs",
            """INSERT INTO exam_runs
            (id,class_key,action,level_tested,started_at,n_cases,details_json)
            VALUES (?,?,?,?,?,0,?)""",
            (
                run_id,
                class_key,
                action,
                level,
                now_iso,
                canonical_json({**details, "reason": "unfinished_exam"}),
            ),
        )
        return True
