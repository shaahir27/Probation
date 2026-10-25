"""Bootstrap-only additive Tavily physical-attempt accounting migration."""

import sqlite3

_COLUMNS = {
    "accounting_version": "INTEGER NOT NULL DEFAULT 0 CHECK(accounting_version IN(0,1))",
    "account_label": "TEXT",
    "run_id": "TEXT",
    "request_id": "TEXT",
    "attempt_ordinal": "INTEGER",
    "state": "TEXT CHECK(state IN('reserved','dispatched','reconciled','ambiguous','never_dispatched','rejected'))",
    "reserved_units": "INTEGER CHECK(reserved_units>=0)",
    "charged_units": "INTEGER CHECK(charged_units>=0)",
    "usage_provenance": "TEXT",
    "dispatched_at": "TEXT",
    "reconciled_at": "TEXT",
    "error_code": "TEXT",
    "request_hash": "TEXT",
    "run_cap_units": "INTEGER CHECK(run_cap_units>=0)",
}


def migrate_tavily_accounting(conn: sqlite3.Connection) -> None:
    """Preserve legacy rows; never reinterpret their unverified credits as confirmed."""
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Tavily migration requires a clean bootstrap connection")
    known = {str(row[1]) for row in conn.execute("PRAGMA table_info(tavily_calls)")}
    if not known:
        raise ValueError("Tavily accounting requires the existing tavily_calls table")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for name, declaration in _COLUMNS.items():
            if name not in known:
                conn.execute(f"ALTER TABLE tavily_calls ADD COLUMN {name} {declaration}")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS tavily_physical_attempt "
            "ON tavily_calls(account_label,request_id,attempt_ordinal) "
            "WHERE accounting_version=1"
        )
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS tavily_attempt_no_replace
            BEFORE INSERT ON tavily_calls WHEN EXISTS(
              SELECT 1 FROM tavily_calls WHERE id=NEW.id AND accounting_version=1)
            BEGIN SELECT RAISE(ABORT,'Tavily attempts cannot be replaced'); END"""
        )
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS tavily_attempt_complete_identity
            BEFORE INSERT ON tavily_calls WHEN NEW.accounting_version=1 AND (
              NEW.account_label IS NULL OR NEW.run_id IS NULL OR NEW.request_id IS NULL
              OR NEW.attempt_ordinal IS NULL OR NEW.attempt_ordinal<1 OR NEW.attempt_ordinal>3
              OR NEW.state IS NULL OR NEW.state NOT IN('reserved','rejected')
              OR NEW.reserved_units IS NULL OR NEW.run_cap_units IS NULL)
            BEGIN SELECT RAISE(ABORT,'Tavily attempt identity incomplete'); END"""
        )
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS tavily_attempt_no_delete
            BEFORE DELETE ON tavily_calls WHEN OLD.accounting_version=1
            BEGIN SELECT RAISE(ABORT,'Tavily attempts are durable'); END"""
        )
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS tavily_attempt_identity
            BEFORE UPDATE ON tavily_calls WHEN OLD.accounting_version=1 AND (
              NEW.id IS NOT OLD.id OR NEW.accounting_version IS NOT OLD.accounting_version
              OR NEW.account_label IS NOT OLD.account_label OR NEW.run_id IS NOT OLD.run_id
              OR NEW.request_id IS NOT OLD.request_id OR NEW.attempt_ordinal IS NOT OLD.attempt_ordinal
              OR NEW.endpoint IS NOT OLD.endpoint OR NEW.purpose IS NOT OLD.purpose
              OR NEW.query_text IS NOT OLD.query_text OR NEW.request_hash IS NOT OLD.request_hash
              OR NEW.created_at IS NOT OLD.created_at OR NEW.run_cap_units IS NOT OLD.run_cap_units
              OR NEW.reserved_units IS NOT OLD.reserved_units)
            BEGIN SELECT RAISE(ABORT,'Tavily attempt identity is immutable'); END"""
        )
        conn.execute(
            """CREATE TRIGGER IF NOT EXISTS tavily_attempt_transition
            BEFORE UPDATE ON tavily_calls WHEN OLD.accounting_version=1 AND (NEW.state IS NULL OR NOT (
              (OLD.state='reserved' AND NEW.state IN('dispatched','never_dispatched')) OR
              (OLD.state='dispatched' AND NEW.state IN('reconciled','ambiguous')) OR
              (OLD.state='ambiguous' AND NEW.state='reconciled')))
            BEGIN SELECT RAISE(ABORT,'Tavily attempt transition refused'); END"""
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
