"""Per-process database write helpers enforcing access boundaries.

Authority: docs/CONTRACT.md section 3.
Only designated workers/modules may write to specific tables.
"""

import sqlite3
from typing import Any


class AccessError(Exception):
    """Raised when an unauthorized component attempts to write to a restricted table."""

    pass


def write_raw_item(conn: sqlite3.Connection, item_dict: dict[str, Any]) -> None:
    """Ingestor write helper for raw_items."""
    pass


def write_proposal(conn: sqlite3.Connection, proposal_dict: dict[str, Any]) -> None:
    """Brain write helper for proposals."""
    pass


def write_outcome(conn: sqlite3.Connection, outcome_dict: dict[str, Any]) -> None:
    """Resolver write helper for outcomes."""
    pass


def write_action(conn: sqlite3.Connection, action_dict: dict[str, Any]) -> None:
    """Executor write helper for actions."""
    pass
