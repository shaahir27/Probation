"""D4 migration evidence: connector-store changes leave no engine byte or protected hash moved.

Authority: docs/FULL_PRODUCT_SPEC.md section 5.3, docs/WP12_D4_GMAIL_CONTRACT.md section 7 and
section 11 row 32, docs/reports/phase-6-d4.md. D4 deliberately kept the engine schema unchanged,
so the plan's "populated prior-schema upgrade" case has no prior connector schema to upgrade.
What is proved here, on real SQLite files under ``tmp_path``, is the substitute obligation:

* connector ``migrate -> rerun -> rollback -> migrate`` leaves the engine ``sqlite_master``,
  every per-table row count, the engine file bytes and the hash-chained ledger identical;
* the rollback removes only connector-owned objects;
* ``backend/tests/fixtures`` and ``docs/results`` hash the same before and after the cycle;
* a migration that fails mid-script leaves no connector table and no open transaction.

No network, no system clock, no writes outside ``tmp_path`` and no install.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from probation.db import gmail_store
from probation.db.connection import apply_schema, get_connection
from probation.db.gmail_store import (
    drop_store_objects,
    migrate_store,
    open_store,
    store_is_current,
)
from probation.db.ledger import append_ledger, ledger_snapshot, verify_ledger

ROOT = Path(__file__).resolve().parents[3]
# Mirrors scripts/check.py:19. These trees are read, never written, by this module.
PROTECTED = ("backend/tests/fixtures", "docs/results")
NOW = "2026-10-24T09:00:00+00:00"
LATER = "2026-10-24T09:05:00+00:00"


@dataclass(frozen=True, slots=True)
class _EngineSnapshot:
    """Everything the connector store must not touch, captured from one closed engine file."""

    objects: tuple[tuple[str, str, str], ...]
    rows: tuple[tuple[str, int], ...]
    ledger_head: str
    ledger_length: int
    ledger_max_seq: int
    digest: str


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _objects(conn: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    """Names plus declared SQL text, the same shape a schema diff compares."""
    rows = conn.execute(
        "SELECT type, name, COALESCE(sql, '') FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return tuple((str(row[0]), str(row[1]), str(row[2])) for row in rows)


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    return {
        name: int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])  # type: ignore[index]
        for name in names
    }


def _seed_engine(path: Path) -> None:
    """A small populated engine: three tables with rows and two real ledger entries."""
    conn = get_connection(path)
    try:
        apply_schema(conn)
        conn.executemany(
            "INSERT INTO sources (id, pack, kind, ref, imported_at) VALUES (?,?,?,?,?)",
            [
                ("src-mail", "mail", "synthetic", "fixtures/mail.mbox", NOW),
                ("src-cal", "calendar", "synthetic", "fixtures/cal.ics", NOW),
            ],
        )
        conn.executemany(
            "INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, "
            "known_at, payload_json, content_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    "raw-1",
                    "src-mail",
                    "mail",
                    "mail_in",
                    "msg-1",
                    NOW,
                    NOW,
                    '{"subject":"synthetic"}',
                    "sha256:aa",
                ),
                (
                    "raw-2",
                    "src-mail",
                    "mail",
                    "mail_sent",
                    "msg-2",
                    LATER,
                    LATER,
                    '{"subject":"synthetic"}',
                    "sha256:bb",
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO situations (id, raw_item_id, pack, family, variant, occurred_at, "
            "sender_key, content_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    "sit-1",
                    "raw-1",
                    "mail",
                    "email_action",
                    "",
                    NOW,
                    "sender@test.invalid",
                    "sha256:cc",
                    NOW,
                ),
                (
                    "sit-2",
                    "raw-2",
                    "mail",
                    "email_action",
                    "",
                    LATER,
                    "sender@test.invalid",
                    "sha256:dd",
                    LATER,
                ),
            ],
        )
        conn.commit()
        assert append_ledger(conn, "outcome", "evt-1", {"decision": "accept"}, NOW) == 1
        assert append_ledger(conn, "outcome", "evt-2", {"decision": "reject"}, LATER) == 2
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _engine_snapshot(path: Path) -> _EngineSnapshot:
    digest = _digest(path)
    conn = get_connection(path)
    try:
        ledger = ledger_snapshot(conn)
        assert ledger.ok, f"ledger chain broken at seq {ledger.first_broken_seq}"
        max_seq = int(conn.execute("SELECT max(seq) FROM ledger").fetchone()[0])  # type: ignore[index]
        snapshot = _EngineSnapshot(
            objects=_objects(conn),
            rows=tuple(sorted(_row_counts(conn).items())),
            ledger_head=ledger.head_hash,
            ledger_length=ledger.length,
            ledger_max_seq=max_seq,
            digest=digest,
        )
    finally:
        conn.close()
    assert _digest(path) == digest, "reading the engine database must not rewrite its bytes"
    return snapshot


def _run_connector_cycle(store_path: Path) -> None:
    """migrate -> rerun -> rollback -> migrate, on the separate private store file only."""
    conn = open_store(store_path)
    try:
        assert migrate_store(conn) is True
        assert migrate_store(conn) is False
        assert store_is_current(conn) is True
        drop_store_objects(conn)
        assert store_is_current(conn) is False
        assert _objects(conn) == ()
        assert migrate_store(conn) is True
        assert store_is_current(conn) is True
    finally:
        conn.close()


def _protected_hashes(root: Path) -> dict[str, str]:
    """Same walk and digest as scripts/check.py:22-29, restricted to the protected trees."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for relative in PROTECTED
        if (root / relative).is_dir()
        for path in (root / relative).rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def test_engine_schema_identical_after_connector_migration(tmp_path: Path) -> None:
    engine_path = tmp_path / "engine.db"
    store_path = tmp_path / "private" / "connectors" / "gmail_metadata.db"
    _seed_engine(engine_path)
    before = _engine_snapshot(engine_path).objects
    assert {name for _, name, _ in before} >= {"sources", "raw_items", "situations", "ledger"}

    conn = open_store(store_path)
    try:
        assert migrate_store(conn) is True
        store_names = {name for _, name, _ in _objects(conn)}
    finally:
        conn.close()
    # Non-vacuous: the connector store really was built, on its own file.
    assert {"gmail_connections", "gmail_observations", "d4_cursor_monotonic"} <= store_names
    assert store_path.is_file()

    after = _engine_snapshot(engine_path).objects
    assert after == before
    assert not [entry for entry in after if entry[1].startswith(("gmail_", "d4_"))]


