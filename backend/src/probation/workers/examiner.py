"""Examiner worker: Evaluates candidate policies on counterfactual trick-question exams.

Authority: docs/CONTRACT.md section 3, invariant I-2, I-14, I-19, and docs/ENGINE_SPEC.md section 15.
CRITICAL: Must NEVER import executor credentials or execute modules (T-SEC).
"""

import sqlite3
from typing import Any

from probation.config import settings
from probation.core.clock import Clock
from probation.db.access import Role, RoleAccess
from probation.engine.exam import ExamRunResult, run_exam


def run_examiner_job(
    conn: sqlite3.Connection,
    class_key: str,
    action: str,
    level: int = 2,
    as_of: str | None = None,
    seed: int = 42,
    llm_client: Any = None,
    clock: Clock | None = None,
) -> ExamRunResult:
    """Execute a single diagnostic exam run using Role.EXAMINER database boundaries."""
    access_conn = RoleAccess(conn, Role.EXAMINER)
    # verify_write asserts that the examiner role is authorized for exam tables
    access_conn.verify_write("exam_runs")
    access_conn.verify_write("exam_cases")
    access_conn.verify_write("ledger")

    return run_exam(
        conn=conn,
        class_key=class_key,
        action=action,
        level_tested=level,
        as_of=as_of,
        seed=seed,
        llm_client=llm_client,
        clock=clock,
    )


def run_candidate_exams(
    conn: sqlite3.Connection,
    candidates: list[tuple[str, str, int]],
    as_of: str | None = None,
    clock: Clock | None = None,
) -> list[ExamRunResult]:
    """Execute diagnostic exams for a list of (class_key, action, target_level) candidates.

    Capped by EXAM_MAX_PER_DAY.
    """
    results: list[ExamRunResult] = []
    max_exams = settings.exam_max_per_day

    for class_key, action, target_level in candidates[:max_exams]:
        res = run_examiner_job(
            conn=conn,
            class_key=class_key,
            action=action,
            level=target_level,
            as_of=as_of,
            clock=clock,
        )
        results.append(res)

    return results
