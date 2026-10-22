"""WP0: exercise CLI contracts and protect generated/published outputs."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from probation.cli import app
from probation.config import settings
from probation.db.connection import get_connection, init_db

runner = CliRunner()


def test_synthesis_default_is_private_synthetic_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["synth", "generate", "--persona-id", "2", "--size", "tiny"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data/synth/2/truth.json").is_file()
    assert not (tmp_path / "backend/tests/fixtures").exists()


def test_synthesis_requires_explicit_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "output"
    target.mkdir()
    marker = target / "do-not-overwrite.txt"
    marker.write_text("preserve", encoding="utf-8")
    result = runner.invoke(app, ["synth", "generate", "--out", str(target)])
    assert result.exit_code != 0
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not (target / "truth.json").exists()


def test_fixture_regeneration_requires_dedicated_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    target = Path("backend/tests/fixtures/tiny_synth")
    result = runner.invoke(app, ["synth", "generate", "--out", str(target)])
    assert result.exit_code != 0
    assert not target.exists()
    assert "regenerate-fixture" in result.output


def test_explicit_regeneration_and_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    target = Path("backend/tests/fixtures/tiny_synth")
    args = ["synth", "generate", "--out", str(target), "--regenerate-fixture"]
    assert runner.invoke(app, args).exit_code == 0
    assert runner.invoke(app, args).exit_code != 0
    assert runner.invoke(app, [*args, "--overwrite"]).exit_code == 0


def test_import_source_option_and_positional_alias(tmp_path: Path) -> None:
    source = tmp_path / "empty.mbox"
    source.write_text("", encoding="utf-8")
    db = tmp_path / "import.db"
    init_db(db)
    with patch.object(settings, "db_path", db):
        for args in (["--source", str(source)], [str(source)]):
            result = runner.invoke(app, ["import", "mail", *args])
            assert result.exit_code == 0, result.output
        ambiguous = runner.invoke(app, ["import", "mail", str(source), "--source", "other.mbox"])
        assert ambiguous.exit_code != 0
    conn = get_connection(db)
    try:
        assert conn.execute("SELECT count(*) FROM raw_items").fetchone()[0] == 0
    finally:
        conn.close()


def test_serve_command_starts_the_existing_api() -> None:
    with patch("uvicorn.run") as serve:
        result = runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "8123"])
    assert result.exit_code == 0, result.output
    serve.assert_called_once_with(
        "probation.api.app:app", host="127.0.0.1", port=8123, reload=False
    )


def test_evaluation_default_does_not_publish_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "eval.db"
    init_db(db)
    result = runner.invoke(app, ["eval", "run", "--db", str(db), "--suite", "fast"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data/results/fast.json").is_file()
    assert not (tmp_path / "docs/results").exists()
