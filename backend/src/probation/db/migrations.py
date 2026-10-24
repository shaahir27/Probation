"""Explicit bootstrap-only additive migration; never runs through a worker role."""

import re
import sqlite3
from pathlib import Path

from probation.db.followup_migration import migrate_followup_proposals

_INDEX_LINE = re.compile(r"^(CREATE INDEX\s+(\w+)\s+ON\s+.*?;)(?:\s*--.*)?$")
_WP1_OBJECT = re.compile(
    r"^CREATE\s+(?:TABLE|INDEX|TRIGGER|VIEW)\s+IF\s+NOT\s+EXISTS\s+(\w+)",
    re.IGNORECASE | re.MULTILINE,
)
_SPEND_OBJECT = re.compile(
    r"^CREATE\s+(?:TABLE|UNIQUE\s+INDEX|INDEX|TRIGGER)\s+IF\s+NOT\s+EXISTS\s+(\w+)",
    re.IGNORECASE | re.MULTILINE,
)
# Rollback for the W3-D03 accounting objects. Dropping them restores the pre-P04 database:
# no other table references them, and exposure_log.cost_units is left in place because it is
# nullable and a DROP of a published column is not additive-reversible in SQLite.
_SPEND_DROP = """DROP TRIGGER IF EXISTS llm_requests_no_history_update;
DROP INDEX IF EXISTS llm_requests_semantic_identity;
DROP TRIGGER IF EXISTS llm_attempts_no_history_update;
DROP TRIGGER IF EXISTS llm_attempts_no_delete;
DROP TRIGGER IF EXISTS llm_requests_no_delete;
DROP TRIGGER IF EXISTS budget_scopes_immutable;
DROP INDEX IF EXISTS llm_attempts_open_by_scope;
DROP INDEX IF EXISTS llm_attempts_charged_by_scope;
DROP INDEX IF EXISTS llm_attempts_ordinal;
DROP TABLE IF EXISTS llm_attempts;
DROP TABLE IF EXISTS llm_requests;
DROP TABLE IF EXISTS budget_scopes;
"""


