"""Every HTTP database handle is permanently bound to the API capability."""

import sqlite3
from pathlib import Path

from fastapi import HTTPException

from probation.db.access import Role
from probation.db.connection import get_role_connection


def connect_api(path: Path | str) -> sqlite3.Connection:
    conn = get_role_connection(path, Role.API)
    tables = {
        str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    required_tables = {
        "admin_commands",
        "drift_receipts",
        "outcome_events",
        "command_receipts",
        "execution_attempts",
        "command_requests",
        "user_responses",
        "actions",
    }
    required_columns = {
        "user_responses": {
            "schema_version",
            "owner_id",
            "reviewed_payload_json",
            "reviewed_payload_hash",
            "intent_hash",
        },
        "actions": {
            "authority_kind",
            "binding_json",
            "binding_hash",
            "approval_response_id",
            "undo_deadline",
        },
        "outcome_events": {"event_json", "ledger_seq", "proposal_id", "known_at"},
        "command_receipts": {"consumer", "state", "fence", "response_id", "command_id"},
        "execution_attempts": {"operation", "state", "binding_hash", "before_json", "result_json"},
        "command_requests": {"owner_id", "scope_json", "payload_hash"},
    }
    ready = required_tables.issubset(tables)
    if ready:
        try:
            for table, columns in required_columns.items():
                # Names are fixed identifiers above. Quoting an unknown column can
                # become a SQLite string literal and falsely report readiness.
                names = ",".join(sorted(columns))
                conn.execute(f'SELECT {names} FROM "{table}" LIMIT 0')
        except sqlite3.Error:
            ready = False
    if not ready:
        conn.close()
        raise HTTPException(
            status_code=503, detail="Database upgrade required: probation db migrate"
        )
    return conn
