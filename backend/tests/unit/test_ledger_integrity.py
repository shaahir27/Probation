"""Unit tests for hash-chained append-only ledger integrity.

Authority: docs/TEST_PLAN.md (T-LEDGER) and docs/CONTRACT.md invariants I-7, I-8.
"""

import sqlite3

import pytest

from probation.core.hashing import GENESIS
from probation.db.ledger import append_ledger, verify_ledger


def test_t_ledger_append_1000_rows_and_verify(memory_db: sqlite3.Connection) -> None:
    """T-LEDGER: Append 1,000 rows; verify() returns OK."""
    for i in range(1, 1001):
        seq = append_ledger(
            memory_db,
            kind="proposal",
            ref_id=f"prop_{i:04d}",
            payload={"step": i, "action": "ARCHIVE", "score": round(i / 1000.0, 4)},
            created_at=f"2026-01-01T{i % 24:02d}:00:00Z",
        )
        assert seq == i

    intact, corrupted_seq = verify_ledger(memory_db)
    assert intact is True
    assert corrupted_seq is None


def test_t_ledger_immutable_triggers(memory_db: sqlite3.Connection) -> None:
    """T-LEDGER: Triggers abort UPDATE and DELETE operations on ledger table."""
    append_ledger(
        memory_db,
        kind="proposal",
        ref_id="prop_01",
        payload={"action": "REPLY"},
        created_at="2026-01-01T00:00:00Z",
    )

    # Attempt direct UPDATE -> abort
    with pytest.raises(
        (sqlite3.OperationalError, sqlite3.IntegrityError), match="ledger is append-only"
    ):
        memory_db.execute("UPDATE ledger SET kind = 'hacked' WHERE seq = 1;")

    # Attempt direct DELETE -> abort
    with pytest.raises(
        (sqlite3.OperationalError, sqlite3.IntegrityError), match="ledger is append-only"
    ):
        memory_db.execute("DELETE FROM ledger WHERE seq = 1;")


def test_t_ledger_tamper_detection(memory_db: sqlite3.Connection) -> None:
    """T-LEDGER: Corrupted payload or broken link is detected at the exact sequence number."""
    for i in range(1, 11):
        append_ledger(
            memory_db,
            kind="proposal",
            ref_id=f"prop_{i}",
            payload={"action": "ARCHIVE", "idx": i},
            created_at="2026-01-01T00:00:00Z",
        )

    # Disable trigger temporarily to simulate malicious raw disk tampering
    memory_db.execute("DROP TRIGGER ledger_no_update;")
    memory_db.execute(
        'UPDATE ledger SET payload_json = \'{"action":"CORRUPTED","idx":5}\' WHERE seq = 5;'
    )
    memory_db.commit()

    intact, corrupted_seq = verify_ledger(memory_db)
    assert intact is False
    assert corrupted_seq == 5


def test_t_ledger_genesis_hash(memory_db: sqlite3.Connection) -> None:
    """T-LEDGER: First row links to GENESIS hash of 64 zeros."""
    append_ledger(
        memory_db,
        kind="proposal",
        ref_id="first_prop",
        payload={"action": "MOVE"},
        created_at="2026-01-01T00:00:00Z",
    )

    cursor = memory_db.cursor()
    cursor.execute("SELECT prev_hash FROM ledger WHERE seq = 1;")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == GENESIS
    assert row[0] == "0" * 64
