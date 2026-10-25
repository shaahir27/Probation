"""Private connector metadata store: separate file, separate authority, no engine writes.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 7. This store deliberately does not live in
the engine database, because CONTRACT.md section 3 grants the ingestor only `sources`,
`raw_items` and `situations`, and section 3's closing note forbids reading a specification as
a blanket allowlist extension. `ATTACH` is not an option either: guards permit writes only in
`main`, so an attached schema would be unwritable for a role connection.
"""

import re
import sqlite3
from pathlib import Path
from typing import Literal, cast

from probation.core.clock import configure_clock_collation
from probation.db.connection import ManagedConnection
from probation.db.guards import AccessError, authorizer

ConnectorAuthority = Literal["administration", "ingestor", "read_worker", "executor", "api"]

_AUTHORITY_TABLES: dict[ConnectorAuthority, frozenset[str]] = {
    "administration": frozenset({"gmail_connections", "gmail_command_receipts"}),
    "ingestor": frozenset(
        {
            "gmail_history_events",
            "gmail_observations",
            "gmail_sync_cursors",
            "gmail_worker_leases",
        }
    ),
    "read_worker": frozenset({"gmail_capabilities", "gmail_worker_leases", "gmail_sync_cursors"}),
    "executor": frozenset(
        {
            "gmail_capabilities",
            "gmail_credential_state",
            "gmail_effect_receipts",
            "gmail_worker_leases",
        }
    ),
    "api": frozenset(),
}

_ALL_TABLES = frozenset(
    {
        "gmail_connections",
        "gmail_history_events",
        "gmail_observations",
        "gmail_sync_cursors",
        "gmail_capabilities",
        "gmail_worker_leases",
        "gmail_effect_receipts",
        "gmail_credential_state",
        "gmail_command_receipts",
    }
)

_OBJECT = re.compile(
    r"^CREATE\s+(?:TABLE|UNIQUE\s+INDEX|INDEX|TRIGGER)\s+IF\s+NOT\s+EXISTS\s+(\w+)",
    re.IGNORECASE | re.MULTILINE,
)

# Rollback removes D4 objects and nothing else. Written in reverse dependency order.
_DROP = """DROP TRIGGER IF EXISTS d4_command_receipt_no_delete;
DROP TRIGGER IF EXISTS d4_command_receipt_immutable;
DROP TABLE IF EXISTS gmail_command_receipts;
DROP TRIGGER IF EXISTS d4_credential_generation;
DROP TRIGGER IF EXISTS d4_credential_identity;
DROP TABLE IF EXISTS gmail_credential_state;
DROP TRIGGER IF EXISTS d4_receipt_no_delete;
DROP TRIGGER IF EXISTS d4_receipt_immutable;
DROP TABLE IF EXISTS gmail_effect_receipts;
DROP TRIGGER IF EXISTS d4_lease_monotonic;
DROP TRIGGER IF EXISTS d4_lease_identity;
DROP TABLE IF EXISTS gmail_worker_leases;
DROP TRIGGER IF EXISTS d4_capability_identity;
DROP TABLE IF EXISTS gmail_capabilities;
DROP TRIGGER IF EXISTS d4_cursor_no_delete;
DROP TRIGGER IF EXISTS d4_cursor_monotonic;
DROP TRIGGER IF EXISTS d4_cursor_identity;
DROP TABLE IF EXISTS gmail_sync_cursors;
DROP INDEX IF EXISTS d4_observation_account;
DROP TRIGGER IF EXISTS d4_observation_no_delete;
DROP TRIGGER IF EXISTS d4_observation_immutable;
DROP TABLE IF EXISTS gmail_observations;
DROP INDEX IF EXISTS d4_history_message;
DROP TRIGGER IF EXISTS d4_history_no_delete;
DROP TRIGGER IF EXISTS d4_history_immutable;
DROP TABLE IF EXISTS gmail_history_events;
DROP TRIGGER IF EXISTS d4_connection_no_delete;
DROP TRIGGER IF EXISTS d4_connection_identity;
DROP TABLE IF EXISTS gmail_connections;
"""


class StoreAccessError(PermissionError):
    """An authority tried to write a row it does not own."""


def default_store_path() -> Path:
    """Private, gitignored location. Never a repository-tracked path."""
    from probation.config import settings

    return Path(settings.db_path).parent.parent / "private" / "connectors" / "gmail_metadata.db"


