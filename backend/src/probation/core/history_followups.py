"""Bounded requests for fresh Brain-owned suggestions after cancelled authority."""

import sqlite3
from typing import Any

from probation.db.guards import ReadConnection


def followup_records(
    conn: sqlite3.Connection | ReadConnection, as_of: str, limit: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT s.*,p.id AS original_proposal_id,p.family AS proposal_family,
            a.id AS cancelled_action_id
        FROM ledger l JOIN actions a ON a.id=l.ref_id
        JOIN proposals p ON p.id=a.proposal_id JOIN situations s ON s.id=p.situation_id
        JOIN raw_items r ON r.id=s.raw_item_id
        WHERE l.kind='action' AND json_extract(l.payload_json,'$.licence_lost_followup_requested')=1
        AND l.created_at COLLATE UTC_TIMESTAMP <= ?
        AND p.proposed_at COLLATE UTC_TIMESTAMP <= ?
        AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
        AND r.known_at COLLATE UTC_TIMESTAMP <= ?
        AND NOT EXISTS (SELECT 1 FROM proposals f WHERE
            f.followup_of_action_id=a.id AND f.proposed_at COLLATE UTC_TIMESTAMP <= ?)
        ORDER BY l.created_at COLLATE UTC_TIMESTAMP,l.seq LIMIT ?""",
        (as_of, as_of, as_of, as_of, as_of, limit),
    ).fetchall()
    return [dict(row) for row in rows]
