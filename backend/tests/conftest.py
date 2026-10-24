"""Pytest configuration and global fixtures.

Authority: docs/TEST_PLAN.md section 1.
"""

import json
import shutil
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.identity import normalize_user_addresses
from probation.core.types import Situation
from probation.db.connection import apply_schema, get_connection


def owner_addresses(directory: Path) -> list[str]:
    """Read the owner identity from a generated persona directory.

    Tests must not hardcode an owner address. A literal that matches nothing in the fixture
    silently turns every situation into unowned incoming mail: no message is recognized as
    sent by the owner, so no REPLY can ever be attributed and every outcome collapses to a
    WEAK default (docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.1.3).
    """
    with open(directory / "persona.json", encoding="utf-8") as f:
        addresses = normalize_user_addresses(str(json.load(f)["email"]))
    assert addresses, f"No usable owner address in {directory / 'persona.json'}"
    return addresses


@pytest.fixture
def tiny_synth_dir() -> Path:
    """Directory holding the tracked tiny synthetic fixture."""
    return Path(__file__).resolve().parent / "fixtures" / "tiny_synth"


@pytest.fixture
def tiny_synth_owner(tiny_synth_dir: Path) -> list[str]:
    """Owner identity of the tracked tiny synthetic fixture, read from its persona."""
    return owner_addresses(tiny_synth_dir)


@pytest.fixture
def writable_world_db(tiny_synth_dir: Path, tmp_path: Path) -> Path:
    """A private copy of the tracked world database for tests that open a SimWorld.

    Opening one applies its schema, so pointing a test at the tracked corpus would rewrite a
    protected synthetic fixture (scripts/check.py hashes it before and after the suite).
    """
    copied = tmp_path / "world.db"
    shutil.copyfile(tiny_synth_dir / "world.db", copied)
    return copied


@pytest.fixture
def persona_owner() -> Callable[[Path], list[str]]:
    """Owner identity reader for persona directories generated inside a test."""
    return owner_addresses


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
