"""WP1: ledger verification and metadata come from the same consistent snapshot."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from probation.api.authority import OwnerContext
from probation.config import settings
from probation.core.hashing import GENESIS
from probation.db.connection import get_connection, init_db
from probation.db.ledger import append_ledger


@pytest.mark.parametrize("count", [0, 1, 4])
def test_api_and_cli_report_the_actual_last_hash(tmp_path: Path, count: int) -> None:
    from probation.api.app import api_ledger_verify
    from probation.cli import app

    target = tmp_path / "views.db"
    init_db(target)
    conn = get_connection(target)
    with conn:
        for n in range(count):
            append_ledger(conn, "proposal", str(n), {"item": n}, "2026-01-01T00:00:00Z")
    row = conn.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    head = row[0] if row else GENESIS
    conn.close()
    with patch.object(settings, "db_path", target):
        assert api_ledger_verify(OwnerContext("owner", ())) == {
            "ok": True,
            "seq": None,
            "length": count,
            "head_hash": head,
        }
        result = CliRunner().invoke(app, ["ledger", "verify"])
    assert result.exit_code == 0
    if count:
        assert head in "".join(result.output.split())


def test_corrupt_snapshot_still_reports_its_actual_head(memory_db: sqlite3.Connection) -> None:
    from probation.db.ledger import ledger_snapshot

    for n in range(4):
        append_ledger(memory_db, "proposal", str(n), {"item": n}, "2026-01-01T00:00:00Z")
    memory_db.execute("DROP TRIGGER ledger_no_update")
    memory_db.execute("UPDATE ledger SET payload_json = '{}' WHERE seq = 2")
    expected = memory_db.execute("SELECT hash FROM ledger WHERE seq = 4").fetchone()[0]
    snapshot = ledger_snapshot(memory_db)
    assert snapshot.ok is False
    assert snapshot.first_broken_seq == 2
    assert snapshot.length == 4
    assert snapshot.head_hash == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_ledger_rejects_nonfinite_payload_before_writing(
    memory_db: sqlite3.Connection, value: float
) -> None:
    with pytest.raises(ValueError):
        append_ledger(memory_db, "proposal", "p", {"score": value}, "2026-01-01T00:00:00Z")
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0
