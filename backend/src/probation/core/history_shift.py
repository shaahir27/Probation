"""Time-bounded observed feature populations, independent of final outcome state."""

import json
import sqlite3
from datetime import timedelta
from typing import Any

from probation.core.clock import format_timestamp, parse_timestamp
from probation.db.guards import ReadConnection


def shift_populations(
    conn: sqlite3.Connection | ReadConnection,
    as_of: str,
    family: str,
    semantic_version: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cut = parse_timestamp(as_of)
    start, split = (
        format_timestamp(cut - timedelta(days=120)),
        format_timestamp(cut - timedelta(days=30)),
    )
    rows = conn.execute(
        """SELECT s.occurred_at,f.deterministic_json,f.reader_json,r.payload_json
        FROM situations s JOIN raw_items r ON r.id=s.raw_item_id
        JOIN features f ON f.situation_id=s.id
        WHERE s.family=? AND s.occurred_at COLLATE UTC_TIMESTAMP >= ?
        AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
        AND r.known_at COLLATE UTC_TIMESTAMP <= ?
        AND f.created_at COLLATE UTC_TIMESTAMP <= ? AND f.reader_ok=1
        AND (? IS NULL OR f.featurizer_version=?)
        ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP,s.id""",
        (family, start, as_of, as_of, as_of, semantic_version, semantic_version),
    ).fetchall()
    reference: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        det, reader = json.loads(row["deterministic_json"]), json.loads(row["reader_json"] or "{}")
        if not det.get("__deterministic_ok", True) or not det.get("__budget_ok", True):
            continue
        if det.get("__reader_required") and not reader:
            continue
        if set(det) & set(reader):
            continue
        value = {key: val for key, val in {**det, **reader}.items() if not key.startswith("__")}
        if family == "file_destination":
            from probation.core.file_tokens import tokenize_name

            value["name_tokens"] = sorted(
                tokenize_name(str(json.loads(row["payload_json"]).get("filename", "")))
            )
        (
            reference if parse_timestamp(row["occurred_at"]) < parse_timestamp(split) else current
        ).append(value)
    return reference, current
