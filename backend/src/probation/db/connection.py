"""SQLite connection management in WAL mode with foreign keys enabled.

Authority: docs/DATA_MODEL.md and docs/CONTRACT.md section 3.
"""

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from probation.config import settings
from probation.core.clock import configure_clock_collation
from probation.db.guards import AccessError, Authorizer

if TYPE_CHECKING:
    from probation.db.access import Role


class ManagedConnection(sqlite3.Connection):
    """Connection metadata for an optional persistent role authorizer."""

    bound_role: str | None = None
    allowed_write_tables: frozenset[str] | None = None
    role_authorizer: Authorizer | None = None

    def set_authorizer(self, callback: Authorizer | None, /) -> None:
        if self.bound_role is not None:
            raise AccessError("A dedicated role connection cannot replace its authorizer")
        super().set_authorizer(callback)


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open an SQLite connection configured with WAL mode and foreign keys enabled."""
    target_path = Path(db_path) if db_path else settings.db_path
    if str(target_path) != ":memory:":
        target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target_path), factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    configure_clock_collation(conn)
    conn.execute("PRAGMA foreign_keys = ON;")
    if str(target_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def get_role_connection(db_path: Path | str, role: "Role") -> sqlite3.Connection:
    """Open a dedicated role connection after schema/bootstrap administration."""
    from probation.db.access import ROLE_ALLOWED_WRITE_TABLES
    from probation.db.guards import authorizer

    conn = get_connection(db_path)
    if not isinstance(conn, ManagedConnection):
        raise TypeError("Role connections require the managed factory")
    conn.bound_role = role.value
    conn.allowed_write_tables = ROLE_ALLOWED_WRITE_TABLES[role]
    # Row-scoped writes require the typed repository, including on a raw cursor.
    generic_tables = (
        conn.allowed_write_tables - {"situations"}
        if role.value == "brain"
        else conn.allowed_write_tables
    )
    if role.value == "executor":
        generic_tables = generic_tables - {"outcomes"}
    conn.role_authorizer = authorizer(generic_tables, role=role.value)
    sqlite3.Connection.set_authorizer(conn, conn.role_authorizer)
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    """Execute schema.sql on an open connection."""
    configure_clock_collation(conn)
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()
    from probation.db.migrations import migrate_wp1

    migrate_wp1(conn)


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database tables from schema.sql."""
    conn = get_connection(db_path)
    try:
        apply_schema(conn)
    finally:
        conn.close()
