"""Persisted review limits and insufficient-case suppression across worker restart."""

from probation.config import settings
from probation.engine.exam import run_exam
from probation.engine.licence import find_exam_candidates


def numeric_candidate(conn, ck="mail|request|known"):
    conn.execute(
        """INSERT INTO class_stats VALUES (?,'REPLY','2026-07-01T00:00:00Z',
        70,70,70,70,30,.96,.96)""",
        (ck,),
    )


def test_repeated_review_cannot_reset_daily_quota(memory_db, monkeypatch):
    monkeypatch.setattr(settings, "exam_max_per_day", 1)
    numeric_candidate(memory_db)
    run_exam(memory_db, "mail|other|known", "REPLY", as_of="2026-07-01T00:00:00Z")
    assert find_exam_candidates(memory_db, "2026-07-01T00:00:00Z") == []


def test_unchanged_insufficient_candidate_is_not_retried_on_next_day(memory_db):
    numeric_candidate(memory_db)
    run_exam(memory_db, "mail|request|known", "REPLY", as_of="2026-07-01T00:00:00Z")
    memory_db.execute("UPDATE class_stats SET as_of='2026-07-02T00:00:00Z'")
    assert find_exam_candidates(memory_db, "2026-07-02T00:00:00Z") == []


def test_zero_candidate_limit_is_zero(memory_db):
    numeric_candidate(memory_db)
    assert find_exam_candidates(memory_db, "2026-07-01T00:00:00Z", max_candidates=0) == []


def test_unavailable_or_hard_capped_pack_is_not_queued(memory_db):
    for ck in ["chain|mail|REPLY", "reading|career|article", "alien|x|y"]:
        numeric_candidate(memory_db, ck)
    assert find_exam_candidates(memory_db, "2026-07-01T00:00:00Z") == []


def test_an_interrupted_attempt_remains_counted_and_unavailable(memory_db, monkeypatch):
    from probation.db.access import Role, RoleAccess
    from probation.engine.exam_storage import claim_exam, load_exam

    monkeypatch.setattr(settings, "exam_max_per_day", 1)
    access = RoleAccess(memory_db, Role.EXAMINER)
    assert claim_exam(
        access,
        "interrupted",
        "mail|request|known",
        "REPLY",
        2,
        "2026-07-01T00:00:00Z",
        {},
        scheduled=True,
    )
    assert not claim_exam(
        access, "second", "mail|other|known", "REPLY", 2, "2026-07-01T00:00:00Z", {}, scheduled=True
    )
    row = memory_db.execute("SELECT finished_at,passed FROM exam_runs").fetchone()
    assert tuple(row) == (None, None)
    assert load_exam(access, "interrupted").details["reason"] == "unfinished_exam"