def open_store(path: Path | str | None = None) -> ManagedConnection:
    """Open the private store with explicit transaction control. Caller verifies ACLs first."""
    target = Path(path) if path is not None else default_store_path()
    in_memory = str(target) == ":memory:"
    if not in_memory:
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), factory=ManagedConnection, isolation_level=None)
    conn.row_factory = sqlite3.Row
    configure_clock_collation(conn)
    conn.execute("PRAGMA foreign_keys = ON;")
    if not in_memory:
        conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def _script_text() -> str:
    return Path(__file__).with_name("gmail.sql").read_text(encoding="utf-8")


def _split_statements(script: str) -> list[str]:
    out: list[str] = []
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            out.append(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete connector migration script")
    return out


def _declared_objects(script: str) -> set[str]:
    names = set(_OBJECT.findall(script))
    if not names:
        raise ValueError("No objects declared in gmail.sql")
    return names


def migrate_store(conn: sqlite3.Connection) -> bool:
    """Create or upgrade the connector store atomically. Rerunnable; reports work done."""
    if conn.in_transaction:
        raise StoreAccessError("Connector migration requires a clean connection")
    script = _script_text()
    declared = _declared_objects(script)
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    if declared <= present:
        return False
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Presence alone must not leave a weaker guard installed under the same name.
        for name in declared:
            if name.startswith("d4_") and name in present:
                conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
        for statement in _split_statements(script):
            conn.execute(statement)
        conn.execute(
            "SELECT connection_id,committed_history_id,fence,catchup_complete "
            "FROM gmail_sync_cursors LIMIT 0"
        )
        conn.execute(
            "SELECT operation_id,outcome,anchor_history_id,verified_no_effect "
            "FROM gmail_effect_receipts LIMIT 0"
        )
        conn.execute("SELECT credential_ref,generation FROM gmail_credential_state LIMIT 0")
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return True


def drop_store_objects(conn: sqlite3.Connection) -> None:
    """Documented rollback of D4 objects only. Operator-initiated; engine data untouched."""
    if conn.in_transaction:
        raise StoreAccessError("Connector rollback requires a clean connection")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _split_statements(_DROP):
            conn.execute(statement)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def store_is_current(conn: sqlite3.Connection) -> bool:
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    return _declared_objects(_script_text()) <= present


class ConnectorAccess:
    """One authority per connection, enforced by a SQLite authorizer, not by convention."""

    def __init__(self, conn: sqlite3.Connection, authority: ConnectorAuthority) -> None:
        if not isinstance(conn, ManagedConnection):
            raise StoreAccessError("Connector store requires the managed connection factory")
        if conn.bound_role is not None:
            raise StoreAccessError("Connector connection is already bound to an authority")
        allowed = _AUTHORITY_TABLES[authority]
        self._conn = conn
        self.authority = authority
        self.allowed_tables = allowed
        conn.allowed_write_tables = allowed
        conn.role_authorizer = authorizer(allowed, role=authority)
        # Assigned last so a second authority can never rebind this connection.
        conn.bound_role = f"connector:{authority}"

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def verify_write(self, table: str) -> None:
        if table not in _ALL_TABLES:
            raise StoreAccessError("Unknown connector table")
        if table not in self.allowed_tables:
            raise StoreAccessError(f"Authority '{self.authority}' may not write '{table}'")

    def write(self, table: str, sql: str, params: tuple[object, ...] = ()) -> int:
        """Scoped write. The installed authorizer is the second, independent line of denial."""
        self.verify_write(table)
        try:
            cursor = self._conn.execute(sql, params)
        except AccessError as exc:
            raise StoreAccessError("Connector write exceeds authority") from exc
        except sqlite3.IntegrityError as exc:
            raise StoreAccessError(f"Connector write violated invariants: {exc}") from exc
        return cursor.rowcount

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        return cast("sqlite3.Row | None", self._conn.execute(sql, params).fetchone())

    def transaction(self) -> "StoreTransaction":
        return StoreTransaction(self)


class StoreTransaction:
    """Atomic unit: a page of observations and its cursor advance commit together or not at all."""

    def __init__(self, access: ConnectorAccess) -> None:
        self._access = access
        self._conn = access.conn

    def __enter__(self) -> ConnectorAccess:
        if self._conn.in_transaction:
            raise StoreAccessError("Nested connector transactions are not permitted")
        self._conn.execute("BEGIN IMMEDIATE")
        return self._access

    def __exit__(self, exc_type: object, exc: object, tb: object) -> Literal[False]:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False
