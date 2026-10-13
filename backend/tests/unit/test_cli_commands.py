"""Tests for Probation CLI commands via Typer CliRunner.

Authority: docs/CONTRACT.md section 10 and docs/TEST_PLAN.md T-API.
"""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from probation.cli import app
from probation.config import settings
from probation.db.connection import get_connection, init_db
from probation.db.ledger import append_ledger

runner = CliRunner()


def test_cli_db_init(tmp_path: Path) -> None:
    """probation db init initializes schema."""
    test_db = tmp_path / "cli_init.db"
    with patch.object(settings, "db_path", test_db):
        result = runner.invoke(app, ["db", "init"])
        assert result.exit_code == 0
        assert "Database schema initialized successfully" in result.stdout
        assert test_db.exists()


def test_cli_ledger_verify(tmp_path: Path) -> None:
    """probation ledger verify verifies hash chain."""
    test_db = tmp_path / "cli_ledger.db"
    init_db(test_db)
    conn = get_connection(test_db)
    append_ledger(conn, "action", "ref-1", {"key": "val"}, "2026-03-01T10:00:00Z")
    conn.close()

    with patch.object(settings, "db_path", test_db):
        # 1. Clean verify
        res_ok = runner.invoke(app, ["ledger", "verify"])
        assert res_ok.exit_code == 0
        assert "Ledger verified OK" in res_ok.stdout

        # 2. Corrupted verify
        conn = get_connection(test_db)
        conn.execute("DROP TRIGGER IF EXISTS ledger_no_update;")
        conn.execute("UPDATE ledger SET hash = 'corrupt' WHERE seq = 1;")
        conn.commit()
        conn.close()

        res_corrupt = runner.invoke(app, ["ledger", "verify"])
        assert res_corrupt.exit_code == 1
        assert "Ledger corrupted at seq 1" in res_corrupt.stdout


def test_cli_budget_show(tmp_path: Path) -> None:
    """probation budget show renders exposure summary table."""
    test_db = tmp_path / "cli_budget.db"
    init_db(test_db)
    conn = get_connection(test_db)
    conn.execute(
        """
        INSERT INTO exposure_log (id, call_kind, model_id, tokens_in, tokens_out, redaction_counts_json, cost_usd, created_at)
        VALUES ('b1', 'writer', 'nvidia/nemotron-4-340b-instruct', 500, 150, '{}', 0.02, '2026-03-01T12:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    with patch.object(settings, "db_path", test_db):
        res = runner.invoke(app, ["budget", "show"])
        assert res.exit_code == 0
        assert "Probation LLM Budget & Exposure Summary" in res.stdout
        assert "$0.0200" in res.stdout


def test_cli_synth_generate(tmp_path: Path) -> None:
    """probation synth generate produces synthetic world files."""
    out_dir = tmp_path / "synth_output"
    res = runner.invoke(
        app,
        [
            "synth",
            "generate",
            "--persona-id",
            "0",
            "--seed",
            "42",
            "--size",
            "tiny",
            "--out",
            str(out_dir),
        ],
    )
    assert res.exit_code == 0
    assert "Successfully generated synthetic world" in res.stdout
    assert (out_dir / "mailbox.mbox").exists()
    assert (out_dir / "calendar.ics").exists()
    assert (out_dir / "truth.json").exists()


def test_cli_import_and_ingest(tmp_path: Path) -> None:
    """probation import and probation ingest commands execute end-to-end."""
    synth_dir = tmp_path / "synth"
    test_db = tmp_path / "probation_cli_pipeline.db"
    init_db(test_db)

    # 1. Generate small fixture
    gen_res = runner.invoke(
        app,
        [
            "synth",
            "generate",
            "--persona-id",
            "0",
            "--seed",
            "11",
            "--size",
            "tiny",
            "--out",
            str(synth_dir),
        ],
    )
    assert gen_res.exit_code == 0

    mbox_path = synth_dir / "mailbox.mbox"
    ics_path = synth_dir / "calendar.ics"
    manifest_path = synth_dir / "files_manifest.json"

    with patch.object(settings, "db_path", test_db):
        # 2. Import mail
        res_mail = runner.invoke(app, ["import", "mail", str(mbox_path)])
        assert res_mail.exit_code == 0
        assert "Mail imported successfully" in res_mail.stdout

        # 3. Import calendar
        res_cal = runner.invoke(app, ["import", "calendar", str(ics_path)])
        assert res_cal.exit_code == 0
        assert "Calendar imported successfully" in res_cal.stdout

        # 4. Import files
        res_files = runner.invoke(app, ["import", "files", str(manifest_path)])
        assert res_files.exit_code == 0
        assert "Files imported successfully" in res_files.stdout

        # 5. Ingest situations & featurize
        res_ingest = runner.invoke(app, ["ingest"])
        assert res_ingest.exit_code == 0
        assert "Ingestion complete" in res_ingest.stdout


def test_cli_stubs() -> None:
    """Stub commands report planned status cleanly."""
    res_backtest = runner.invoke(app, ["backtest"])
    assert res_backtest.exit_code == 0
    assert "Phase 4" in res_backtest.stdout

    res_exam = runner.invoke(app, ["exam", "run"])
    assert res_exam.exit_code == 0
    assert "Phase 7" in res_exam.stdout

    res_eval = runner.invoke(app, ["eval"])
    assert res_eval.exit_code == 0
    assert "Phase 10" in res_eval.stdout
