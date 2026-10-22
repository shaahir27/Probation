"""HistoryView: Temporal isolation preventing access to future state.

Authority: docs/CONTRACT.md section 2, invariant I-6, and section 5.
History access goes ONLY through HistoryView(as_of=t).
It exposes only outcomes and raw items with known_at <= as_of.
It has no method that can return later data.
"""

import sqlite3
from datetime import datetime
from typing import Any, cast

from probation.core.clock import format_timestamp


class HistoryView:
    """Read-only database view bounded temporally by timestamp cutoff `as_of`."""

    def __init__(self, conn: sqlite3.Connection, as_of: str | datetime) -> None:
        self._conn = conn
        self._as_of = format_timestamp(as_of)

    @property
    def as_of(self) -> str:
        return self._as_of

    def get_raw_item(self, raw_item_id: str) -> sqlite3.Row | None:
        """Fetch a single item only if it was knowable at this cut."""
        return cast(
            sqlite3.Row | None,
            self._conn.execute(
                "SELECT * FROM raw_items WHERE id=? AND known_at COLLATE UTC_TIMESTAMP <= ?",
                (raw_item_id, self.as_of),
            ).fetchone(),
        )

    def get_raw_items(
        self,
        pack: str | None = None,
        source_id: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch raw items with known_at <= as_of."""
        query = "SELECT * FROM raw_items WHERE known_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if pack is not None:
            query += " AND pack = ?"
            params.append(pack)
        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)

        query += " ORDER BY known_at COLLATE UTC_TIMESTAMP ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_situations(
        self,
        pack: str | None = None,
        family: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch situations with occurred_at <= as_of."""
        query = "SELECT * FROM situations WHERE occurred_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if pack is not None:
            query += " AND pack = ?"
            params.append(pack)
        if family is not None:
            query += " AND family = ?"
            params.append(family)

        query += " ORDER BY occurred_at COLLATE UTC_TIMESTAMP ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_outcomes(
        self,
        situation_ids: list[str] | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch outcomes with known_at <= as_of."""
        query = "SELECT * FROM outcomes WHERE known_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if situation_ids is not None:
            if not situation_ids:
                return []
            placeholders = ",".join("?" for _ in situation_ids)
            query += f" AND situation_id IN ({placeholders})"
            params.extend(situation_ids)

        query += " ORDER BY known_at COLLATE UTC_TIMESTAMP ASC"
        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_proposals(
        self,
        class_key: str | None = None,
        action: str | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch proposals with proposed_at <= as_of."""
        query = "SELECT * FROM proposals WHERE proposed_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if class_key is not None:
            query += " AND class_key = ?"
            params.append(class_key)
        if action is not None:
            query += " AND action = ?"
            params.append(action)

        query += " ORDER BY proposed_at COLLATE UTC_TIMESTAMP ASC"
        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())
