"""WP1: one injected clock across inference, budgets and quarantined persistence."""

import json
import sqlite3
from datetime import UTC, datetime

import httpx
import pytest

from probation.core.clock import Clock
from probation.llm.client import LLMClient


def _response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps({"ok": True})}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def _infer(client: LLMClient, conn: sqlite3.Connection) -> None:
    client.chat_json(
        kind="reader",
        model="synthetic-model",
        system="data only",
        user="synthetic",
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        cache_parts={"content_hash": "wp1-context"},
        conn=conn,
    )


def test_inference_uses_the_shared_context_clock(memory_db: sqlite3.Connection) -> None:
    from probation.core.clock import use_clock

    clock = Clock.replay(datetime(2026, 6, 1, 10, 0, 0, 123456, tzinfo=UTC))
    with use_clock(clock):
        client = LLMClient(api_key="synthetic", transport=httpx.MockTransport(_response))
        _infer(client, memory_db)
    assert memory_db.execute("SELECT created_at FROM exposure_log").fetchone()[0] == clock.now_iso()
    assert memory_db.execute("SELECT created_at FROM llm_cache").fetchone()[0] == clock.now_iso()


def test_inference_recording_rolls_back_cache_if_exposure_fails(
    memory_db: sqlite3.Connection,
) -> None:
    memory_db.execute(
        "CREATE TRIGGER reject_exposure BEFORE INSERT ON exposure_log BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
    )
    memory_db.commit()
    client = LLMClient(api_key="synthetic", transport=httpx.MockTransport(_response))
    with pytest.raises(sqlite3.DatabaseError):
        _infer(client, memory_db)
    assert memory_db.execute("SELECT count(*) FROM llm_cache").fetchone()[0] == 0


def test_inference_cannot_commit_its_callers_transaction(memory_db: sqlite3.Connection) -> None:
    memory_db.commit()
    memory_db.execute("BEGIN")
    client = LLMClient(api_key="synthetic", transport=httpx.MockTransport(_response))
    _infer(client, memory_db)
    memory_db.rollback()
    assert memory_db.execute("SELECT count(*) FROM llm_cache").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM exposure_log").fetchone()[0] == 0


def test_tavily_budget_and_audit_use_same_clock(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probation.config import settings
    from probation.web.client import TavilyClient

    clock = Clock.replay(datetime(2026, 6, 1, tzinfo=UTC))
    client = TavilyClient(api_key="synthetic", conn=memory_db, clock=clock)
    client.search("<PERSON_1>")  # rejected locally; no outbound request
    assert memory_db.execute("SELECT created_at FROM tavily_calls").fetchone()[0] == clock.now_iso()
    monkeypatch.setattr(settings, "tavily_max_calls_per_day", 1)
    assert client._check_budget()[0] is False
    clock.advance_seconds(86400)
    assert client._check_budget()[0] is True


def test_api_replay_state_uses_the_application_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from probation.api.app import app

    clock = Clock.replay(datetime(2026, 6, 1, 10, 0, 0, 123456, tzinfo=UTC))
    monkeypatch.setattr(app.state, "clock", clock)
    with TestClient(app) as client:
        response = client.get("/api/replay/state")
        assert response.status_code == 200
        assert response.json()["simulated_date"] == clock.now_iso()
