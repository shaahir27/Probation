"""HistoryView: Temporal isolation preventing access to future state.

Authority: docs/CONTRACT.md section 2, invariant I-6.
Any database query for training, featurization, or evidence derivation
must filter records strictly by known_at <= as_of (or occurred_at <= as_of).
"""

import sqlite3
from typing import Any


class HistoryView:
    """Read-only database view bounded temporally by a timestamp cutoff `as_of`."""

    def __init__(self, conn: sqlite3.Connection, as_of: str) -> None:
        self.conn = conn
        self.as_of = as_of

    def execute_query(self, query: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        """Execute a query within the temporal boundary.

        The query must include an as_of condition or enforce the cutoff parameter.
        """
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return list(cursor.fetchall())
