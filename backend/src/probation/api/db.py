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
    if not {"admin_commands", "drift_receipts"}.issubset(tables):
        conn.close()
        raise HTTPException(
            status_code=503, detail="Database upgrade required: probation db migrate"
        )
    return conn
