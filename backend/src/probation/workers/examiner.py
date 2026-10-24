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
from probation.engine.exam_prediction import ExamPredictionContext


def run_examiner_job(
    conn: sqlite3.Connection,
    class_key: str,
    action: str,
    level: int = 2,
    as_of: str | None = None,
    seed: int = 42,
    llm_client: Any = None,
    clock: Clock | None = None,
    attempt_ordinal: int = 0,
    prediction_context: ExamPredictionContext | None = None,
    scheduled: bool = False,
) -> ExamRunResult:
    """Execute a single diagnostic exam run using Role.EXAMINER database boundaries."""
    access_conn = RoleAccess(conn, Role.EXAMINER)
    # verify_write asserts that the examiner role is authorized for exam tables
    access_conn.verify_write("exam_runs")
    access_conn.verify_write("exam_cases")
    access_conn.verify_write("ledger")

    if prediction_context is None:
        from probation.core.clock import get_clock
        from probation.engine.exam_context import build_exam_context
        from probation.engine.novelty import NoveltyUnavailable
        from probation.llm.consumers import RegisteredConsumer

        try:
            prediction_context = build_exam_context(
                conn,
                class_key,
                as_of or (clock or get_clock()).now_iso(),
                consumer=llm_client if isinstance(llm_client, RegisteredConsumer) else None,
            )
        except (NoveltyUnavailable, ValueError):
            prediction_context = None
    return run_exam(
        conn=conn,
        class_key=class_key,
        action=action,
        level_tested=level,
        as_of=as_of,
        seed=seed,
        llm_client=llm_client,
        clock=clock,
        attempt_ordinal=attempt_ordinal,
        prediction_context=prediction_context,
        scheduled=scheduled,
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
            scheduled=True,
        )
        results.append(res)

    return results
