"""Owner command consumption: pause/resume/revoke move connection state exactly once.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5 and 7, and docs/OCT29_DEMO_BUILD_PLAN.md
10.1/12.1. Commands are submitted through the real D3 ``CommandStore`` path, applied to the real
private store with real authorities, and the observation worker's public ``tick`` gate proves
that pause/revoke block before the next provider dispatch. Everything is offline and synthetic.
"""

import ast
import inspect
import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

from probation.connectors.credentials_state import SecretMaterial
from probation.connectors.types import ConnectorError
from probation.core.clock import Clock, ClockMode
from probation.core.lifecycle import CommandIntent, CommandScope
from probation.db.access import Role, RoleAccess
from probation.db.gmail_store import (
    ConnectorAccess,
    StoreAccessError,
    migrate_store,
    open_store,
)
from probation.db.lifecycle_commands import CommandStore
from probation.workers.gmail_commands import GmailCommandConsumer
from probation.workers.gmail_observation import GmailObservationWorker
from probation.workers.restrictions import ExecutionRestrictions

CONNECTION = "conn-1"
ACCOUNT = "acct-1"
OWNER = "owner-1"
T0 = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)
T_VISIBLE = "2026-10-24T08:59:30Z"

_CONNECTION = """INSERT INTO gmail_connections
 (connection_id,account_id,owner_id,state,selection_revision,label_ids,credential_ref,
  granted_scopes,created_at,updated_at) VALUES(?,?,?,?,?,'["COHORT"]','cred-ref-1',
  '["gmail.readonly"]',?,?)"""


class _ReadGrant:
    """Read-role credential surface only; the module under test never receives one."""

    role = "read"

    def resolve_access(
        self, capability: str, required_scopes: Sequence[str] = ()
    ) -> SecretMaterial:
        del capability, required_scopes
        return SecretMaterial(value="read-token", kind="access")


class _Handles:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conns: list[ConnectorAccess] = []

    def access(self, authority: str) -> ConnectorAccess:
        conn = open_store(self.path)
        access = ConnectorAccess(conn, authority)  # type: ignore[arg-type]
        self._conns.append(access)
        return access

    def close(self) -> None:
        for access in self._conns:
            access.conn.close()


@pytest.fixture
def handles(tmp_path: Path) -> Iterator[_Handles]:
    path = tmp_path / "gmail_metadata.db"
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    bag = _Handles(path)
    yield bag
    bag.close()


def register(
    handles: _Handles,
    state: str = "ACTIVE",
    *,
    owner: str = OWNER,
    account: str = ACCOUNT,
) -> None:
    admin = handles.access("administration")
    admin.write(
        "gmail_connections",
        _CONNECTION,
        (CONNECTION, account, owner, state, 1, T_VISIBLE, T_VISIBLE),
    )


def _clock() -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=T0)


def _submit(
    engine: sqlite3.Connection,
    key: str,
    kind: str,
    *,
    owner: str = OWNER,
    account: str = ACCOUNT,
) -> None:
    CommandStore(RoleAccess(engine, Role.API)).submit(
        CommandIntent(
            request_id=key,
            owner_id=owner,
            type=kind,  # type: ignore[arg-type]
            scope=CommandScope(connection_id=CONNECTION, account_id=account),
            created_at=T_VISIBLE,
        )
    )


def _consumer(handles: _Handles, engine: sqlite3.Connection, clock: Clock) -> GmailCommandConsumer:
    return GmailCommandConsumer(
        commands=CommandStore(RoleAccess(engine, Role.API)),
        store=handles.access("administration"),
        clock=clock,
    )


def _state(handles: _Handles) -> str:
    row = handles.access("api").one(
        "SELECT state FROM gmail_connections WHERE connection_id=?", (CONNECTION,)
    )
    assert row is not None
    return str(row["state"])


def _receipts(handles: _Handles) -> list[sqlite3.Row]:
    return handles.access("api").query("SELECT * FROM gmail_command_receipts ORDER BY command_id")


def _cursor(handles: _Handles) -> tuple[int, int, str] | None:
    row = handles.access("api").one(
        "SELECT committed_history_id,fence,updated_at FROM gmail_sync_cursors"
        " WHERE connection_id=? AND resource_key='cohort'",
        (CONNECTION,),
    )
    if row is None:
        return None
    return (int(row["committed_history_id"]), int(row["fence"]), str(row["updated_at"]))


def _fake() -> FakeGmailTransport:
    fake = FakeGmailTransport(expected_token="read-token", page_size=2)
    fake.add_message(
        _Message(
            "m1",
            thread_id="t-m1",
            from_addr="alice@sender.test",
            to_addr="bob@owner.test",
            subject="subj m1",
            date="Tue, 14 Nov 2023 22:13:20 +0000",
            message_id="<m1@sender.test>",
            internal_date_ms=1700000000000,
            labels={"COHORT", "INBOX"},
            text="synthetic body",
        )
    )
    return fake


