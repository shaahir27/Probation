"""Explicit bootstrap-only additive migration; never runs through a worker role."""

import sqlite3
from pathlib import Path


def migrate_wp1(conn: sqlite3.Connection) -> None:
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Migration requires a clean bootstrap connection")
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
