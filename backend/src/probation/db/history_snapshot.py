"""Materialize only knowable history in a separate read-only in-memory database."""

import sqlite3

from probation.db.guards import ReadConnection


def freeze_history(source: ReadConnection, as_of: str) -> ReadConnection:
    from probation.db.connection import apply_schema, get_connection

    target = get_connection(":memory:")
    apply_schema(target)
    # A followup proposal references its already-cancelled autonomous action, which
    # in turn references the original proposal. Check that cycle at commit.
    target.execute("PRAGMA defer_foreign_keys=ON")
    # Fixed queries, never caller-supplied SQL or a copy of future private rows.
    visible_situations = """SELECT s.id FROM situations s JOIN raw_items r ON r.id=s.raw_item_id
        WHERE s.occurred_at COLLATE UTC_TIMESTAMP <= ? AND r.known_at COLLATE UTC_TIMESTAMP <= ?"""
    selections: list[tuple[str, str, tuple[str, ...]]] = [
        (
            "sources",
            """SELECT * FROM sources WHERE id IN
            (SELECT source_id FROM raw_items WHERE known_at COLLATE UTC_TIMESTAMP <= ?)""",
            (as_of,),
        ),
        (
            "raw_items",
            "SELECT * FROM raw_items WHERE known_at COLLATE UTC_TIMESTAMP <= ?",
            (as_of,),
        ),
        (
            "situations",
            f"SELECT * FROM situations WHERE id IN ({visible_situations})",
            (as_of, as_of),
        ),
        (
            "features",
            f"""SELECT * FROM features WHERE situation_id IN ({visible_situations})
            AND created_at COLLATE UTC_TIMESTAMP <= ?""",
            (as_of, as_of, as_of),
        ),
        (
            "proposals",
            f"""SELECT * FROM proposals WHERE situation_id IN ({visible_situations})
            AND proposed_at COLLATE UTC_TIMESTAMP <= ?""",
            (as_of, as_of, as_of),
        ),
        (
            "actions",
            f"""SELECT a.id,a.proposal_id,a.pack,a.type,'{{}}' AS params_json,
            a.level_required,a.recallable,a.status,a.hold_until,a.created_at,a.updated_at,
            a.executed_at,a.authority_kind FROM actions a JOIN proposals p ON p.id=a.proposal_id
            WHERE p.situation_id IN ({visible_situations})
            AND p.proposed_at COLLATE UTC_TIMESTAMP <= ?
            AND a.authority_kind='autonomous' AND a.created_at COLLATE UTC_TIMESTAMP <= ?
            AND a.updated_at COLLATE UTC_TIMESTAMP <= ?
            AND a.id IN (SELECT followup_of_action_id FROM proposals
                WHERE proposed_at COLLATE UTC_TIMESTAMP <= ?)""",
            (as_of, as_of, as_of, as_of, as_of, as_of),
        ),
        (
            "command_requests",
            "SELECT * FROM command_requests WHERE created_at COLLATE UTC_TIMESTAMP <= ?",
            (as_of,),
        ),
        (
            "command_receipts",
            """SELECT * FROM command_receipts WHERE command_id IN
            (SELECT id FROM command_requests WHERE created_at COLLATE UTC_TIMESTAMP <= ?)
            AND created_at COLLATE UTC_TIMESTAMP <= ? AND updated_at COLLATE UTC_TIMESTAMP <= ?""",
            (as_of, as_of, as_of),
        ),
        (
            "outcomes",
            f"""SELECT * FROM outcomes WHERE situation_id IN ({visible_situations})
            AND known_at COLLATE UTC_TIMESTAMP <= ?""",
            (as_of, as_of, as_of),
        ),
        (
            "ledger",
            """SELECT * FROM ledger WHERE created_at COLLATE UTC_TIMESTAMP <= ?
            AND COALESCE(json_extract(payload_json,'$.known_at'),created_at)
                COLLATE UTC_TIMESTAMP <= ? ORDER BY seq""",
            (as_of, as_of),
        ),
        (
            "drift_receipts",
            """SELECT * FROM drift_receipts WHERE known_at COLLATE UTC_TIMESTAMP <= ?
            AND event_seq IN (SELECT seq FROM ledger WHERE created_at COLLATE UTC_TIMESTAMP <= ?
            AND COALESCE(json_extract(payload_json,'$.known_at'),created_at) COLLATE UTC_TIMESTAMP <= ?)""",
            (as_of, as_of, as_of),
        ),
        (
            "drift_state",
            """SELECT * FROM drift_state WHERE last_alarm_at IS NULL
            OR last_alarm_at COLLATE UTC_TIMESTAMP <= ?""",
            (as_of,),
        ),
        (
            "family_shift",
            "SELECT * FROM family_shift WHERE week_start COLLATE UTC_TIMESTAMP <= ?",
            (as_of,),
        ),
        (
            "class_stats",
            "SELECT * FROM class_stats WHERE as_of COLLATE UTC_TIMESTAMP <= ?",
            (as_of,),
        ),
        (
            "licence_cache",
            "SELECT * FROM licence_cache WHERE computed_at COLLATE UTC_TIMESTAMP <= ?",
            (as_of,),
        ),
    ]
    try:
        for table, query, params in selections:
            rows = source.execute(query, params).fetchall()
            if not rows:
                continue
            columns = list(rows[0].keys())
            names = ",".join(f'"{column}"' for column in columns)
            placeholders = ",".join("?" for _ in columns)
            target.executemany(
                f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
                [tuple(row) for row in rows],
            )
        target.commit()
        target.execute("PRAGMA query_only=ON")
        return ReadConnection(target)
    except sqlite3.Error:
        target.close()
        raise
