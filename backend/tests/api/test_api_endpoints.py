"""Tests for FastAPI HTTP endpoints.

Authority: docs/CONTRACT.md section 9 and docs/TEST_PLAN.md T-API.
"""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from probation.api.app import app
from probation.config import settings
from probation.db.connection import get_connection, init_db
from probation.db.ledger import append_ledger

client = TestClient(app)


def test_health_endpoints() -> None:
    """GET /health and GET /api/health return liveness status."""
    res1 = client.get("/health")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ok"
    assert data1["service"] == "probation"
    assert "mode" in data1

    res2 = client.get("/api/health")
    assert res2.status_code == 200
    assert res2.json() == data1


def test_api_settings_endpoint() -> None:
    """GET /api/settings returns effective tunables without leaking secrets."""
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "budget_hard_limit_usd" in data
    assert "l1_min_n" in data
    assert "l2_min_n" in data
    assert "cusum_threshold" in data
    # Invariant: Never leak secret keys in settings output
    assert "llm_api_key" not in data
    assert "tavily_api_key" not in data


def test_api_ledger_verify_clean(tmp_path: Path) -> None:
    """GET /api/ledger/verify returns ok on intact database."""
    test_db = tmp_path / "test_api.db"
    init_db(test_db)
    conn = get_connection(test_db)
    append_ledger(conn, "proposal", "ref-1", {"detail": "sample"}, "2026-03-01T10:00:00Z")
    conn.close()

    with patch.object(settings, "db_path", test_db):
        res = client.get("/api/ledger/verify")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["seq"] is None
        assert data["length"] == 1
        assert len(data["head_hash"]) == 64


def test_api_ledger_verify_tampered(tmp_path: Path) -> None:
    """GET /api/ledger/verify detects corruption."""
    test_db = tmp_path / "test_api_corrupt.db"
    init_db(test_db)
    conn = get_connection(test_db)
    append_ledger(conn, "proposal", "ref-1", {"foo": 1}, "2026-03-01T10:00:00Z")
    append_ledger(conn, "outcome", "ref-2", {"foo": 2}, "2026-03-01T10:01:00Z")

    # Direct sqlite tampering by bypassing triggers (drop triggers and mutate)
    conn.execute("DROP TRIGGER IF EXISTS ledger_no_update;")
    conn.execute("UPDATE ledger SET hash = 'corrupted_hash' WHERE seq = 2;")
    conn.commit()
    conn.close()

    with patch.object(settings, "db_path", test_db):
        res = client.get("/api/ledger/verify")
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is False
        assert data["seq"] == 2


def test_api_exposure_endpoint(tmp_path: Path) -> None:
    """GET /api/exposure aggregates LLM exposure logs."""
    test_db = tmp_path / "test_exposure.db"
    init_db(test_db)
    conn = get_connection(test_db)
    conn.execute(
        """
        INSERT INTO exposure_log (id, call_kind, model_id, tokens_in, tokens_out, redaction_counts_json, cost_usd, created_at)
        VALUES ('exp1', 'reader', 'nvidia/nemotron-mini-4b-instruct', 120, 40, '{}', 0.005, '2026-03-01T12:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    with patch.object(settings, "db_path", test_db):
        res = client.get("/api/exposure")
        assert res.status_code == 200
        data = res.json()
        assert data["calls"] == 1
        assert data["total_cost_usd"] == 0.005
        assert len(data["breakdown"]) == 1
        assert data["breakdown"][0]["call_kind"] == "reader"


def test_uniform_error_shape() -> None:
    """Contract requires error shape: { 'error': { 'code': str, 'message': str } }."""
    res = client.get("/api/nonexistent-route-for-testing")
    assert res.status_code == 404
    data = res.json()
    assert "error" in data
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert data["error"]["code"] == "404"
