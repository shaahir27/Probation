"""A cache hit is a semantic fact about the whole request, and an unusable row never buys a retry.

Authority: docs/wp3/WORK_PACKAGES.md P05.1-P05.4, W3-T21/T05/T08/T35. The gateway is the only path
a registered production job may take, so these tests also pin what it refuses before any send.
"""

import dataclasses
import json
import sqlite3
from decimal import Decimal
from typing import Any

import httpx
import pytest

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.llm.budget import BudgetGuard
from probation.llm.cache import semantic_content_hash
from probation.llm.catalog import resolve_job
from probation.llm.client import LLMClient
from probation.llm.gateway import JobFailure, JobGateway, build_envelope, transport_authority
from probation.llm.prompt_loader import load_prompt
from probation.llm.results import FailureCode

MODEL = settings.model_reader
READER_MAIL = resolve_job("reader.mail", "v3")
VALUES = {
    "subject": "Lab session moved",
    "sender_domain_class": "university",
    "body": "Thursday class is in room 204 instead.",
}
READING: dict[str, Any] = {
    "intent": "fyi",
    "asks_me_to_do_something": False,
    "has_deadline": False,
    "deadline_text": None,
    "money_involved": False,
    "urgency": 1,
    "formality": "neutral",
    "asks_for_personal_info": False,
    "looks_automated": False,
}


