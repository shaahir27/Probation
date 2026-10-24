"""D3 response races, migration rollback and dedicated-connection denials."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from probation.core.enums import GateDecision
from probation.core.hashing import canonical_json
from probation.core.lifecycle import (
    ApprovalBinding,
    LifecycleConflict,
    LifecycleDenied,
    ResponseIntent,
    binding_hash,
)
from probation.core.types import Situation
from probation.db.access import AccessError, Role, RoleAccess
from probation.db.connection import get_connection, get_role_connection
from probation.db.lifecycle_commands import CommandStore
from probation.db.lifecycle_responses import ResponseStore
from probation.db.proposals import persist_proposal
from tests.unit.test_wp1_proposals import proposal
from tests.unit.test_wp6_storage import intent


def response_fixture(
    conn: sqlite3.Connection, situation: Situation, *, executing: bool = False
) -> ResponseIntent:
    candidate = proposal(situation, "ARCHIVE")
    if executing:
        candidate = candidate.model_copy(
            update={"gate": GateDecision.EXECUTE_UNDO, "licence_level": 2, "cap": 3}
        )
    persist_proposal(RoleAccess(conn, Role.BRAIN), candidate)
    source_hash = hashlib.sha256(
        canonical_json(
            {"payload": {}, "source_ref": "synthetic-ref", "content_hash": "synthetic-hash"}
        ).encode()
    ).hexdigest()
    binding = ApprovalBinding(
        owner_id="owner",
        connection_id="synthetic",
        account_id="test",
        resource_id="synthetic-ref",
        source_hash=source_hash,
        action="ARCHIVE",
        restriction_revision="0",
    )
    return ResponseIntent(
        request_id="first",
        proposal_id="wp1-proposal",
        response="accept",
        owner_id="owner",
        responded_at="2026-01-01T10:00:01Z",
        reviewed_payload=binding,
        reviewed_payload_hash=binding_hash(binding),
    )


def test_first_decision_and_retry_survive_two_connection_race(
    memory_db: sqlite3.Connection, basic_situation: Situation, tmp_path: Path
) -> None:
    first = response_fixture(memory_db, basic_situation)
    target = tmp_path / "race.db"
    disk = get_connection(target)
    memory_db.backup(disk)
    disk.close()
    gate = Barrier(2)

    def submit(index: int) -> str:
        conn = get_role_connection(target, Role.API)
        try:
            store = ResponseStore(RoleAccess(conn, Role.API))
            request = first.model_copy(
                update={
                    "request_id": f"request-{index}",
                    "response": "accept" if index == 0 else "reject",
                }
            )
            gate.wait(timeout=5)
            try:
                store.submit(request)
                return "accepted"
            except LifecycleConflict:
                return "conflict"
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sorted(results) == ["accepted", "conflict"]
    conn = get_connection(target)
    try:
        store = ResponseStore(RoleAccess(conn, Role.API))
        saved = conn.execute("SELECT id FROM user_responses").fetchone()[0]
        value = store.get(saved)
        assert value is not None
        assert store.submit(
            value.model_copy(update={"responded_at": "2026-01-01T10:05:00Z"})
        ).existing
        with pytest.raises(LifecycleConflict):
            store.submit(value.model_copy(update={"response": "edit", "edited_action": "LEAVE"}))
        assert conn.execute("SELECT count(*) FROM user_responses").fetchone()[0] == 1
    finally:
        conn.close()


def test_invalid_clock_and_binding_do_not_reserve_initial_decision(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    first = response_fixture(memory_db, basic_situation)
    store = ResponseStore(RoleAccess(memory_db, Role.API))
    for invalid in [
        first.model_copy(update={"responded_at": basic_situation.occurred_at}),
        first.model_copy(update={"reviewed_payload_hash": "forged"}),
    ]:
        with pytest.raises(LifecycleDenied):
            store.submit(invalid)
    assert not store.submit(first).existing


@pytest.mark.parametrize("role", list(Role))
def test_dedicated_raw_cursor_cannot_write_typed_shared_tables(
    memory_db: sqlite3.Connection, tmp_path: Path, role: Role
) -> None:
    target = tmp_path / "guard.db"
    disk = get_connection(target)
    memory_db.backup(disk)
    disk.close()
    conn = get_role_connection(target, role)
    try:
        for table in [
            "command_requests",
            "command_receipts",
            "outcome_events",
            "execution_attempts",
        ]:
            with pytest.raises(sqlite3.DatabaseError):
                conn.cursor().execute(f"DELETE FROM {table}")
        if role == Role.API:
            assert not CommandStore(RoleAccess(conn, role)).submit(intent()).existing
        with pytest.raises(AccessError):
            conn.set_authorizer(None)
    finally:
        conn.close()


def test_bootstrap_migration_rolls_back_columns_and_new_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import probation.db.connection as connection
    import probation.db.migrations as migrations

    conn = get_connection(tmp_path / "legacy.db")
    schema = Path(connection.__file__).with_name("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.execute("INSERT INTO meta VALUES ('construction-record','preserve')")
    conn.commit()
    original_run = migrations._run_script

    def fail_after_script(db: sqlite3.Connection, script: str) -> None:
        original_run(db, script)
        raise RuntimeError("synthetic migration interruption")

    monkeypatch.setattr(migrations, "_run_script", fail_after_script)
    with pytest.raises(RuntimeError):
        migrations.migrate_lifecycle(conn)
    assert "schema_version" not in {r[1] for r in conn.execute("PRAGMA table_info(user_responses)")}
    assert (
        conn.execute("SELECT 1 FROM sqlite_master WHERE name='command_requests'").fetchone() is None
    )
    assert (
        conn.execute("SELECT value FROM meta WHERE key='construction-record'").fetchone()[0]
        == "preserve"
    )
    monkeypatch.setattr(migrations, "_run_script", original_run)
    migrations.migrate_lifecycle(conn)
    migrations.migrate_lifecycle(conn)
    conn.close()
