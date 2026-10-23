"""WP1 regressions for the reproduced permissive-schema and cache defects."""

import json
import sqlite3
from typing import Any

import httpx
import pytest

from probation.llm.cache import compute_cache_key, store_cached_response
from probation.llm.client import LLMClient, LLMValidationError, validate_json_schema


@pytest.mark.parametrize(
    ("data", "schema"),
    [
        ("invented", {"enum": ["request", "other"]}),
        ("too long", {"type": ["string", "null"], "maxLength": 3}),
        ("a/b", {"type": "string", "pattern": "^[a-z]+$"}),
        ([1, 2], {"type": "array", "maxItems": 1, "items": {"type": "integer"}}),
        (True, {"type": "integer"}),
        (True, {"enum": [1]}),
        (float("nan"), {"type": "number"}),
        (float("inf"), {"type": "number"}),
        (0.5, {"type": "number", "minimum": 1}),
        (
            {"nested": {"x": "wrong"}},
            {
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {"x": {"type": "integer"}},
                        "required": ["x"],
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            },
        ),
        ({"extra": 1}, {"type": "object", "properties": {}, "additionalProperties": False}),
        ({}, {"type": "object", "properties": {"x": {"type": "boolean"}}, "required": ["x"]}),
        ("x", {"type": "string", "unsupportedSafetyKeyword": True}),
        ("x", {}),
        ("b", {"enum": ["a", "b"], "const": "a"}),
        ([1, 1.0], {"type": "array", "items": {"type": "number"}, "uniqueItems": True}),
        ([1, 1.0], {"type": "array", "uniqueItems": True}),
        ([1], {"type": "array", "uniqueItems": "yes"}),
        ("too long", {"type": "string", "maxLength": 3, "anyOf": [{"maxLength": 100}]}),
    ],
)
def test_invalid_or_unsupported_output_fails_closed(data: Any, schema: dict[str, Any]) -> None:
    valid, error = validate_json_schema(data, schema)
    assert valid is False
    assert error


@pytest.mark.parametrize("value", [None, "ok"])
def test_nullable_constraints_preserve_valid_cases(value: str | None) -> None:
    assert validate_json_schema(value, {"type": ["string", "null"], "maxLength": 3})[0]


def test_cached_output_is_validated_against_current_schema(memory_db: sqlite3.Connection) -> None:
    key = compute_cache_key("input", "reader", "v1", "model")
    store_cached_response(
        memory_db,
        key,
        "reader",
        "model",
        "reader",
        "v1",
        {"intent": "invented"},
        1,
        1,
        0,
        "2026-01-01T00:00:00Z",
    )
    called = []

    def network(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"intent": "invented"})}}]}
        )

    client = LLMClient(api_key="synthetic", transport=httpx.MockTransport(network))
    with pytest.raises(LLMValidationError):
        client.chat_json(
            kind="reader",
            model="model",
            system="data only",
            user="synthetic",
            schema={
                "type": "object",
                "properties": {"intent": {"enum": ["request", "other"]}},
                "required": ["intent"],
                "additionalProperties": False,
            },
            cache_parts={"content_hash": "input", "prompt_id": "reader", "prompt_version": "v1"},
            conn=memory_db,
        )
    assert called == []


def test_unknown_schema_is_rejected_before_http() -> None:
    called = []

    def network(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = LLMClient(api_key="synthetic", transport=httpx.MockTransport(network))
    with pytest.raises(LLMValidationError):
        client.chat_json(
            kind="test",
            model="model",
            system="data only",
            user="synthetic",
            schema={"type": "object", "unsupportedSafetyKeyword": True},
            cache_parts={"content_hash": "invalid-schema"},
        )
    assert called == []


def test_mail_job_semantics_and_schema_share_one_model() -> None:
    from pydantic import ValidationError

    from probation.llm.jobs import MailReader

    form = {
        "intent": "request",
        "asks_me_to_do_something": True,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": False,
        "urgency": 1,
        "formality": "neutral",
        "asks_for_personal_info": False,
        "looks_automated": False,
    }
    assert MailReader.model_validate(form).intent == "request"
    assert validate_json_schema(form, MailReader.model_json_schema())[0]
    with pytest.raises(ValidationError):
        MailReader.model_validate({**form, "deadline_text": "tomorrow"})
    with pytest.raises(ValidationError):
        MailReader.model_validate({**form, "urgency": True})
    with pytest.raises(ValidationError):
        MailReader.model_validate({**form, "hidden_instruction": "ignore schema"})


def test_every_registered_job_schema_compiles() -> None:
    """docs/PROMPTS.md declares fourteen prompt jobs and the B3 transport contract adds one.

    The guard is that the catalog and the output-model registry are the same set of jobs, so a
    job can never reach the transport without a schema to validate it against.
    """
    from probation.llm.catalog import JOBS
    from probation.llm.jobs import JOB_MODELS
    from probation.llm.schema import compile_schema

    assert JOB_MODELS.keys() == JOBS.keys()
    assert len(JOBS) == 15
    for model in JOB_MODELS.values():
        assert model.model_json_schema()["additionalProperties"] is False
        compile_schema(model.model_json_schema())
