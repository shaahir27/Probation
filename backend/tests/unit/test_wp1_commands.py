"""Approved CCR-F: durable intent and Examiner-owned administration."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from probation.core.clock import Clock
from probation.db.access import AccessError, Role, RoleAccess
from probation.db.commands import DenyHabit, RunExam, enqueue_command
from probation.db.connection import get_connection, get_role_connection, init_db
from probation.workers.admin import process_admin_commands


def seed_habit(conn: sqlite3.Connection) -> None:
    conn.execute("""INSERT INTO habits VALUES ('h','email_action','sender_tier','known','ARCHIVE',
                 30,30,2,0.001,'synthetic','[]','active','2026-01-01T00:00:00Z')""")
    conn.commit()


def test_command_retry_and_worker_preserve_ownership(memory_db: sqlite3.Connection) -> None:
    seed_habit(memory_db)
    api = RoleAccess(memory_db, Role.API)
    first = enqueue_command(api, DenyHabit(habit_id="h"), "2026-02-01T00:00:00Z")
    second = enqueue_command(api, DenyHabit(habit_id="h"), "2026-02-02T00:00:00Z")
    assert first == second
    assert first["status"] == "PENDING"
    assert memory_db.execute("SELECT status FROM habits").fetchone()[0] == "active"
    memory_db.commit()
    clock = Clock.replay(datetime(2026, 2, 2, tzinfo=UTC))
    assert process_admin_commands(memory_db, clock=clock) == [first["id"]]
    assert process_admin_commands(memory_db, clock=clock) == []
    assert memory_db.execute("SELECT status FROM habits").fetchone()[0] == "denied"
    assert memory_db.execute("SELECT status FROM admin_commands").fetchone()[0] == "SUCCEEDED"


def test_enqueue_cannot_commit_parent(memory_db: sqlite3.Connection) -> None:
    seed_habit(memory_db)
    with pytest.raises(RuntimeError), memory_db:
        memory_db.execute("INSERT INTO meta VALUES ('parent','synthetic')")
        enqueue_command(
            RoleAccess(memory_db, Role.API), DenyHabit(habit_id="h"), "2026-02-01T00:00:00Z"
        )
        raise RuntimeError("caller failed")
    assert memory_db.execute("SELECT count(*) FROM admin_commands").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM meta WHERE key='parent'").fetchone()[0] == 0


def test_role_connections_enforce_command_operation_permissions(tmp_path: Path) -> None:
    path = tmp_path / "roles.db"
    init_db(path)
    with get_connection(path) as setup:
        seed_habit(setup)
    with get_role_connection(path, Role.API) as api:
        enqueue_command(RoleAccess(api, Role.API), DenyHabit(habit_id="h"), "2026-02-01T00:00:00Z")
        api.commit()
        for sql in [
            "UPDATE habits SET status='denied'",
            "UPDATE admin_commands SET status='SUCCEEDED'",
            "DELETE FROM admin_commands",
        ]:
            with pytest.raises(sqlite3.DatabaseError):
                api.execute(sql)
        with pytest.raises(AccessError):
            RoleAccess(api, Role.API).execute_write(
                "admin_commands", "UPDATE admin_commands SET status='SUCCEEDED'"
            )
    with get_role_connection(path, Role.EXAMINER) as examiner:
        with pytest.raises(AccessError):
            enqueue_command(
                RoleAccess(examiner, Role.EXAMINER), DenyHabit(habit_id="h"), "2026-02-01T00:00:00Z"
            )
        assert (
            len(
                process_admin_commands(
                    examiner, clock=Clock.replay(datetime(2026, 2, 2, tzinfo=UTC))
                )
            )
            == 1
        )


@pytest.mark.parametrize(
    "kwargs",
    [{"level": True}, {"level": 1}, {"attempt_ordinal": -1}, {"extra": "x"}, {"action": "UNKNOWN"}],
)
def test_invalid_exam_commands_fail_closed(kwargs: dict[str, object]) -> None:
    values = {"class_key": "mail|known", "action": "ARCHIVE", **kwargs}
    with pytest.raises(ValidationError):
        RunExam.model_validate(values)


def test_explicit_attempt_is_stable_and_distinct() -> None:
    first = RunExam(class_key="mail|known", action="ARCHIVE")
    assert first != first.model_copy(update={"attempt_ordinal": 1})


def test_insert_or_replace_cannot_reset_a_terminal_command(memory_db: sqlite3.Connection) -> None:
    seed_habit(memory_db)
    queued = enqueue_command(
        RoleAccess(memory_db, Role.API), DenyHabit(habit_id="h"), "2026-02-01T00:00:00Z"
    )
    process_admin_commands(memory_db, clock=Clock.replay(datetime(2026, 2, 2, tzinfo=UTC)))
    row = memory_db.execute("SELECT * FROM admin_commands").fetchone()
    with pytest.raises((AccessError, sqlite3.DatabaseError)):
        RoleAccess(memory_db, Role.API).execute_write(
            "admin_commands",
            """INSERT OR REPLACE INTO admin_commands
            (id,kind,payload_json,status,requested_at,updated_at) VALUES (?,?,?,'PENDING',?,?)""",
            (
                queued["id"],
                row["kind"],
                row["payload_json"],
                row["requested_at"],
                row["requested_at"],
            ),
        )
    assert memory_db.execute("SELECT status FROM admin_commands").fetchone()[0] == "SUCCEEDED"


def test_insert_or_replace_cannot_rewrite_existing_ledger(memory_db: sqlite3.Connection) -> None:
    from probation.db.ledger import append_ledger

    append_ledger(memory_db, "proposal", "original", {"action": "ARCHIVE"}, "2026-01-01T00:00:00Z")
    memory_db.commit()
    row = memory_db.execute("SELECT * FROM ledger").fetchone()
    before = tuple(row)
    with pytest.raises((AccessError, sqlite3.DatabaseError)):
        RoleAccess(memory_db, Role.BRAIN).execute_write(
            "ledger",
            """INSERT OR REPLACE INTO ledger
            (seq,kind,ref_id,payload_json,prev_hash,hash,created_at) VALUES (?,?,?,?,?,?,?)""",
            (
                row["seq"],
                row["kind"],
                "replacement",
                row["payload_json"],
                row["prev_hash"],
                row["hash"],
                row["created_at"],
            ),
        )
    assert tuple(memory_db.execute("SELECT * FROM ledger").fetchone()) == before


def test_schema_upgrade_preserves_existing_ledger(memory_db: sqlite3.Connection) -> None:
    from probation.db.ledger import append_ledger, ledger_snapshot
    from probation.db.migrations import migrate_wp1

    memory_db.execute("DROP TABLE admin_commands")
    memory_db.execute("DROP TABLE drift_receipts")
    append_ledger(memory_db, "proposal", "synthetic", {"action": "ARCHIVE"}, "2026-01-01T00:00:00Z")
    memory_db.commit()
    before = ledger_snapshot(memory_db)
    migrate_wp1(memory_db)
    migrate_wp1(memory_db)
    assert ledger_snapshot(memory_db) == before


def test_concurrent_retries_enqueue_one_intent(tmp_path: Path) -> None:
    path = tmp_path / "concurrent-commands.db"
    init_db(path)
    with get_connection(path) as setup:
        seed_habit(setup)
    barrier = Barrier(2)

    def enqueue() -> str:
        with get_role_connection(path, Role.API) as api:
            barrier.wait(timeout=10)
            return str(
                enqueue_command(
                    RoleAccess(api, Role.API), DenyHabit(habit_id="h"), "2026-02-01T00:00:00Z"
                )["id"]
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: enqueue(), range(2)))
    assert ids[0] == ids[1]
    with get_connection(path) as observer:
        assert observer.execute("SELECT count(*) FROM admin_commands").fetchone()[0] == 1


def test_exam_crash_gap_reuses_the_completed_run(
    memory_db: sqlite3.Connection, basic_situation: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import probation.workers.admin as admin
    from probation.core.enums import GateDecision
    from probation.core.types import Proposal, Situation
    from probation.db.proposals import persist_proposal

    assert isinstance(basic_situation, Situation)
    persist_proposal(
        RoleAccess(memory_db, Role.BRAIN),
        Proposal(
            id="admin-exam-proposal",
            situation_id=basic_situation.id,
            family=basic_situation.family,
            class_key="mail|known",
            action="ARCHIVE",
            p_max=0.99,
            novel=False,
            gate=GateDecision.SHADOW,
            proposed_at=basic_situation.occurred_at,
            policy_version="wp1",
            features_hash="wp1",
        ),
    )
    memory_db.commit()
    queued = enqueue_command(
        RoleAccess(memory_db, Role.API),
        RunExam(class_key="mail|known", action="ARCHIVE"),
        "2026-02-01T00:00:00Z",
    )
    finish = admin._finish

    def crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic crash after exam commit")

    monkeypatch.setattr(admin, "_finish", crash)
    clock = Clock.replay(datetime(2026, 2, 2, tzinfo=UTC))
    with pytest.raises(RuntimeError):
        process_admin_commands(memory_db, clock=clock)
    assert memory_db.execute("SELECT count(*) FROM exam_runs").fetchone()[0] == 1
    assert memory_db.execute("SELECT status FROM admin_commands").fetchone()[0] == "PENDING"
    monkeypatch.setattr(admin, "_finish", finish)
    assert process_admin_commands(memory_db, clock=clock) == [queued["id"]]
    assert memory_db.execute("SELECT count(*) FROM exam_runs").fetchone()[0] == 1