def migrate_lifecycle(conn: sqlite3.Connection) -> None:
    """Bootstrap-only atomic D3 migration; original rows and ledger remain intact."""
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Lifecycle migration requires a clean bootstrap connection")
    columns = {
        "user_responses": {
            "schema_version": "INTEGER NOT NULL DEFAULT 1 CHECK(schema_version IN(1,2))",
            "request_key": "TEXT",
            "owner_id": "TEXT",
            "reviewed_payload_json": "TEXT CHECK(reviewed_payload_json IS NULL OR json_valid(reviewed_payload_json))",
            "reviewed_payload_hash": "TEXT",
            "intent_hash": "TEXT",
        },
        "actions": {
            "authority_kind": "TEXT CHECK(authority_kind IS NULL OR authority_kind IN('autonomous','explicit_user'))",
            "approval_response_id": "TEXT REFERENCES user_responses(id)",
            "binding_json": "TEXT CHECK(binding_json IS NULL OR json_valid(binding_json))",
            "binding_hash": "TEXT",
            "undo_deadline": "TEXT",
        },
    }
    script = Path(__file__).with_name("lifecycle.sql").read_text(encoding="utf-8")
    expected = set(_SPEND_OBJECT.findall(script))
    present_objects = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    followup_ready = "followup_of_action_id" in {
        r[1] for r in conn.execute("PRAGMA table_info(proposals)")
    }
    if expected and expected <= present_objects and followup_ready:
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    legacy = int(conn.execute("PRAGMA legacy_alter_table").fetchone()[0])
    conn.execute("PRAGMA legacy_alter_table=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table, additions in columns.items():
            present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in additions.items():
                if name not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        migrate_followup_proposals(conn)
        _run_script(conn, script)
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Lifecycle migration would break foreign keys")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute(f"PRAGMA legacy_alter_table={legacy}")
        conn.execute("PRAGMA foreign_keys=ON")


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


def _run_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a multi-statement DDL script inside the caller's transaction.

    `executescript` commits implicitly, which would publish a half-applied migration, so
    statements are split the way SQLite itself splits them and run one at a time.
    """
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete migration")


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
        _run_script(conn, script)
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


def _spend_applied(conn: sqlite3.Connection) -> bool:
    """Report whether every object spend.sql declares is already present."""
    declared = _SPEND_OBJECT.findall(
        Path(__file__).with_name("spend.sql").read_text(encoding="utf-8")
    )
    if not declared:
        raise ValueError("No objects found in spend.sql")
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    if not all(name in present for name in declared):
        return False
    script = Path(__file__).with_name("spend.sql").read_text(encoding="utf-8")
    for trigger in re.findall(r"CREATE TRIGGER IF NOT EXISTS \w+ .*?END;", script, re.DOTALL):
        name = trigger.split()[5]
        stored = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        expected = trigger.replace("IF NOT EXISTS ", "", 1)
        if stored is None or _normalize_ddl(str(stored[0])) != _normalize_ddl(expected):
            return False
    return True


def _exposure_cost_units_present(conn: sqlite3.Connection) -> bool:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='exposure_log'"
    ).fetchone():
        return True
    return "cost_units" in {row[1] for row in conn.execute("PRAGMA table_info(exposure_log)")}


def migrate_spend_accounting(conn: sqlite3.Connection) -> bool:
    """Additive W3-D03 migration: durable spend scope/request/attempt accounting.

    Returns True when anything was created. Re-runnable, and it never rewrites a row that
    already exists: an attempt row is the audit of money that may already have been billed.
    """
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Migration requires a clean bootstrap connection")
    if _spend_applied(conn) and _exposure_cost_units_present(conn):
        return False

    script = Path(__file__).with_name("spend.sql").read_text(encoding="utf-8")
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Upgrade an earlier reviewed trigger definition atomically; presence alone
        # must not leave a weaker transition guard installed under the same name.
        for name in re.findall(r"CREATE TRIGGER IF NOT EXISTS (\w+)", script):
            conn.execute(f'DROP TRIGGER IF EXISTS "{name}"')
        _run_script(conn, script)
        if not _exposure_cost_units_present(conn):
            conn.execute(
                "ALTER TABLE exposure_log ADD COLUMN cost_units INTEGER "
                "CHECK (cost_units IS NULL OR cost_units >= 0)"
            )
        conn.execute("SELECT scope_id,cap_units,price_version FROM budget_scopes LIMIT 0")
        conn.execute("SELECT request_id,scope_id,owner_role,result_state FROM llm_requests LIMIT 0")
        conn.execute(
            "SELECT attempt_id,request_id,ordinal,stage,state,estimate_units,charged_units,"
            "lease_owner,lease_token FROM llm_attempts LIMIT 0"
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return True


def drop_spend_accounting(conn: sqlite3.Connection) -> None:
    """Documented rollback: remove the W3-D03 objects and nothing else.

    Operator-initiated only. Every other table is untouched, so a database rolled back this
    way is the pre-P04 database plus a nullable `exposure_log.cost_units` column that no
    reader requires.
    """
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Migration requires a clean bootstrap connection")
    conn.execute("BEGIN IMMEDIATE")
    try:
        _run_script(conn, _SPEND_DROP)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def migrate_features_provenance(conn: sqlite3.Connection) -> bool:
    """Additive migration: add provenance_json column to features table if absent."""
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Migration requires a clean bootstrap connection")

    has_features = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='features'"
    ).fetchone()
    if not has_features:
        return False

    cols = {row[1] for row in conn.execute("PRAGMA table_info(features)").fetchall()}
    if "provenance_json" in cols:
        return False

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "ALTER TABLE features ADD COLUMN provenance_json TEXT CHECK (provenance_json IS NULL OR json_valid(provenance_json));"
        )
        conn.commit()
        return True
    except BaseException:
        conn.rollback()
        raise