def _never_restricted(as_of: str) -> ExecutionRestrictions:
    del as_of
    return ExecutionRestrictions()


def _worker(handles: _Handles, clock: Clock, transport: object) -> GmailObservationWorker:
    return GmailObservationWorker(
        connection_id=CONNECTION,
        owner="reader-a",
        ingest=handles.access("ingestor"),
        capabilities=None,
        credentials=_ReadGrant(),
        transport=transport,  # type: ignore[arg-type]
        clock=clock,
        restrictions=_never_restricted,
        page_size=2,
    )


def _dispatch_counts(fake: FakeGmailTransport) -> tuple[int, int, int]:
    return (fake.profile_calls, fake.list_calls, fake.body_calls)


# -- pause / revoke block the observation gate ---------------------------------------------------
def test_pause_command_blocks_next_effect(handles: _Handles, memory_db: sqlite3.Connection) -> None:
    register(handles, "ACTIVE")
    clock, fake = _clock(), _fake()
    worker = _worker(handles, clock, fake)
    assert worker.tick(Event()).action == "observed"
    cursor, calls = _cursor(handles), _dispatch_counts(fake)

    _submit(memory_db, "pause-1", "pause")
    (outcome,) = _consumer(handles, memory_db, clock).consume()
    assert outcome.outcome == "applied" and outcome.applied_state == "PAUSED"
    assert _state(handles) == "PAUSED"

    # Public gate, not a re-implementation: the paused connection is read by the worker itself.
    blocked = worker.tick(Event())
    assert blocked.action == "blocked" and blocked.safe_reason == "connection_state_paused"
    assert _cursor(handles) == cursor  # no claim and no cursor advance
    assert _dispatch_counts(fake) == calls  # no provider request after the pause landed


def test_revoke_disconnects_and_stops_observation(
    handles: _Handles, memory_db: sqlite3.Connection
) -> None:
    register(handles, "ACTIVE")
    clock, fake = _clock(), _fake()
    worker = _worker(handles, clock, fake)
    assert worker.tick(Event()).action == "observed"
    cursor, calls = _cursor(handles), _dispatch_counts(fake)

    _submit(memory_db, "revoke-1", "revoke")
    (outcome,) = _consumer(handles, memory_db, clock).consume()
    assert outcome.outcome == "applied" and outcome.applied_state == "DISCONNECTED"
    assert _state(handles) == "DISCONNECTED"

    stopped = worker.tick(Event())
    assert stopped.action == "stopped" and stopped.stops_loop
    assert _cursor(handles) == cursor
    assert _dispatch_counts(fake) == calls
    assert worker.run(Event(), max_ticks=3) == 1  # disconnect ends the loop, not just one tick


def test_commands_queued_before_a_fresh_authorization_are_superseded(
    handles: _Handles, memory_db: sqlite3.Connection
) -> None:
    register(handles, "SHADOW")
    clock = _clock()
    _submit(memory_db, "stale-disconnect", "revoke")
    admin = handles.access("administration")
    admin.write(
        "gmail_connections",
        "UPDATE gmail_connections SET authorized_at=? WHERE connection_id=?",
        (T_VISIBLE, CONNECTION),
    )

    (stale,) = _consumer(handles, memory_db, clock).consume()
    assert stale.outcome == "failed"
    assert stale.safe_code == "superseded_by_reauthorization"
    assert _state(handles) == "SHADOW"

    _submit(memory_db, "post-reauthorization-disconnect", "revoke")
    (current,) = _consumer(handles, memory_db, clock).consume()
    assert current.outcome == "applied"
    assert current.applied_state == "DISCONNECTED"
    assert _state(handles) == "DISCONNECTED"


# -- resume ----------------------------------------------------------------------------------------
def test_resume_from_paused_reactivates(handles: _Handles, memory_db: sqlite3.Connection) -> None:
    register(handles, "PAUSED")
    clock, fake = _clock(), _fake()
    _submit(memory_db, "resume-1", "resume")
    (outcome,) = _consumer(handles, memory_db, clock).consume()
    assert outcome.outcome == "applied" and outcome.applied_state == "ACTIVE"
    assert _state(handles) == "ACTIVE"
    assert _worker(handles, clock, fake).tick(Event()).action == "observed"


def test_resume_from_disconnected_is_refused(
    handles: _Handles, memory_db: sqlite3.Connection
) -> None:
    register(handles, "DISCONNECTED")
    clock = _clock()
    _submit(memory_db, "resume-1", "resume")
    (outcome,) = _consumer(handles, memory_db, clock).consume()
    assert outcome.outcome == "failed" and outcome.safe_code == "resume_requires_paused"
    assert _state(handles) == "DISCONNECTED"
    (receipt,) = _receipts(handles)
    assert (
        str(receipt["state"]) == "failed" and str(receipt["safe_code"]) == "resume_requires_paused"
    )


