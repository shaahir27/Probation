"""HTTP handles check schema capabilities without migrating old databases."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.config import settings


@pytest.mark.parametrize("tables_only", [False, True])
def test_pre_lifecycle_database_returns_upgrade_required_without_mutation(
    tmp_path, monkeypatch, tables_only
):
    path = tmp_path / "old-capabilities.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE admin_commands(id TEXT); CREATE TABLE drift_receipts(id TEXT);"
        )
        if tables_only:
            for table in (
                "outcome_events",
                "command_receipts",
                "execution_attempts",
                "command_requests",
                "user_responses",
                "actions",
            ):
                conn.execute(f'CREATE TABLE "{table}"(id TEXT)')
        original = conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    monkeypatch.setattr(settings, "db_path", path)
    with TestClient(app) as client:
        response = client.get("/api/queue")
    assert response.status_code == 503
    assert "upgrade required" in response.json()["error"]["message"].lower()
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == original
        )
