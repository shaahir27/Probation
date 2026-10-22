"""Pytest configuration and global fixtures.

Authority: docs/TEST_PLAN.md section 1.
"""

import sqlite3
from collections.abc import Generator

import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.types import Situation
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


@pytest.fixture(autouse=True)
def disable_live_llm_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure test suite does not make unintentional live LLM calls by default."""
    from probation.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "")


@pytest.fixture
def basic_situation(memory_db: sqlite3.Connection) -> Situation:
    """A complete synthetic source/raw/situation chain for atomic storage regressions."""
    timestamp = "2026-01-01T10:00:00Z"
    with memory_db:
        memory_db.execute(
            "INSERT INTO sources VALUES ('wp1-source', 'mail', 'synthetic', 'synthetic-wp1', ?)",
            (timestamp,),
        )
        memory_db.execute(
            "INSERT INTO raw_items VALUES ('wp1-raw', 'wp1-source', 'mail', 'mail_in', 'synthetic-ref', ?, ?, '{}', 'synthetic-hash')",
            (timestamp, timestamp),
        )
        memory_db.execute(
            "INSERT INTO situations(id, raw_item_id, pack, family, occurred_at, content_hash, created_at) VALUES ('wp1-situation', 'wp1-raw', 'mail', 'email_action', ?, 'synthetic-hash', ?)",
            (timestamp, timestamp),
        )
    return Situation(
        id="wp1-situation",
        raw_item_id="wp1-raw",
        pack="mail",
        family="email_action",
        occurred_at=timestamp,
        content_hash="synthetic-hash",
        created_at=timestamp,
    )
