"""WebFactsView: Restriction-only view exposing web facts to workers without policy bias.

Authority: docs/CONTRACT.md invariant I-21 and docs/TAVILY_AND_NEW_PACKS.md section 6.
This view NEVER includes probability, evidence, or licence fields.
"""

import sqlite3
from typing import Any


class WebFactsView:
    """Read-only view into web_facts table providing restriction-only data."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_entity_facts(self, entity_key: str) -> dict[str, Any] | None:
        """Fetch entity facts for a domain.

        Returns only restriction-relevant fields: status, origin, sources.
        Never returns probabilities or evidence weights.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT status, origin, sources_json FROM web_facts WHERE entity_key = ?;",
            (entity_key,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "entity_key": entity_key,
            "status": row["status"],
            "origin": row["origin"],
            "sources": row["sources_json"],
        }
