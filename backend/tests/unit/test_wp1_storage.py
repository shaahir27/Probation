"""WP1: transaction ownership, concurrent appends and actual SQL target enforcement."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from probation.db.access import AccessError, Role, RoleAccess
from probation.db.connection import get_connection, init_db
from probation.db.ledger import append_ledger, verify_ledger
from probation.llm.cache import store_cached_response


def test_ledger_append_does_not_commit_callers_work(memory_db: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), memory_db:
        memory_db.execute("INSERT INTO meta(key, value) VALUES ('atomic', 'synthetic')")
        append_ledger(memory_db, "proposal", "p", {"action": "ARCHIVE"}, "2026-01-01T00:00:00Z")
        raise RuntimeError("synthetic failure after append")
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM meta WHERE key = 'atomic'").fetchone()[0] == 0


def test_cache_write_does_not_commit_callers_work(memory_db: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), memory_db:
        store_cached_response(
            memory_db, "k", "reader", "m", "p", "v1", {"x": 1}, 1, 1, 0, "2026-01-01T00:00:00Z"
        )
        raise RuntimeError("synthetic failure after cache")
    assert memory_db.execute("SELECT count(*) FROM llm_cache").fetchone()[0] == 0


def test_concurrent_appenders_produce_one_chain(tmp_path: Path) -> None:
    target = tmp_path / "concurrent.db"
    init_db(target)
    start = Barrier(4)

    def append_worker(worker: int) -> None:
        conn = get_connection(target)
        try:
            start.wait(timeout=10)
            for i in range(12):
                with conn:
                    append_ledger(
                        conn,
                        "proposal",
                        f"{worker}-{i}",
                        {"worker": worker, "item": i},
                        "2026-01-01T00:00:00Z",
                    )
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(append_worker, range(4)))
    conn = get_connection(target)
    try:
        assert verify_ledger(conn) == (True, None)
        assert [r[0] for r in conn.execute("SELECT seq FROM ledger ORDER BY seq")] == list(
            range(1, 49)
        )
    finally:
        conn.close()


def test_supplied_table_cannot_hide_actual_sql_target(memory_db: sqlite3.Connection) -> None:
    brain = RoleAccess(memory_db, Role.BRAIN)
    with pytest.raises(AccessError):
        brain.execute_write("features", "INSERT INTO meta(key, value) VALUES ('spoofed', 'denied')")
    assert memory_db.execute("SELECT count(*) FROM meta WHERE key = 'spoofed'").fetchone()[0] == 0


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE features",
        "DROP TRIGGER ledger_no_update",
        "PRAGMA foreign_keys=OFF",
        "ATTACH DATABASE ':memory:' AS bypass",
    ],
)
def test_role_cannot_change_schema_or_attach_database(
    memory_db: sqlite3.Connection, sql: str
) -> None:
    with pytest.raises(AccessError):
        RoleAccess(memory_db, Role.BRAIN).execute_write("features", sql)


def test_role_read_view_does_not_expose_a_write_bypass(memory_db: sqlite3.Connection) -> None:
    brain = RoleAccess(memory_db, Role.BRAIN)
    with pytest.raises(AccessError):
        brain.conn.execute("INSERT INTO meta(key, value) VALUES ('bypass', 'denied')")


def test_write_cursor_cannot_expose_a_raw_connection(memory_db: sqlite3.Connection) -> None:
    brain = RoleAccess(memory_db, Role.BRAIN)
    cursor = brain.execute_write(
        "ledger",
        "INSERT INTO ledger(seq, kind, ref_id, payload_json, prev_hash, hash, created_at) "
        "VALUES (1, 'proposal', 'p', '{}', '', '', '2026-01-01T00:00:00Z')",
    )
    with pytest.raises(AccessError):
        cursor.connection.execute("INSERT INTO meta(key, value) VALUES ('cursor-bypass', 'denied')")


def test_nested_unit_of_work_cannot_commit_its_parent(memory_db: sqlite3.Connection) -> None:
    brain = RoleAccess(memory_db, Role.BRAIN)
    with pytest.raises(RuntimeError), memory_db:
        memory_db.execute("INSERT INTO meta(key, value) VALUES ('parent', 'preserve')")
        with brain.transaction():
            append_ledger(memory_db, "proposal", "p", {"action": "ARCHIVE"}, "2026-01-01T00:00:00Z")
        raise RuntimeError("parent fails after child succeeds")
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM meta WHERE key = 'parent'").fetchone()[0] == 0


def test_brain_generic_sql_cannot_modify_ordinary_situations(
    memory_db: sqlite3.Connection,
    basic_situation: object,
) -> None:
    with pytest.raises(AccessError):
        RoleAccess(memory_db, Role.BRAIN).execute_write(
            "situations", "UPDATE situations SET redacted_text='synthetic bypass'"
        )


def test_brain_chain_repository_validates_row_ownership(
    memory_db: sqlite3.Connection,
    basic_situation: object,
) -> None:
    from probation.core.types import Situation

    assert isinstance(basic_situation, Situation)
    brain = RoleAccess(memory_db, Role.BRAIN)
    with pytest.raises(AccessError):
        brain.insert_chain_situation(basic_situation)
    followup = basic_situation.model_copy(
        update={
            "id": "wp1-owned-chain",
            "pack": "chains",
            "family": "chain_followup",
            "variant": "CREATE_TASK",
        }
    )
    brain.insert_chain_situation(followup)
    assert (
        memory_db.execute("SELECT pack FROM situations WHERE id=?", (followup.id,)).fetchone()[0]
        == "chains"
    )


def test_trigger_cannot_write_a_foreign_role_table(memory_db: sqlite3.Connection) -> None:
    memory_db.execute("""CREATE TRIGGER cross_role AFTER INSERT ON ledger
                        BEGIN INSERT INTO meta(key,value) VALUES ('forbidden-trigger','synthetic'); END""")
    with pytest.raises(AccessError):
        RoleAccess(memory_db, Role.BRAIN).append_ledger("proposal", "p", {}, "2026-01-01T00:00:00Z")
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0


def test_dedicated_role_connection_keeps_its_authorizer(tmp_path: Path) -> None:
    from probation.db.connection import get_role_connection

    path = tmp_path / "role.sqlite"
    init_db(path)
    conn = get_role_connection(path, Role.BRAIN)
    try:
        assert conn.execute("SELECT count(*) FROM proposals").fetchone()[0] == 0
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO meta(key,value) VALUES ('bypass','synthetic')")
        with pytest.raises(AccessError):
            RoleAccess(conn, Role.EXECUTOR)
        with pytest.raises(AccessError):
            conn.set_authorizer(None)
        RoleAccess(conn, Role.BRAIN).conn.execute("SELECT count(*) FROM meta")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DROP TRIGGER ledger_no_update")
    finally:
        conn.close()
