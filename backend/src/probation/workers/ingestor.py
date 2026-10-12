"""Ingestor worker: Ingests raw items and extracts situations.

Authority: docs/CONTRACT.md section 3 and docs/PACKS_SPEC.md section 0.
Enforces Role.INGESTOR database write boundaries.
"""

import sqlite3

from probation.db.access import Role, RoleAccess
from probation.packs.registry import registry


def ingest_situations(conn: sqlite3.Connection) -> int:
    """Extract situations from unparsed raw_items into situations table.

    Authority: docs/DATA_MODEL.md section 1.
    """
    access_conn = RoleAccess(conn, Role.INGESTOR)
    read_cursor = conn.cursor()

    # Find raw items not yet processed into situations
    read_cursor.execute(
        """
        SELECT r.*
        FROM raw_items r
        LEFT JOIN situations s ON r.id = s.raw_item_id
        WHERE s.id IS NULL
        ORDER BY r.occurred_at ASC;
        """
    )
    unprocessed_rows = read_cursor.fetchall()
    extracted_count = 0

    for row in unprocessed_rows:
        pack_name = row["pack"]
        try:
            pack = registry.get(pack_name)
        except KeyError:
            continue

        raw_item_dict = dict(row)
        situations = pack.iter_situations(raw_item_dict)

        for sit in situations:
            access_conn.execute_write(
                "situations",
                """
                INSERT OR IGNORE INTO situations
                (id, raw_item_id, pack, family, variant, occurred_at, sender_key, content_hash, redacted_text, hands_off_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    sit.id,
                    sit.raw_item_id,
                    sit.pack,
                    sit.family,
                    sit.variant,
                    sit.occurred_at,
                    sit.sender_key,
                    sit.content_hash,
                    sit.redacted_text,
                    sit.hands_off_reason,
                    sit.created_at or sit.occurred_at,
                ),
            )
            extracted_count += 1

    access_conn.commit()
    return extracted_count
