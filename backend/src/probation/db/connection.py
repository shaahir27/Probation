"""SQLite connection management in WAL mode with foreign keys enabled.

Authority: docs/DATA_MODEL.md and docs/CONTRACT.md section 3.
"""

import sqlite3
from pathlib import Path

from probation.config import settings


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open an SQLite connection configured with WAL mode and foreign keys enabled."""
    target_path = Path(db_path) if db_path else settings.db_path
    if str(target_path) != ":memory:":
        target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    if str(target_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    """Execute schema.sql on an open connection."""
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize database tables from schema.sql."""
    conn = get_connection(db_path)
    try:
        apply_schema(conn)
    finally:
        conn.close()
