"""Event-sourced replay engine loop.

Authority: docs/ENGINE_SPEC.md section 1.
"""

import sqlite3

from probation.core.clock import Clock


def run_replay(conn: sqlite3.Connection, clock: Clock, family: str | None = None) -> int:
    """Execute event-sourced replay over historical raw items up to current clock."""
    return 0
