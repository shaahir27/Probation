"""Append-only, SHA-256 hash-chained tamper-evident ledger.

Authority: docs/CONTRACT.md section 2, invariants I-7, I-8.
"""

import sqlite3
from typing import Any

from probation.core.hashing import canonical_json, ledger_hash

GENESIS_HASH = "0" * 64


class LedgerCorrupt(Exception):
    """Raised when ledger verification detects tampering or broken hash chain."""

    pass


def append_ledger(
    conn: sqlite3.Connection,
    kind: str,
    ref_id: str,
    payload: dict[str, Any] | str,
    created_at: str,
) -> int:
    """Append a new record to the hash-chained ledger and return its sequence number."""
    payload_json = canonical_json(payload) if isinstance(payload, dict) else payload

    cursor = conn.cursor()
    cursor.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1;")
    last_row = cursor.fetchone()

    if last_row is None:
        seq = 1
        prev_hash = GENESIS_HASH
    else:
        seq = int(last_row["seq"]) + 1
        prev_hash = str(last_row["hash"])

    current_hash = ledger_hash(prev_hash, seq, kind, payload_json)

    cursor.execute(
        """
        INSERT INTO ledger (seq, kind, ref_id, payload_json, prev_hash, hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (seq, kind, ref_id, payload_json, prev_hash, current_hash, created_at),
    )
    conn.commit()
    return seq


def verify_ledger(conn: sqlite3.Connection) -> tuple[bool, int | None]:
    """Verify hash chain integrity across all entries in the ledger.

    Returns (True, None) if intact, or (False, seq) for the first corrupted sequence number.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT seq, kind, payload_json, prev_hash, hash FROM ledger ORDER BY seq ASC;")
    rows = cursor.fetchall()

    expected_prev = GENESIS_HASH
    for row in rows:
        seq = int(row["seq"])
        kind = str(row["kind"])
        payload_json = str(row["payload_json"])
        prev_hash = str(row["prev_hash"])
        stored_hash = str(row["hash"])

        if prev_hash != expected_prev:
            return (False, seq)

        computed = ledger_hash(prev_hash, seq, kind, payload_json)
        if computed != stored_hash:
            return (False, seq)

        expected_prev = stored_hash

    return (True, None)
