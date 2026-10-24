"""SQLite statement authorization and read-only views for role-bound repositories."""

import sqlite3
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from typing import Any, cast

Authorizer = Callable[[int, str | None, str | None, str | None, str | None], int]


class AccessError(Exception):
    """A database operation exceeds the caller's actual role capability."""


WRITE_ACTIONS = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
READ_ACTIONS = {
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_SAVEPOINT,
    sqlite3.SQLITE_RECURSIVE,
}


def authorizer(
    allowed: frozenset[str],
    *,
    target: str | None = None,
    denied: list[bool] | None = None,
    role: str | None = None,
) -> Authorizer:
    """Authorize compiled SQL targets, including CTEs, aliases and trigger effects."""

    def check(
        action: int,
        table: str | None,
        column: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        permitted = action in READ_ACTIONS
        if action == sqlite3.SQLITE_FUNCTION:
            permitted = column not in {"load_extension", "writefile", "readfile"}
        elif action in WRITE_ACTIONS:
            permitted = (
                database == "main" and table in allowed and (target is None or table == target)
            )
            if table == "ledger" and action != sqlite3.SQLITE_INSERT:
                permitted = False
            if table == "admin_commands":
                permitted = permitted and (
                    (role == "api" and action == sqlite3.SQLITE_INSERT)
                    or (role == "examiner" and action == sqlite3.SQLITE_UPDATE)
                )
            if table == "drift_receipts":
                permitted = permitted and role == "examiner" and action == sqlite3.SQLITE_INSERT
        if not permitted and denied is not None:
            denied[0] = True
        return sqlite3.SQLITE_OK if permitted else sqlite3.SQLITE_DENY

    return check


@contextmanager
def statement_guard(
    conn: sqlite3.Connection,
    allowed: frozenset[str],
    *,
    target: str | None = None,
    role: str | None = None,
) -> Generator[None]:
    """Apply a role for one statement; restore a dedicated connection's bound guard."""
    blocked = [False]
    permanent = getattr(conn, "role_authorizer", None)
    bound = getattr(conn, "allowed_write_tables", None)
    if bound is not None:
        allowed = allowed & bound
    sqlite3.Connection.set_authorizer(
        conn, authorizer(allowed, target=target, denied=blocked, role=role)
    )
    try:
        yield
    except sqlite3.DatabaseError as exc:
        if blocked[0]:
            raise AccessError("SQL operation is outside the role's declared capability") from exc
        raise
    finally:
        sqlite3.Connection.set_authorizer(conn, permanent)


class ReadCursor:
    """A cursor whose connection and execute paths cannot leak a raw writer."""

    def __init__(self, conn: sqlite3.Connection, cursor: sqlite3.Cursor | None = None) -> None:
        self._conn = conn
        self._cursor = cursor if cursor is not None else conn.cursor()

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> "ReadCursor":
        with statement_guard(self._conn, frozenset()):
            self._cursor.execute(query, params)
        return self

    def fetchone(self) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self._cursor.fetchone())

    def fetchall(self) -> list[sqlite3.Row]:
        return cast(list[sqlite3.Row], self._cursor.fetchall())

    def fetchmany(self, size: int = 1) -> list[sqlite3.Row]:
        return cast(list[sqlite3.Row], self._cursor.fetchmany(size))

    def __iter__(self) -> Iterator[sqlite3.Row]:
        return iter(self.fetchall())

    @property
    def connection(self) -> "ReadConnection":
        return ReadConnection(self._conn)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    def close(self) -> None:
        self._cursor.close()


class ReadConnection:
    """Bounded SQL read capability; transaction ownership remains with the caller."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self) -> ReadCursor:
        return ReadCursor(self._conn)

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> ReadCursor:
        return self.cursor().execute(query, params)

    def frozen(self, as_of: str) -> "ReadConnection":
        """Own a consistent read snapshot without committing the caller's writes."""
        from probation.db.history_snapshot import freeze_history

        own_read = not self._conn.in_transaction
        if own_read:
            self._conn.execute("BEGIN")
        try:
            return freeze_history(self, as_of)
        finally:
            if own_read:
                self._conn.rollback()
