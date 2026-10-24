"""D3 durable intents: transactional migration and actual role boundaries."""

import sqlite3

import pytest

from probation.core.lifecycle import CommandIntent, CommandScope, LifecycleConflict
from probation.db.access import AccessError, Role, RoleAccess
from probation.db.lifecycle_commands import CommandStore
from probation.db.lifecycle_receipts import ReceiptStore
from probation.db.migrations import migrate_lifecycle


def intent(key: str = "pause-1", command: str = "pause") -> CommandIntent:
    return CommandIntent(
        request_id=key,
        owner_id="synthetic-owner",
        type=command,
        scope=CommandScope(connection_id="synthetic", account_id="test-account"),
        created_at="2026-10-24T00:00:00Z",
    )


def test_migration_rerun_preserves_historical_ledger(memory_db: sqlite3.Connection) -> None:
    original = list(memory_db.execute("SELECT * FROM ledger"))
    migrate_lifecycle(memory_db)
    migrate_lifecycle(memory_db)
    assert list(memory_db.execute("SELECT * FROM ledger")) == original
    assert memory_db.execute("SELECT count(*) FROM command_requests").fetchone()[0] == 0


def test_immutable_command_retry_conflict_and_row_ownership(memory_db: sqlite3.Connection) -> None:
    api = CommandStore(RoleAccess(memory_db, Role.API))
    assert not api.submit(intent()).existing
    assert api.submit(intent()).existing
    with pytest.raises(LifecycleConflict):
        api.submit(intent(command="revoke"))
    with pytest.raises(AccessError):
        CommandStore(RoleAccess(memory_db, Role.EXECUTOR)).submit(intent("forged"))
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute("UPDATE command_requests SET type='resume'")
    assert api.get("pause-1").type == "pause"


def test_receipts_are_consumer_owned_and_caller_atomic(memory_db: sqlite3.Connection) -> None:
    CommandStore(RoleAccess(memory_db, Role.API)).submit(intent())
    examiner = RoleAccess(memory_db, Role.EXAMINER)
    store = ReceiptStore(examiner)
    with pytest.raises(RuntimeError), examiner.transaction():
        claim = store.claim_command("pause-1", now="2026-10-24T00:00:01Z", owner="examiner-A")
        assert claim is not None
        store.finish(claim, now="2026-10-24T00:00:02Z", status="succeeded", result={})
        raise RuntimeError("abort caller unit of work")
    assert store.get_command("pause-1") is None
    with pytest.raises(AccessError):
        ReceiptStore(RoleAccess(memory_db, Role.EXECUTOR)).claim_command(
            "pause-1", now="2026-10-24T00:00:01Z", owner="forged"
        )


def test_generic_sql_cannot_forge_typed_receipt(memory_db: sqlite3.Connection) -> None:
    with pytest.raises(AccessError):
        RoleAccess(memory_db, Role.EXAMINER).execute_write(
            "command_receipts", "DELETE FROM command_receipts"
        )


def test_migration_requires_bootstrap_and_clean_transaction(memory_db: sqlite3.Connection) -> None:
    memory_db.execute("BEGIN")
    with pytest.raises(ValueError):
        migrate_lifecycle(memory_db)
    memory_db.rollback()
