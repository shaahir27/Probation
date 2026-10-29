"""Operator-only, append-only increases to an immutable budget scope."""

import sqlite3

from probation.core.clock import parse_timestamp
from probation.core.hashing import det_id
from probation.llm.budget import BudgetExceeded


def migrate_budget_increases(conn: sqlite3.Connection) -> bool:
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Budget migration requires a clean bootstrap connection")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='budget_cap_increases'").fetchone():
        return False
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""CREATE TABLE budget_cap_increases (
            id TEXT PRIMARY KEY,
            scope_id TEXT NOT NULL REFERENCES budget_scopes(scope_id),
            previous_cap_units INTEGER NOT NULL CHECK(previous_cap_units >= 0),
            cap_units INTEGER NOT NULL CHECK(cap_units > previous_cap_units),
            created_at_op TEXT NOT NULL
        )""")
        for operation in ("UPDATE", "DELETE"):
            conn.execute(f"""CREATE TRIGGER budget_cap_increases_no_{operation.lower()}
                BEFORE {operation} ON budget_cap_increases
                BEGIN SELECT RAISE(ABORT, 'budget increases are append-only'); END""")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return True


def effective_cap(conn: sqlite3.Connection, scope_id: str, original: int) -> int:
    row = conn.execute(
        "SELECT MAX(cap_units) FROM budget_cap_increases WHERE scope_id=?", (scope_id,)
    ).fetchone()
    return max(original, int(row[0])) if row and row[0] is not None else original


def increase_budget_cap(
    conn: sqlite3.Connection, *, scope_id: str, cap_units: int, created_at_op: str
) -> None:
    """Record an explicitly approved absolute cap; retries never add more allowance."""
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Budget increases require a clean bootstrap connection")
    if type(cap_units) is not int or not 0 <= cap_units <= 9223372036854775807:
        raise BudgetExceeded("Invalid budget cap", code="amount_invalid")
    parse_timestamp(created_at_op)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT cap_units FROM budget_scopes WHERE scope_id=?", (scope_id,)
        ).fetchone()
        if row is None:
            raise BudgetExceeded("Budget scope is missing", code="scope_missing")
        current = effective_cap(conn, scope_id, int(row[0]))
        if cap_units < current:
            raise BudgetExceeded("An increase cannot lower the cap", code="amount_invalid")
        if cap_units > current:
            conn.execute(
                "INSERT INTO budget_cap_increases VALUES (?,?,?,?,?)",
                (
                    det_id("budget-increase-v1", scope_id, str(cap_units)),
                    scope_id,
                    current,
                    cap_units,
                    created_at_op,
                ),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