# -- idempotency, ownership and atomicity ---------------------------------------------------------
def test_command_is_idempotent_across_restart(
    handles: _Handles, memory_db: sqlite3.Connection
) -> None:
    register(handles, "ACTIVE")
    clock = _clock()
    _submit(memory_db, "pause-1", "pause")
    assert len(_consumer(handles, memory_db, clock).consume()) == 1
    assert _state(handles) == "PAUSED"
    landed = (str(_receipts(handles)[0]["applied_at"]), _state(handles))

    clock.advance_seconds(30)
    restarted = _consumer(handles, memory_db, clock)  # new store handle and command store
    assert restarted.consume() == ()  # already receipted: skipped, not re-applied
    assert _state(handles) == "PAUSED"
    (receipt,) = _receipts(handles)
    assert str(receipt["state"]) == "applied"
    assert (str(receipt["applied_at"]), _state(handles)) == landed  # state changed exactly once


def test_command_for_unregistered_connection_stays_pending(
    handles: _Handles, memory_db: sqlite3.Connection
) -> None:
    """A command may precede its connection's registration: no receipt, so it can still apply."""
    clock = _clock()
    _submit(memory_db, "pause-before-registration", "pause")
    assert _consumer(handles, memory_db, clock).consume() == ()
    assert _receipts(handles) == []

    register(handles, "ACTIVE")
    (outcome,) = _consumer(handles, memory_db, clock).consume()
    assert outcome.outcome == "applied" and outcome.applied_state == "PAUSED"
    assert _state(handles) == "PAUSED"
    (receipt,) = _receipts(handles)
    assert str(receipt["state"]) == "applied" and str(receipt["applied_state"]) == "PAUSED"


def test_foreign_owner_command_cannot_touch_connection(
    handles: _Handles, memory_db: sqlite3.Connection
) -> None:
    register(handles, "ACTIVE", owner=OWNER, account=ACCOUNT)
    clock = _clock()
    _submit(memory_db, "pause-foreign-owner", "pause", owner="owner-evil")
    _submit(memory_db, "pause-foreign-account", "pause", account="acct-other")
    outcomes = _consumer(handles, memory_db, clock).consume()
    assert {item.command_id: (item.outcome, item.safe_code) for item in outcomes} == {
        "pause-foreign-owner": ("failed", "command_owner_mismatch"),
        "pause-foreign-account": ("failed", "command_account_mismatch"),
    }
    assert _state(handles) == "ACTIVE"
    assert {str(row["state"]) for row in _receipts(handles)} == {"failed"}
    assert {str(row["applied_state"]) for row in _receipts(handles)} == {"ACTIVE"}


def test_state_and_receipt_commit_atomically(
    handles: _Handles,
    memory_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register(handles, "ACTIVE")
    clock = _clock()
    _submit(memory_db, "pause-1", "pause")
    store = handles.access("administration")
    real_write = store.write

    def failing_write(table: str, sql: str, params: tuple[object, ...] = ()) -> int:
        if table == "gmail_command_receipts":
            raise RuntimeError("receipt write failed after the state write")
        return real_write(table, sql, params)

    monkeypatch.setattr(store, "write", failing_write)
    commands = CommandStore(RoleAccess(memory_db, Role.API))
    with pytest.raises(RuntimeError):
        GmailCommandConsumer(commands=commands, store=store, clock=clock).consume()
    assert _state(handles) == "ACTIVE"  # the state write rolled back with the receipt
    assert _receipts(handles) == []

    monkeypatch.undo()  # a later run (restart) applies the command exactly once
    (outcome,) = GmailCommandConsumer(commands=commands, store=store, clock=clock).consume()
    assert outcome.outcome == "applied"
    assert _state(handles) == "PAUSED" and len(_receipts(handles)) == 1


# -- structural capability boundary ---------------------------------------------------------------
def test_consumer_holds_no_provider_capability(
    handles: _Handles, memory_db: sqlite3.Connection
) -> None:
    module = inspect.getmodule(GmailCommandConsumer)
    assert module is not None and module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    imported = _imports(source)
    forbidden = (
        "probation.packs",
        "probation.connectors.credentials",
        "probation.workers.gmail_observation",
        "http",
        "httpx",
        "urllib",
        "socket",
        "requests",
        "google",
    )
    assert not [name for name in imported if name.startswith(forbidden)]
    assert "gmail_write" not in source and "access_token" not in source

    store = handles.access("administration")
    consumer = GmailCommandConsumer(
        commands=CommandStore(RoleAccess(memory_db, Role.API)), store=store, clock=_clock()
    )
    assert store.authority == "administration"
    assert store.allowed_tables == frozenset({"gmail_connections", "gmail_command_receipts"})
    assert not hasattr(consumer, "transport") and not hasattr(consumer, "post")
    with pytest.raises(StoreAccessError):
        store.write("gmail_effect_receipts", "DELETE FROM gmail_effect_receipts")
    with pytest.raises(ConnectorError):
        GmailCommandConsumer(
            commands=CommandStore(RoleAccess(memory_db, Role.API)),
            store=handles.access("read_worker"),
            clock=_clock(),
        )


def _imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names
