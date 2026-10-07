"""Pytest configuration and global fixtures.

Authority: docs/TEST_PLAN.md section 1.
"""

import sqlite3
from collections.abc import Generator

import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.db.connection import apply_schema, get_connection


@pytest.fixture
def replay_clock() -> Clock:
    """Fixture providing a deterministic replay clock."""
    return Clock(mode=ClockMode.REPLAY)


@pytest.fixture
def memory_db() -> Generator[sqlite3.Connection, None, None]:
    """Fixture providing an in-memory SQLite database initialized with schema.sql."""
    conn = get_connection(":memory:")
    apply_schema(conn)
    try:
        yield conn
    finally:
        conn.close()
