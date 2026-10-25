"""Configured model discovery is read-only and sanitized at the LLM boundary."""

import httpx
import pytest

from probation.llm.client import LLMClient
from probation.llm.errors import LLMValidationError


def test_catalog_is_exact_and_contains_only_public_model_fields():
    def handler(request):
        assert request.url.path == "/v1/models"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "configured/model", "pricing": {"input": "0.06"}, "secret": "hidden"}
                ]
            },
        )

    client = LLMClient(api_key="synthetic-key", transport=httpx.MockTransport(handler))
    result = client.available_models()
    assert result == [{"id": "configured/model", "pricing": {"input": "0.06"}}]


@pytest.mark.parametrize("code", [401, 403, 404, 500])
def test_catalog_failure_does_not_expose_provider_body(code):
    client = LLMClient(
        api_key="synthetic-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(code, text="SECRET PROVIDER BODY")),
    )
    with pytest.raises(LLMValidationError) as failure:
        client.available_models()
    assert "SECRET" not in str(failure.value)


def test_instruction_profile_changes_cache_features_and_wire_without_prompt_edits(monkeypatch):
    from probation.config import settings
    from probation.llm.catalog import resolve_job
    from probation.llm.feature_identity import semantic_feature_version
    from probation.llm.gateway import build_envelope
    from probation.llm.generation import generation_options
    from probation.llm.prompt_loader import load_prompt

    asset = load_prompt(resolve_job("reader.mail", "v3"))

    def envelope():
        return build_envelope(
            asset=asset,
            model_id=settings.model_reader,
            system="fixed",
            user="fixed",
            purpose="test",
        )

    monkeypatch.setattr(settings, "llm_instruction_only", False)
    old, old_features = envelope(), semantic_feature_version()
    assert generation_options(settings.model_reader) == {}
    monkeypatch.setattr(settings, "llm_instruction_only", True)
    new = envelope()
    assert new.cache_key() != old.cache_key()
    assert semantic_feature_version() != old_features
    assert new.template_hash == old.template_hash
    assert generation_options(settings.model_reader) == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert generation_options("unconfigured/model") == {}


def test_instruction_profile_reaches_transport_and_reuses_its_own_cache(memory_db, monkeypatch):
    import json
    from decimal import Decimal

    from probation.config import settings
    from probation.llm.budget import BudgetGuard

    monkeypatch.setattr(settings, "llm_instruction_only", True)
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        assert payload["chat_template_kwargs"]["enable_thinking"] is False
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            },
        )

    client = LLMClient(
        api_key="synthetic",
        transport=httpx.MockTransport(handler),
        budget_guard=BudgetGuard(
            limit_usd="1", price_table={settings.model_reader: (Decimal("0.06"), Decimal("0.24"))}
        ),
    )
    kwargs = {
        "kind": "reader",
        "model": settings.model_reader,
        "system": "fixed",
        "user": "fixed",
        "schema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        "cache_parts": {"content_hash": "fixed", "prompt_id": "test", "prompt_version": "v1"},
        "conn": memory_db,
    }
    assert client.dispatch_json(**kwargs).data == {"ok": True}
    assert client.dispatch_json(**kwargs).cache_hit
    assert len(sent) == 1


def test_d5_corrected_jobs_are_explicit_and_do_not_replace_old_assets(memory_db):
    from probation.llm.catalog import resolve_job
    from probation.llm.consumers import offline_consumer
    from probation.llm.gateway import build_envelope
    from probation.llm.prompt_loader import load_prompt

    consumer = offline_consumer(memory_db)
    for job, fields in (
        ("writer.reply", {"incoming": "update", "examples": "", "style_facts": "unknown"}),
        ("reader.opportunity", {"subject": "public opportunity", "body": "public opportunity"}),
    ):
        old, new = (load_prompt(resolve_job(job, v)) for v in ("v1", "v2"))
        assert old.template_hash != new.template_hash
        assert old.schema_fingerprint == new.schema_fingerprint
        assert old.spec.max_tokens == new.spec.max_tokens
        assert consumer.context(job, fields).spec.prompt_version == "v1"
        assert consumer.context(job, fields, prompt_version="v2").spec.prompt_version == "v2"

        def envelope(asset):
            return build_envelope(
                asset=asset,
                model_id="configured",
                system=asset.system,
                user="fixed",
                purpose="test",
            )

        assert envelope(old).cache_key() != envelope(new).cache_key()
