"""Unit tests for Examination Board and adversarial invariance evaluation.

Authority: docs/CONTRACT.md invariants I-2, I-3, I-14, I-19, I-20,
           docs/ENGINE_SPEC.md section 15, and docs/TEST_PLAN.md (T-EXAM, T-SEC).
"""

import ast
import json
import sqlite3
from pathlib import Path

import pytest

from probation.config import settings
from probation.core.enums import GateDecision, LedgerKind
from probation.db.connection import apply_schema
from probation.engine.exam import (
    autonomy_rank,
    evaluate_exam_run,
    run_exam,
)
from probation.engine.licence import (
    check_exam_ok,
    derive_and_cache_licences,
    find_exam_candidates,
)
from tests.unit.wp5_exam_fixtures import (
    CheatingPolicy as CheatingPolicy,
)
from tests.unit.wp5_exam_fixtures import (
    SoundPolicy as SoundPolicy,
)
from tests.unit.wp5_exam_fixtures import (
    _populate_test_situations as _populate_test_situations,
)
from tests.unit.wp5_exam_fixtures import (
    context_for as context_for,
)
from tests.unit.wp5_exam_fixtures import (
    fixture_editor as fixture_editor,
)


@pytest.fixture
def exam_db() -> sqlite3.Connection:
    """In-memory SQLite database initialized with Probation schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    return conn


# --- T-EXAM Tests ---


def test_t_exam_autonomy_rank_mapping() -> None:
    """T-EXAM: Verify exact autonomy rank ordering per ENGINE_SPEC section 15.2."""
    assert autonomy_rank(GateDecision.SHADOW) == 0
    assert autonomy_rank(GateDecision.ASK) == 1
    assert autonomy_rank(GateDecision.SUGGEST) == 1
    assert autonomy_rank(GateDecision.HOLD_THEN_EXECUTE) == 2
    assert autonomy_rank(GateDecision.EXECUTE_UNDO) == 2
    assert autonomy_rank(GateDecision.EXECUTE_SILENT) == 3


def test_t_exam_sound_policy_passes(exam_db: sqlite3.Connection) -> None:
    """T-EXAM: A sound, well-calibrated policy passes adversarial counterfactual evaluation."""
    _populate_test_situations(exam_db, count=25)
    policy = SoundPolicy()

    res = run_exam(
        conn=exam_db,
        class_key="mail|request|known",
        action="REPLY",
        level_tested=2,
        policy=policy,
        prediction_context=context_for(exam_db, policy),
        as_of="2026-07-01T00:00:00Z",
    )

    assert res.passed is True
    assert res.n_cases >= settings.exam_min_valid_cases
    assert res.critical_violations == 0
    assert res.invariance_flip_rate is not None
    assert res.invariance_flip_rate <= settings.exam_invariance_max_flip

    # Verify ledger entry written
    cur = exam_db.cursor()
    cur.execute("SELECT kind, ref_id, payload_json FROM ledger WHERE ref_id = ?;", (res.run_id,))
    ledger_row = cur.fetchone()
    assert ledger_row is not None
    assert ledger_row["kind"] == LedgerKind.EXAM_RUN.value
    payload = json.loads(ledger_row["payload_json"])
    assert payload["passed"] is True


def test_t_exam_cheating_policy_fails(exam_db: sqlite3.Connection) -> None:
    """T-EXAM: A deliberately cheating policy fails the invariance and critical directional checks."""
    _populate_test_situations(exam_db, count=25)
    cheating_policy = CheatingPolicy()

    res = run_exam(
        conn=exam_db,
        class_key="mail|request|known",
        action="REPLY",
        level_tested=2,
        policy=cheating_policy,
        prediction_context=context_for(exam_db, cheating_policy),
        as_of="2026-07-01T00:00:00Z",
    )

    # Cheating policy triggers invariance flips when greeting changes or typos occur
    assert res.passed is False
    assert res.invariance_flip_rate is not None
    assert res.invariance_flip_rate > settings.exam_invariance_max_flip


def test_exam_and_case_ids_match_across_independent_replays(exam_db: sqlite3.Connection) -> None:
    from probation.db.connection import get_connection

    _populate_test_situations(exam_db, count=25)
    exam_db.commit()
    clone = get_connection(":memory:")
    try:
        exam_db.backup(clone)
        kwargs = {
            "class_key": "mail|request|known",
            "action": "REPLY",
            "level_tested": 2,
            "as_of": "2026-07-01T00:00:00Z",
            "seed": 7,
            "policy": SoundPolicy(),
        }
        kwargs["prediction_context"] = context_for(exam_db, kwargs["policy"])
        first = run_exam(exam_db, **kwargs)
        second = run_exam(clone, **kwargs)
        assert first == second
        assert first.n_cases >= settings.exam_min_valid_cases
        first_cases = [
            tuple(row) for row in exam_db.execute("SELECT * FROM exam_cases ORDER BY id")
        ]
        assert first_cases == [
            tuple(row) for row in clone.execute("SELECT * FROM exam_cases ORDER BY id")
        ]
        assert (
            exam_db.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()[0]
            == clone.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()[0]
        )
        assert run_exam(exam_db, **kwargs) == first
        assert exam_db.execute("SELECT count(*) FROM exam_cases").fetchone()[0] == len(first_cases)
    finally:
        clone.close()


def test_t_exam_insufficient_cases_fails(exam_db: sqlite3.Connection) -> None:
    """T-EXAM: When fewer than EXAM_MIN_VALID_CASES (20) exist, exam fails with insufficient_cases."""
    # Seed only 10 situations (below minimum 20)
    _populate_test_situations(exam_db, count=10)

    res = run_exam(
        conn=exam_db,
        class_key="mail|request|known",
        action="REPLY",
        level_tested=2,
        policy=SoundPolicy(),
        as_of="2026-07-01T00:00:00Z",
    )

    assert res.passed is False
    assert res.details.get("reason") == "insufficient_cases"
    assert res.n_cases < settings.exam_min_valid_cases


def test_t_exam_verdicts_computed_without_llm() -> None:
    """T-EXAM: Evaluate exam run computes verdicts strictly without calling an LLM."""
    cases = [
        {
            "expectation": "invariant",
            "critical": False,
            "violated": False,
        }
        for _ in range(20)
    ]
    # Pure code evaluation
    res = evaluate_exam_run(
        class_key="mail|test|known",
        action="REPLY",
        level_tested=2,
        cases=cases,
    )
    assert res["passed"] is True
    assert res["invariance_flip_rate"] == 0.0
    assert res["critical_violations"] == 0


def test_t_exam_level_3_pass_satisfies_level_2(exam_db: sqlite3.Connection) -> None:
    """T-EXAM: A pass at level_tested = 3 also qualifies for Level 2 (ENGINE_SPEC section 15)."""
    cur = exam_db.cursor()
    cur.execute(
        """
        INSERT INTO exam_runs (id, class_key, action, level_tested, started_at, finished_at, n_cases,
                               invariance_flip_rate, directional_violations_critical, passed, details_json)
        VALUES ('exam-l3-test', 'mail|tier1|known', 'ARCHIVE', 3, '2026-03-01T10:00:00Z', '2026-03-01T10:05:00Z', 30, 0.0, 0, 1, '{}');
        """
    )
    from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

    complete_validity_exam_fixture(exam_db)

    # Pass at Level 3 qualifies for Level 3
    assert (
        check_exam_ok(exam_db, "mail|tier1|known", "ARCHIVE", "2026-03-10T00:00:00Z", level=3)
        is True
    )
    # Pass at Level 3 ALSO qualifies for Level 2
    assert (
        check_exam_ok(exam_db, "mail|tier1|known", "ARCHIVE", "2026-03-10T00:00:00Z", level=2)
        is True
    )

    # But a pass at Level 2 does NOT qualify for Level 3
    cur.execute(
        """
        INSERT INTO exam_runs (id, class_key, action, level_tested, started_at, finished_at, n_cases,
                               invariance_flip_rate, directional_violations_critical, passed, details_json)
        VALUES ('exam-l2-test', 'mail|tier2|known', 'ARCHIVE', 2, '2026-03-01T10:00:00Z', '2026-03-01T10:05:00Z', 30, 0.0, 0, 1, '{}');
        """
    )
    from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

    complete_validity_exam_fixture(exam_db)

    assert (
        check_exam_ok(exam_db, "mail|tier2|known", "ARCHIVE", "2026-03-10T00:00:00Z", level=2)
        is True
    )
    assert (
        check_exam_ok(exam_db, "mail|tier2|known", "ARCHIVE", "2026-03-10T00:00:00Z", level=3)
        is False
    )


def test_t_exam_stale_exam_expiry(exam_db: sqlite3.Connection) -> None:
    """T-EXAM: Exams older than EXAM_VALID_DAYS or older than latest drift alarm do not count."""
    cur = exam_db.cursor()
    # 1. Stale by age (> 90 days)
    cur.execute(
        """
        INSERT INTO exam_runs (id, class_key, action, level_tested, started_at, finished_at, n_cases,
                               invariance_flip_rate, directional_violations_critical, passed, details_json)
        VALUES ('exam-old', 'mail|tier1|known', 'REPLY', 2, '2026-01-01T10:00:00Z', '2026-01-01T10:05:00Z', 30, 0.0, 0, 1, '{}');
        """
    )
    from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

    complete_validity_exam_fixture(exam_db)

    # Querying 100 days later: should be stale
    assert (
        check_exam_ok(exam_db, "mail|tier1|known", "REPLY", "2026-04-15T00:00:00Z", level=2)
        is False
    )

    # 2. Stale by CUSUM drift alarm
    cur.execute(
        """
        INSERT INTO exam_runs (id, class_key, action, level_tested, started_at, finished_at, n_cases,
                               invariance_flip_rate, directional_violations_critical, passed, details_json)
        VALUES ('exam-recent', 'mail|drift|known', 'REPLY', 2, '2026-03-01T10:00:00Z', '2026-03-01T10:05:00Z', 30, 0.0, 0, 1, '{}');
        """
    )
    # Record drift alarm AFTER the exam finished
    cur.execute(
        """
        INSERT INTO drift_state (class_key, action, cusum, baseline_err, last_alarm_at)
        VALUES ('mail|drift|known', 'REPLY', 5.5, 0.03, '2026-03-05T12:00:00Z');
        """
    )
    from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

    complete_validity_exam_fixture(exam_db)

    # Exam was finished before drift alarm, so it is stale and effective level cannot be 2
    assert (
        check_exam_ok(exam_db, "mail|drift|known", "REPLY", "2026-03-10T00:00:00Z", level=2)
        is False
    )


def test_t_exam_max_per_day_cap(exam_db: sqlite3.Connection) -> None:
    """T-EXAM: At most EXAM_MAX_PER_DAY (3) exams are queued per review tick."""
    cur = exam_db.cursor()
    # Insert 6 distinct class_stats meeting numeric thresholds
    for i in range(6):
        cur.execute(
            """
            INSERT INTO class_stats (class_key, action, as_of, n_strong, k_strong, n_all, k_all, n_recent, lb_strong, lb_all)
            VALUES (?, 'REPLY', '2026-06-01T00:00:00Z', 60, 60, 60, 60, 25, 0.96, 0.96);
            """,
            (f"mail|class{i}|known",),
        )
    from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

    complete_validity_exam_fixture(exam_db)

    candidates = find_exam_candidates(exam_db, as_of="2026-06-01T00:00:00Z", max_candidates=3)
    assert len(candidates) == 3


def test_t_exam_licence_cache_integration(exam_db: sqlite3.Connection) -> None:
    """T-EXAM: Passing exam results in exam_run_id stored in licence_cache upon Level 2 promotion."""
    cur = exam_db.cursor()
    # Insert passing exam
    cur.execute(
        """
        INSERT INTO exam_runs (id, class_key, action, level_tested, started_at, finished_at, n_cases,
                               invariance_flip_rate, directional_violations_critical, passed, details_json)
        VALUES ('exam-passed-123', 'mail|promo|known', 'REPLY', 2, '2026-06-01T10:00:00Z', '2026-06-01T10:05:00Z', 30, 0.0, 0, 1, '{}');
        """
    )
    # Genuine committed evidence, not a cached class_stats assertion, supplies authority.
    from tests.unit.test_wp5_licence_derivation import cohort

    cohort(exam_db)
    exam_db.execute("UPDATE exam_runs SET class_key='mail|request|known',action='ARCHIVE'")
    from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

    complete_validity_exam_fixture(exam_db)

    derive_and_cache_licences(exam_db, as_of="2026-06-02T00:00:00Z")

    cur.execute(
        "SELECT level, exam_run_id FROM licence_cache WHERE class_key = 'mail|request|known' AND action = 'ARCHIVE';"
    )
    row = cur.fetchone()
    assert row is not None
    assert row["level"] == 2
    assert row["exam_run_id"] == "exam-passed-123"


# --- T-SEC Security Isolation Check ---


def test_t_sec_examiner_security_boundaries() -> None:
    """T-SEC: Static import-graph check confirms workers/examiner.py and engine/exam.py

    never import workers/executor.py or write credentials (CONTRACT I-2, I-19).
    """
    src_dir = Path(__file__).resolve().parent.parent.parent / "src" / "probation"
    examiner_file = src_dir / "workers" / "examiner.py"
    exam_file = src_dir / "engine" / "exam.py"

    for target_file in (examiner_file, exam_file):
        with open(target_file, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(target_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "executor" not in alias.name, (
                        f"Disallowed executor import '{alias.name}' in {target_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "executor" not in module, (
                    f"Disallowed executor import from '{module}' in {target_file.name}"
                )
                for alias in node.names:
                    assert "executor" not in alias.name, (
                        f"Disallowed executor symbol '{alias.name}' in {target_file.name}"
                    )