def _provider_answer(count: list[int], payload: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        count.append(1)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    return handler


def _gateway(
    memory_db: sqlite3.Connection, payload: dict[str, Any] | None = None
) -> tuple[JobGateway, list[int]]:
    count: list[int] = []
    guard = BudgetGuard(limit_usd="10.00", price_table={MODEL: (Decimal("0.06"), Decimal("0.24"))})
    client = LLMClient(
        api_key="test-key",
        budget_guard=guard,
        transport=httpx.MockTransport(_provider_answer(count, payload or READING)),
        max_retries=0,
        sleeper=lambda _seconds: None,
        clock=Clock(mode=ClockMode.REPLAY),
    )
    return JobGateway(client, conn=memory_db), count


def _authority(client: LLMClient, *, allow_live_dispatch: bool = True) -> Any:
    return transport_authority(client, allow_live_dispatch=allow_live_dispatch)


def test_every_semantic_input_participates_in_the_cache_identity() -> None:
    """W3-T21: system, user, schema, template, model, provider, limits, versions and purpose."""
    asset = load_prompt(READER_MAIL)
    base = build_envelope(
        asset=asset, model_id=MODEL, system="sys", user="usr", purpose="reader.mail"
    )
    stable = build_envelope(
        asset=asset, model_id=MODEL, system="sys", user="usr", purpose="reader.mail"
    )
    assert base.content_hash() == stable.content_hash()

    mutations = {
        "system": "sys with one more instruction",
        "user": "usr mentioning a different sender",
        "model_id": settings.model_writer,
        "provider": "another-provider",
        "template_hash": "0123456789abcdef",
        "schema_fingerprint": "fedcba9876543210",
        "context_version": "wp3-v2",
        "validator_version": "wp3-p05-v2",
        "max_tokens": base.max_tokens + 1,
        "temperature": 0.5,
        "purpose": "reader.opportunity",
        "prompt_version": "v4",
    }
    for field, value in mutations.items():
        changed = dataclasses.replace(base, **{field: value})
        assert changed.content_hash() != base.content_hash(), f"{field} is not in the identity"


def test_the_outer_key_stays_the_contracts_four_part_tuple() -> None:
    """I-16 is preserved: only content_hash becomes the complete semantic digest."""
    asset = load_prompt(READER_MAIL)
    envelope = build_envelope(
        asset=asset, model_id=MODEL, system="sys", user="usr", purpose="reader.mail"
    )
    digest = envelope.content_hash()
    assert digest == semantic_content_hash(dataclasses.asdict(envelope))
    assert len(digest) == 64


def test_an_identical_request_is_served_from_the_cache_without_a_send(
    memory_db: sqlite3.Connection,
) -> None:
    gateway, count = _gateway(memory_db)
    authority = _authority(gateway.client)
    first = gateway.dispatch(
        "reader.mail", "v3", values=VALUES, purpose="reader.mail", authority=authority
    )
    assert first.cache_hit is False and first.physical_attempts == 1 and first.cost_units > 0
    assert len(count) == 1

    second = gateway.dispatch(
        "reader.mail", "v3", values=VALUES, purpose="reader.mail", authority=authority
    )
    assert second.data == first.data
    assert second.cache_hit is True
    assert second.physical_attempts == 0 and second.cost_units == 0
    assert len(count) == 1, "a cache hit must not create a fake paid call"
    assert memory_db.execute("SELECT COUNT(*) FROM exposure_log").fetchone()[0] == 1


def test_changing_the_bounded_context_misses_and_never_rewrites_the_old_row(
    memory_db: sqlite3.Connection,
) -> None:
    """P05.2: incompatible history stays incompatible instead of being relabelled current."""
    gateway, count = _gateway(memory_db)
    authority = _authority(gateway.client)
    gateway.dispatch("reader.mail", "v3", values=VALUES, purpose="r", authority=authority)
    before = memory_db.execute(
        "SELECT cache_key, response_json, created_at, model_id FROM llm_cache"
    ).fetchall()

    changed = dict(VALUES, body="Friday class is cancelled.")
    outcome = gateway.dispatch(
        "reader.mail", "v3", values=changed, purpose="r", authority=authority
    )
    assert outcome.cache_hit is False
    assert len(count) == 2
    after = memory_db.execute(
        "SELECT cache_key, response_json, created_at, model_id FROM llm_cache"
    ).fetchall()
    assert len(after) == 2
    assert before == [row for row in after if row["cache_key"] == before[0]["cache_key"]]


def test_an_unregistered_production_job_is_refused_before_the_transport(
    memory_db: sqlite3.Connection,
) -> None:
    """W3-T05: a superseded asset and an invented job are both unavailable, not generic prompts."""
    gateway, count = _gateway(memory_db)
    authority = _authority(gateway.client)
    for prompt_id, version in (("reader.mail", "v1"), ("unknown.job", "v9")):
        with pytest.raises(JobFailure) as failure:
            gateway.dispatch(prompt_id, version, values=VALUES, purpose="r", authority=authority)
        assert failure.value.code is FailureCode.NOT_REGISTERED
    assert count == []


def test_missing_model_configuration_is_unavailable_not_defaulted(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W3-T22: an empty role setting denies; there is no writer/model_reader/Meta-Llama literal."""
    monkeypatch.setattr(settings, "model_reader", "")
    gateway, count = _gateway(memory_db)
    authority = _authority(gateway.client)
    with pytest.raises(JobFailure) as failure:
        gateway.dispatch("reader.mail", "v3", values=VALUES, purpose="r", authority=authority)
    assert failure.value.code is FailureCode.NOT_REGISTERED
    assert count == []


def test_dispatch_without_an_explicit_live_opt_in_makes_no_request(
    memory_db: sqlite3.Connection,
) -> None:
    """W3-T35: a key-shaped configuration is not authorization; the grant has to be explicit."""
    gateway, count = _gateway(memory_db)
    denied = _authority(gateway.client, allow_live_dispatch=False)
    assert denied.granted is False
    with pytest.raises(JobFailure) as failure:
        gateway.dispatch("reader.mail", "v3", values=VALUES, purpose="r", authority=denied)
    assert failure.value.code is FailureCode.NO_TRANSPORT_AUTHORITY
    assert count == []


def test_an_unauthorized_endpoint_is_refused_without_a_send(
    memory_db: sqlite3.Connection,
) -> None:
    """P05.9: no new destination. A client pointed elsewhere cannot borrow the grant."""
    gateway, count = _gateway(memory_db)
    authority = transport_authority(
        gateway.client, allow_live_dispatch=True, approved_base_url="https://api.test/v1"
    )
    assert authority.granted is False
    with pytest.raises(JobFailure) as failure:
        gateway.dispatch("reader.mail", "v3", values=VALUES, purpose="r", authority=authority)
    assert failure.value.code is FailureCode.NO_TRANSPORT_AUTHORITY
    assert count == []


def test_a_cache_row_without_accounting_provenance_denies_rather_than_resending(
    memory_db: sqlite3.Connection,
) -> None:
    """P05.3: an answer with no exposure record is a data-integrity finding, not free credit."""
    gateway, count = _gateway(memory_db)
    authority = _authority(gateway.client)
    gateway.dispatch("reader.mail", "v3", values=VALUES, purpose="r", authority=authority)
    assert memory_db.execute("SELECT COUNT(*) FROM exposure_log").fetchone()[0] == 1
    memory_db.execute("DELETE FROM exposure_log")  # test-only corruption of the provenance pair

    with pytest.raises(JobFailure) as failure:
        gateway.dispatch("reader.mail", "v3", values=VALUES, purpose="r", authority=authority)
    assert failure.value.code is FailureCode.CACHE_PROVENANCE
    assert len(count) == 1, "the private request is not re-sent to work around a broken row"


def test_the_gateway_resolves_the_model_from_settings_only(
    memory_db: sqlite3.Connection,
) -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(READING)}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    guard = BudgetGuard(limit_usd="10.00", price_table={MODEL: (Decimal("0.06"), Decimal("0.24"))})
    client = LLMClient(
        api_key="test-key",
        budget_guard=guard,
        transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
    )
    gateway = JobGateway(client, conn=memory_db)
    outcome = gateway.dispatch(
        "reader.mail",
        "v3",
        values=VALUES,
        purpose="r",
        authority=transport_authority(client, allow_live_dispatch=True),
    )
    assert sent[0]["model"] == settings.model_reader
    assert outcome.provenance.model_id == settings.model_reader
    assert outcome.provenance.prompt_id == "reader.mail"
    assert outcome.provenance.template_hash == load_prompt(READER_MAIL).template_hash
    assert outcome.provenance.transport == "live"
    assert outcome.data == READING


def test_a_contextual_check_reaches_the_final_gate_as_a_typed_failure(
    memory_db: sqlite3.Connection,
) -> None:
    """P05.1: schema-valid data is still subject to the caller's contextual rules."""

    def conflict(_data: Any) -> tuple[FailureCode, str] | None:
        return FailureCode.HEADER_CONFLICT, "authoritative facts contradict the form"

    gateway, count = _gateway(memory_db)
    with pytest.raises(JobFailure) as failure:
        gateway.dispatch(
            "reader.mail",
            "v3",
            values=VALUES,
            purpose="r",
            authority=_authority(gateway.client),
            contextual=conflict,
        )
    assert failure.value.code is FailureCode.HEADER_CONFLICT
    assert len(count) == 1
    assert memory_db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 1


def test_a_form_that_is_not_the_current_strict_model_is_refused(
    memory_db: sqlite3.Connection,
) -> None:
    """P05.1: a deadline text with no deadline is not a usable reader form, however it parses."""
    broken = dict(READING, has_deadline=False, deadline_text="friday")
    gateway, count = _gateway(memory_db, broken)
    with pytest.raises(JobFailure) as failure:
        gateway.dispatch(
            "reader.mail", "v3", values=VALUES, purpose="r", authority=_authority(gateway.client)
        )
    assert failure.value.code is FailureCode.INVALID_OUTPUT
    assert len(count) == 3  # the whole bounded tree re-asks, then still refuses
    assert memory_db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0
