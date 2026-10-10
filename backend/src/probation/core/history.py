"""HistoryView: Temporal isolation preventing access to future state.

Authority: docs/CONTRACT.md section 2, invariant I-6, and section 5.
History access goes ONLY through HistoryView(as_of=t).
It exposes only outcomes and raw items with known_at <= as_of.
It has no method that can return later data.
"""

import sqlite3
from datetime import UTC, datetime
from typing import Any


class HistoryView:
    """Read-only database view bounded temporally by timestamp cutoff `as_of`."""

    def __init__(self, conn: sqlite3.Connection, as_of: str | datetime) -> None:
        self.conn = conn
        if isinstance(as_of, datetime):
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=UTC)
            else:
                as_of = as_of.astimezone(UTC)
            self.as_of = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            self.as_of = str(as_of)

    def get_raw_items(
        self,
        pack: str | None = None,
        source_id: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch raw items with known_at <= as_of."""
        query = "SELECT * FROM raw_items WHERE known_at <= ?"
        params: list[Any] = [self.as_of]

        if pack is not None:
            query += " AND pack = ?"
            params.append(pack)
        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)

        query += " ORDER BY known_at ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_situations(
        self,
        pack: str | None = None,
        family: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch situations with occurred_at <= as_of."""
        query = "SELECT * FROM situations WHERE occurred_at <= ?"
        params: list[Any] = [self.as_of]

        if pack is not None:
            query += " AND pack = ?"
            params.append(pack)
        if family is not None:
            query += " AND family = ?"
            params.append(family)

        query += " ORDER BY occurred_at ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_outcomes(
        self,
        situation_ids: list[str] | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch outcomes with known_at <= as_of."""
        query = "SELECT * FROM outcomes WHERE known_at <= ?"
        params: list[Any] = [self.as_of]

        if situation_ids is not None:
            if not situation_ids:
                return []
            placeholders = ",".join("?" for _ in situation_ids)
            query += f" AND situation_id IN ({placeholders})"
            params.extend(situation_ids)

        query += " ORDER BY known_at ASC"
        cursor = self.conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_proposals(
        self,
        class_key: str | None = None,
        action: str | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch proposals with proposed_at <= as_of."""
        query = "SELECT * FROM proposals WHERE proposed_at <= ?"
        params: list[Any] = [self.as_of]

        if class_key is not None:
            query += " AND class_key = ?"
            params.append(class_key)
        if action is not None:
            query += " AND action = ?"
            params.append(action)

        query += " ORDER BY proposed_at ASC"
        cursor = self.conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())
