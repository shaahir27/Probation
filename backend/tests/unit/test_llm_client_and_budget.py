"""Unit tests for LLM client retries, schema fallback, budget guard, and caching.

Authority: docs/TEST_PLAN.md (T-LLM) and docs/CONTRACT.md invariants I-1, I-3, I-15, I-16.
"""

import json
import sqlite3
from typing import Any

import httpx
import pytest

from probation.llm.budget import BudgetExceeded, BudgetGuard
from probation.llm.client import LLMClient, LLMValidationError


def test_t_llm_cache_hit_avoids_http(memory_db: sqlite3.Connection) -> None:
    """T-LLM: Identical second call hits SQLite cache without network request."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"intent": "request", "urgency": 1})}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(api_key="test-key", transport=transport)

    cache_parts = {"content_hash": "hash_123", "prompt_id": "reader", "prompt_version": "v1"}
    schema = {
        "type": "object",
        "properties": {"intent": {"type": "string"}, "urgency": {"type": "integer"}},
    }

    # First call -> hits transport and writes cache
    res1 = client.chat_json(
        kind="reader",
        model="nvidia/nemotron-mini-4b-instruct",
        system="Form filler",
        user="Please review",
        schema=schema,
        cache_parts=cache_parts,
        conn=memory_db,
    )
    assert res1["intent"] == "request"
    assert called is True

    # Reset flag and call second time -> must read from cache
    called = False
    res2 = client.chat_json(
        kind="reader",
        model="nvidia/nemotron-mini-4b-instruct",
        system="Form filler",
        user="Please review",
        schema=schema,
        cache_parts=cache_parts,
        conn=memory_db,
    )
    assert res2["intent"] == "request"
    assert called is False  # Zero HTTP calls on cache hit!


def test_t_llm_budget_cap_exceeded_fails_closed(memory_db: sqlite3.Connection) -> None:
    """T-LLM: Budget cap raises BudgetExceeded before initiating an unaffordable call."""
    guard = BudgetGuard(limit_usd=0.0001)  # Very low limit
    guard.spent_usd = 0.0001  # Already reached limit

    client = LLMClient(api_key="test-key", budget_guard=guard)
    cache_parts = {"content_hash": "hash_456", "prompt_id": "reader", "prompt_version": "v1"}

    with pytest.raises(BudgetExceeded):
        client.chat_json(
            kind="reader",
            model="nvidia/nemotron-mini-4b-instruct",
            system="Form filler",
            user="Important email",
            schema={"type": "object"},
            cache_parts=cache_parts,
            conn=memory_db,
        )


def test_t_llm_retry_and_backoff_on_429() -> None:
    """T-LLM: Retries on 429 and honours Retry-After header."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"status": "ok"})}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(api_key="test-key", transport=transport)

    res = client.chat_json(
        kind="test",
        model="nvidia/nemotron-mini-4b-instruct",
        system="Test",
        user="Test request",
        schema={"type": "object"},
        cache_parts={"content_hash": "hash_retry"},
    )
    assert res["status"] == "ok"
    assert attempts == 2


def test_t_llm_json_schema_rejection_triggers_fallback() -> None:
    """T-LLM: Structured output rejection falls back to JSON-only prompt mode."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        calls.append(payload)
        # First call has json_schema in response_format -> reject with 400
        if "response_format" in payload and payload["response_format"].get("type") == "json_schema":
            return httpx.Response(400, text="Structured output not supported on this model.")
        # Fallback call has json_object -> accept
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"action": "ARCHIVE"})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(api_key="test-key", transport=transport)

    res = client.chat_json(
        kind="reader",
        model="nvidia/nemotron-mini-4b-instruct",
        system="Triage",
        user="Newsletter message",
        schema={"type": "object"},
        cache_parts={"content_hash": "hash_fb"},
    )
    assert res["action"] == "ARCHIVE"
    assert len(calls) == 2
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[1]["response_format"]["type"] == "json_object"


def test_t_llm_repair_retry_then_validation_error() -> None:
    """T-LLM: Invalid JSON triggers repair retry; fails closed with LLMValidationError on final failure."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Always return non-JSON plain text
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "I am unable to output JSON."}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(api_key="test-key", transport=transport)

    with pytest.raises(LLMValidationError):
        client.chat_json(
            kind="reader",
            model="nvidia/nemotron-mini-4b-instruct",
            system="System",
            user="User message",
            schema={"type": "object"},
            cache_parts={"content_hash": "hash_err"},
        )


def test_t_llm_exposure_log_written(memory_db: sqlite3.Connection) -> None:
    """T-LLM: Successful inference writes record to exposure_log table."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"verdict": "valid"})}}],
                "usage": {"prompt_tokens": 250, "completion_tokens": 50},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(api_key="test-key", transport=transport)

    client.chat_json(
        kind="reader",
        model="nvidia/nemotron-mini-4b-instruct",
        system="Validator",
        user="Validate this item",
        schema={"type": "object"},
        cache_parts={"content_hash": "hash_exp"},
        conn=memory_db,
        situation_id="sit_001",
        redaction_counts={"email": 2, "phone": 1},
    )

    cursor = memory_db.cursor()
    cursor.execute(
        "SELECT situation_id, call_kind, model_id, tokens_in, tokens_out FROM exposure_log;"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["situation_id"] == "sit_001"
    assert row["call_kind"] == "reader"
    assert row["tokens_in"] == 250
    assert row["tokens_out"] == 50


def test_t_llm_schema_validation_rejects_missing_field() -> None:
    """T-LLM: Validates JSON against schema and raises LLMValidationError if required field missing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"wrong_field": "val"})}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(api_key="test-key", transport=transport)

    schema = {
        "type": "object",
        "required": ["intent", "money_involved"],
        "properties": {
            "intent": {"type": "string"},
            "money_involved": {"type": "boolean"},
        },
    }

    with pytest.raises(LLMValidationError):
        client.chat_json(
            kind="reader",
            model="nvidia/nemotron-mini-4b-instruct",
            system="System",
            user="Email text",
            schema=schema,
            cache_parts={"content_hash": "hash_missing_field"},
        )


def test_t_llm_extracts_from_thought_tags_and_markdown() -> None:
    """T-LLM: Successfully parses JSON wrapped in thinking tags and markdown fences."""

    def handler(request: httpx.Request) -> httpx.Response:
        content = (
            "<think>Analyzing email...</think>\n"
            "```json\n"
            '{"intent": "question", "money_involved": false}\n'
            "```"
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(api_key="test-key", transport=transport)

    schema = {
        "type": "object",
        "required": ["intent", "money_involved"],
        "properties": {
            "intent": {"type": "string"},
            "money_involved": {"type": "boolean"},
        },
    }

    res = client.chat_json(
        kind="reader",
        model="nvidia/nemotron-mini-4b-instruct",
        system="System",
        user="Email text",
        schema=schema,
        cache_parts={"content_hash": "hash_think_md"},
    )
    assert res["intent"] == "question"
    assert res["money_involved"] is False