def test_engine_rows_and_ledger_unchanged(tmp_path: Path) -> None:
    engine_path = tmp_path / "engine.db"
    store_path = tmp_path / "private" / "connectors" / "gmail_metadata.db"
    _seed_engine(engine_path)
    before = _engine_snapshot(engine_path)
    counts = dict(before.rows)
    assert (counts["sources"], counts["raw_items"], counts["situations"]) == (2, 2, 2)
    assert (before.ledger_length, before.ledger_max_seq) == (2, 2)

    _run_connector_cycle(store_path)

    after = _engine_snapshot(engine_path)
    assert after.ledger_head == before.ledger_head
    assert (after.ledger_max_seq, after.ledger_length) == (2, 2)
    assert after.digest == before.digest
    assert after == before

    conn = get_connection(engine_path)
    try:
        assert verify_ledger(conn) == (True, None)
    finally:
        conn.close()


def test_connector_rollback_removes_only_connector_objects(tmp_path: Path) -> None:
    engine_path = tmp_path / "engine.db"
    store_path = tmp_path / "private" / "connectors" / "gmail_metadata.db"
    _seed_engine(engine_path)
    before = _engine_snapshot(engine_path).objects

    conn = open_store(store_path)
    try:
        assert migrate_store(conn) is True
        created = {name for _, name, _ in _objects(conn)}
        # Every object in the store is connector-owned, so the rollback may remove all of them.
        assert {name for name in created if name.startswith(("gmail_", "d4_"))} == created
        drop_store_objects(conn)
        remaining = _objects(conn)
        assert remaining == ()
        assert not [entry for entry in remaining if entry[1].startswith(("gmail_", "d4_"))]
        # A rolled-back store is still a healthy, re-migratable file, not a corrupt one.
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"  # type: ignore[index]
        assert store_is_current(conn) is False
    finally:
        conn.close()

    assert _engine_snapshot(engine_path).objects == before


def test_prior_schema_is_upgraded_with_a_backfilled_authorization(tmp_path: Path) -> None:
    store_path = tmp_path / "private" / "connectors" / "gmail_metadata.db"
    store_path.parent.mkdir(parents=True)
    conn = open_store(store_path)
    try:
        conn.execute(
            """CREATE TABLE gmail_connections(
                connection_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,owner_id TEXT NOT NULL,
                state TEXT NOT NULL,selection_revision INTEGER NOT NULL,
                label_ids TEXT NOT NULL,credential_ref TEXT NOT NULL,
                granted_scopes TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                UNIQUE(account_id,connection_id)
            )"""
        )
        conn.execute(
            "INSERT INTO gmail_connections VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "connection",
                "account@example.test",
                "owner",
                "ACTIVE",
                1,
                '["Label_1"]',
                "cred-1",
                '["https://www.googleapis.com/auth/gmail.readonly"]',
                NOW,
                LATER,
            ),
        )
        assert migrate_store(conn) is True
        row = conn.execute(
            "SELECT updated_at,authorized_at FROM gmail_connections WHERE connection_id='connection'"
        ).fetchone()
        assert row["authorized_at"] == LATER
        assert migrate_store(conn) is False
    finally:
        conn.close()


def test_protected_fixtures_and_results_unchanged(tmp_path: Path) -> None:
    required = ("backend/tests/fixtures",)
    for relative in required:
        assert (ROOT / relative).is_dir(), relative
    before = _protected_hashes(ROOT)
    for relative in required:
        assert any(key.startswith(f"{relative}/") for key in before), relative

    _run_connector_cycle(tmp_path / "private" / "connectors" / "gmail_metadata.db")

    assert _protected_hashes(ROOT) == before


def test_migration_failure_leaves_no_partial_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "private" / "connectors" / "gmail_metadata.db"
    real_script = Path(gmail_store.__file__).with_name("gmail.sql").read_text(encoding="utf-8")
    # Appended after the whole real script, so a successful rollback has to undo every DDL
    # statement the script issued before this deliberately missing table aborts the transaction.
    poisoned = real_script + "\nSELECT * FROM d4_injected_missing_table;\n"
    assert len(gmail_store._split_statements(poisoned)) == (
        len(gmail_store._split_statements(real_script)) + 1
    )
    monkeypatch.setattr(gmail_store, "_script_text", lambda: poisoned)

    conn = open_store(store_path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="d4_injected_missing_table"):
            migrate_store(conn)
        assert not conn.in_transaction
        assert _objects(conn) == ()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"  # type: ignore[index]
        assert store_is_current(conn) is False
    finally:
        conn.close()

    # Restore the real script: a clean rerun must still succeed on the same store file.
    monkeypatch.setattr(gmail_store, "_script_text", lambda: real_script)
    reopened = open_store(store_path)
    try:
        assert _objects(reopened) == ()
        assert migrate_store(reopened) is True
        assert store_is_current(reopened) is True
    finally:
        reopened.close()
