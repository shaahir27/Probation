"""Bounded owner-control intents and the Examiner's completion knowledge."""

import sqlite3
from typing import Any

from probation.db.guards import ReadConnection


def control_records(conn: sqlite3.Connection | ReadConnection, as_of: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT c.*,r.state AS receipt_state,r.updated_at AS completed_at
        FROM command_requests c LEFT JOIN command_receipts r
          ON r.command_id=c.id AND r.consumer='examiner'
          AND r.updated_at COLLATE UTC_TIMESTAMP <= ?
        WHERE c.created_at COLLATE UTC_TIMESTAMP <= ?
        ORDER BY c.created_at COLLATE UTC_TIMESTAMP,c.id""",
        (as_of, as_of),
    ).fetchall()
    return [dict(row) for row in rows]
