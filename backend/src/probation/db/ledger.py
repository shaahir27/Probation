"""Append-only, SHA-256 hash-chained tamper-evident ledger.

Authority: docs/CONTRACT.md section 2, invariants I-7, I-8, and docs/DATA_MODEL.md section 4.
"""

import sqlite3
from dataclasses import dataclass
from typing import Any

from probation.core.hashing import GENESIS, canonical_json, ledger_hash


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
    """Append a new record to the hash-chained ledger and return its sequence number.

    Authority: docs/DATA_MODEL.md section 4.
    """
    payload_json = canonical_json(payload)

    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    else:
        # Acquire the writer reservation before reading the head, even in a deferred
        # caller transaction. This inserts no rows and never mutates existing entries.
        conn.execute(
            "INSERT INTO ledger (seq, kind, ref_id, payload_json, prev_hash, hash, created_at) "
            "SELECT 0, '', '', '', '', '', '' WHERE 0"
        )

    cursor = conn.cursor()
    cursor.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1;")
    last_row = cursor.fetchone()

    if last_row is None:
        seq = 1
        prev_hash = GENESIS
    else:
        seq = int(last_row["seq"]) + 1
        prev_hash = str(last_row["hash"])

    current_hash = ledger_hash(prev_hash, kind, ref_id, payload_json)

    cursor.execute(
        """
        INSERT INTO ledger (seq, kind, ref_id, payload_json, prev_hash, hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (seq, kind, ref_id, payload_json, prev_hash, current_hash, created_at),
    )
    return seq


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    ok: bool
    first_broken_seq: int | None
    length: int
    head_hash: str


def ledger_snapshot(conn: sqlite3.Connection) -> LedgerSnapshot:
    """Verify and report metadata from one SQLite statement's consistent read snapshot."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT seq, kind, ref_id, payload_json, prev_hash, hash FROM ledger ORDER BY seq ASC;"
    )
    rows = cursor.fetchall()

    expected_prev = GENESIS
    broken: int | None = None
    for expected_seq, row in enumerate(rows, 1):
        seq = int(row["seq"])
        kind = str(row["kind"])
        ref_id = str(row["ref_id"])
        payload_json = str(row["payload_json"])
        prev_hash = str(row["prev_hash"])
        stored_hash = str(row["hash"])

        if seq != expected_seq or prev_hash != expected_prev:
            broken = expected_seq
            break
        try:
            computed = ledger_hash(prev_hash, kind, ref_id, payload_json)
        except (ValueError, TypeError, OverflowError):
            broken = seq
            break
        if computed != stored_hash:
            broken = seq
            break

        expected_prev = stored_hash

    return LedgerSnapshot(
        ok=broken is None,
        first_broken_seq=broken,
        length=len(rows),
        head_hash=str(rows[-1]["hash"]) if rows else GENESIS,
    )


def verify_ledger(conn: sqlite3.Connection) -> tuple[bool, int | None]:
    """Return integrity and the first broken sequence from the same snapshot."""
    snapshot = ledger_snapshot(conn)
    return snapshot.ok, snapshot.first_broken_seq
