"""Populated proposal migration retains child references, bytes and rollback safety."""

from pathlib import Path

import pytest

from probation.db import connection, migrations
from probation.db.connection import get_connection
from tests.unit.wp6_mail_fixture import seed


def test_populated_rebuild_preserves_proposal_draft_and_ledger_on_failure_and_retry(
    tmp_path, monkeypatch
):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    source, world = seed(fixture, "REPLY")
    conn = get_connection(tmp_path / "legacy.db")
    conn.executescript(
        Path(connection.__file__).with_name("schema.sql").read_text(encoding="utf-8")
    )
    for table in ("sources", "raw_items", "situations", "proposals", "drafts", "ledger"):
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        names = ",".join(columns)
        rows = source.execute(f"SELECT {names} FROM {table}").fetchall()
        conn.executemany(
            f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in columns)})", rows
        )
    conn.commit()
    before = [tuple(r) for r in conn.execute("SELECT * FROM proposals")]
    ledger = [tuple(r) for r in conn.execute("SELECT * FROM ledger")]
    original = migrations._run_script

    def interrupted(db, sql):
        original(db, sql)
        raise RuntimeError("synthetic interruption after rebuild")

    monkeypatch.setattr(migrations, "_run_script", interrupted)
    with pytest.raises(RuntimeError):
        migrations.migrate_lifecycle(conn)
    assert [tuple(r) for r in conn.execute("SELECT * FROM proposals")] == before
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    monkeypatch.setattr(migrations, "_run_script", original)
    migrations.migrate_lifecycle(conn)
    migrations.migrate_lifecycle(conn)
    assert [tuple(r)[:-1] for r in conn.execute("SELECT * FROM proposals")] == before
    assert [tuple(r) for r in conn.execute("SELECT * FROM ledger")] == ledger
    assert conn.execute("SELECT proposal_id FROM drafts").fetchone()[0] == "proposal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    source.close()
    conn.close()
    world.close()
