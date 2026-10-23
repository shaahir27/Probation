"""Explicit bootstrap-only additive migration; never runs through a worker role."""

import re
import sqlite3
from pathlib import Path

_INDEX_LINE = re.compile(r"^(CREATE INDEX\s+(\w+)\s+ON\s+.*?;)(?:\s*--.*)?$")
_WP1_OBJECT = re.compile(
    r"^CREATE\s+(?:TABLE|INDEX|TRIGGER|VIEW)\s+IF\s+NOT\s+EXISTS\s+(\w+)",
    re.IGNORECASE | re.MULTILINE,
)

# sqlite_master is read positionally throughout: callers hand in plain sqlite3
# connections as well as Row-factory ones, so nothing here may depend on row_factory.


def _normalize_ddl(statement: str) -> str:
    """Canonical DDL text for comparison; sqlite_master stores no trailing semicolon."""
    return " ".join(statement.split()).rstrip(";")


def _schema_index_statements() -> list[tuple[str, str]]:
    """Read the authoritative index DDL straight out of schema.sql.

    Deriving the list from schema.sql keeps a single source of truth, so a new or
    re-collated index cannot drift away from the definition a fresh database gets.
    """
    text = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    found: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _INDEX_LINE.match(line.strip())
        if match:
            found.append((match.group(2), match.group(1)))
    declared = len(re.findall(r"\bCREATE\s+INDEX\b", text, re.IGNORECASE))
    if declared != len(found):
        raise ValueError(
            f"schema.sql declares {declared} indexes but only {len(found)} are single-line; "
            "the index migration requires exactly one per line"
        )
    if not found:
        raise ValueError("No index statements found in schema.sql")
    return found


def _index_drift(conn: sqlite3.Connection) -> list[tuple[str, str, bool]]:
    """Return (name, statement, already_exists) for each schema index that differs."""
    existing = {
        row[0]: (row[1] or "")
        for row in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
    }
    drift: list[tuple[str, str, bool]] = []
    for name, statement in _schema_index_statements():
        if _normalize_ddl(existing.get(name, "")) != _normalize_ddl(statement):
            drift.append((name, statement, name in existing))
    return drift


def _wp1_applied(conn: sqlite3.Connection) -> bool:
    """Report whether every object wp1.sql declares is already present."""
    declared = _WP1_OBJECT.findall(Path(__file__).with_name("wp1.sql").read_text(encoding="utf-8"))
    if not declared:
        raise ValueError("No objects found in wp1.sql")
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    return all(name in present for name in declared)


def migrate_wp1(conn: sqlite3.Connection) -> None:
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Migration requires a clean bootstrap connection")
    # Bail out before taking the write lock: an up-to-date database is the common case
    # for callers that only wanted to read, and BEGIN IMMEDIATE would block them.
    if _wp1_applied(conn):
        return
    script = Path(__file__).with_name("wp1.sql").read_text(encoding="utf-8")
    conn.execute("BEGIN IMMEDIATE")
    try:
        statement = ""
        for line in script.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                conn.execute(statement)
                statement = ""
        if statement.strip():
            raise ValueError("Incomplete migration")
        conn.execute(
            "SELECT id,kind,payload_json,status,result_json,requested_at,updated_at FROM admin_commands LIMIT 0"
        )
        conn.execute(
            "SELECT event_seq,class_key,action,known_at,is_correction FROM drift_receipts LIMIT 0"
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def migrate_indexes(conn: sqlite3.Connection) -> int:
    """Bring the indexes of an already-initialized database in line with schema.sql.

    `CREATE INDEX IF NOT EXISTS` is not enough on its own: an index that already
    exists under the same name but was built with a different collation is silently
    left alone, and the planner then cannot use its time column for a range seek.
    Such indexes are dropped and rebuilt. Returns the number created or rebuilt.
    """
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Migration requires a clean bootstrap connection")

    drift = _index_drift(conn)
    if not drift:
        return 0

    conn.execute("BEGIN IMMEDIATE")
    try:
        for name, statement, exists in drift:
            if exists:
                conn.execute(f'DROP INDEX "{name}"')
            conn.execute(statement)
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        }
        missing = [name for name, _, _ in drift if name not in present]
        if missing:
            raise ValueError(f"Index migration left indexes missing: {missing}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return len(drift)
