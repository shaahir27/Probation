"""Only a classified transient failure may be retried, and only a provider format rejection may fall back.

Authority: docs/wp3/WORK_PACKAGES.md P05.5-P05.8, W3-T23. Fake transport only, and every test
here asserts an exact physical send count, because an unauthorized extra send is the defect.
Timing is injected: no test sleeps against the wall clock, and no wall-clock value is produced.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.llm.budget import BudgetGuard
from probation.llm.catalog import JobNotRegistered, model_for_job, resolve_job
from probation.llm.client import LLMClient
from probation.llm.errors import LLMValidationError, TransportFailure
from probation.llm.results import FailureCode

MODEL = "nvidia/priced"
RATES = {MODEL: (Decimal("0.06"), Decimal("0.24"))}
OPERATIONAL_NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)
FORMAT_REJECTION = {
    "error": {
        "message": "response_format of type json_schema is not supported by this model",
        "code": "unsupported_response_format",
    }
}


def _ok(content: object, **extra: Any) -> httpx.Response:
    choice: dict[str, Any] = {
        "message": {"content": content if isinstance(content, str) else json.dumps(content)}
    }
    choice.update(extra)
    return httpx.Response(
        200,
        json={
            "choices": [choice],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10},
        },
    )


class Recorder:
    """Counts sends and waits instead of sleeping, so a count is an exact assertion."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.waits: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)

    def formats(self) -> list[Any]:
        return [p.get("response_format", {}).get("type") for p in self.payloads]


def _scripted(waits: Recorder, responses: list[httpx.Response]):
    """One scripted answer per physical send: the send count becomes the test's own evidence."""
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        waits.payloads.append(json.loads(request.content.decode("utf-8")))
        if not remaining:
            raise AssertionError("the client sent more physical requests than were authorized")
        return remaining.pop(0)

    return handler


def _client(
    handler,
    *,
    retries: int = 0,
    waits: Recorder | None = None,
    operational_clock: Clock | None = None,
    **kwargs: Any,
) -> tuple[LLMClient, BudgetGuard, Recorder]:
    guard = BudgetGuard(limit_usd="10.00", price_table=RATES)
    waits = waits or Recorder()
    client = LLMClient(
        api_key="test-key",
        budget_guard=guard,
        transport=httpx.MockTransport(handler),
        max_retries=retries,
        sleeper=waits.sleep,
        operational_clock=operational_clock
        or Clock(mode=ClockMode.REPLAY, initial_time=OPERATIONAL_NOW),
        **kwargs,
    )
    return client, guard, waits


def _args(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "reader",
        "model": MODEL,
        "system": "System",
        "user": "Email text",
        "schema": {"type": "object"},
        "cache_parts": {"content_hash": "hash_classification"},
        "max_tokens": 64,
    }
    base.update(overrides)
    return base


def test_an_auth_rejection_sends_once_and_never_starts_a_format_fallback() -> None:
    """P05.5: 401 is an authority failure, not evidence that the model dislikes a response format."""
    waits = Recorder()
    handler = _scripted(
        waits, [httpx.Response(401, json={"error": {"message": "Invalid API key"}})]
    )

    client, guard, _ = _client(handler)
    with pytest.raises(TransportFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.AUTH
    assert len(waits.payloads) == 1
    assert guard.spent_units > 0 and guard.held_units == 0


def test_a_forbidden_response_is_classified_as_auth_not_format() -> None:
    waits = Recorder()
    handler = _scripted(
        waits, [httpx.Response(403, json={"error": {"message": "Model access is not granted"}})]
    )

    client, _, _ = _client(handler)
    with pytest.raises(TransportFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.AUTH
    assert len(waits.payloads) == 1


def test_an_unknown_model_denies_without_burning_the_ladder() -> None:
    """W3-T23: an endpoint/model failure must not be re-labelled as an unsupported format."""
    waits = Recorder()
    handler = _scripted(
        waits, [httpx.Response(404, json={"error": {"message": "model not found"}})]
    )

    client, _, _ = _client(handler)
    with pytest.raises(TransportFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.UNKNOWN_MODEL
    assert len(waits.payloads) == 1


def test_only_a_provider_unsupported_format_rejection_enables_json_mode_fallback() -> None:
    """P05.5: the fallback is authorized by the provider's own rejection, and nothing else."""
    waits = Recorder()
    handler = _scripted(
        waits, [httpx.Response(400, json=FORMAT_REJECTION), _ok({"verdict": "valid"})]
    )

    client, _, _ = _client(handler, waits=waits)
    assert client.chat_json(**_args())["verdict"] == "valid"
    assert waits.formats() == ["json_schema", "json_object"]


def test_a_bad_request_without_a_format_signature_does_not_fall_back() -> None:
    """A generic 400 is a transport failure: re-sending the same private request costs money."""
    waits = Recorder()
    handler = _scripted(waits, [httpx.Response(400, json={"error": {"message": "bad request"}})])

    client, _, _ = _client(handler, waits=waits)
    with pytest.raises(TransportFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.TRANSPORT
    assert len(waits.payloads) == 1


def test_transient_statuses_retry_and_the_exhausted_set_denies_the_further_send() -> None:
    """P05.8: retries are bounded, and each answered-for send is booked before the next one."""
    waits = Recorder()
    handler = _scripted(
        waits,
        [
            httpx.Response(503, json={"error": {"message": "overloaded"}}),
            httpx.Response(500, text="boom"),
            _ok({"verdict": "valid"}),
        ],
    )

    client, guard, _ = _client(handler, waits=waits, retries=2)
    assert client.chat_json(**_args())["verdict"] == "valid"
    assert len(waits.payloads) == 3
    assert guard.held_units == 0


def test_exhausted_transient_retries_end_the_request_with_a_typed_failure() -> None:
    waits = Recorder()
    handler = _scripted(
        waits,
        [httpx.Response(503, json={"error": {"message": "overloaded"}})] * 3,
    )

    client, _, _ = _client(handler, waits=waits, retries=2)
    with pytest.raises(TransportFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.TRANSPORT
    assert len(waits.payloads) == 3  # the first send plus two retries


def test_numeric_retry_after_is_honoured_with_injected_timing() -> None:
    waits = Recorder()
    handler = _scripted(
        waits,
        [httpx.Response(429, headers={"Retry-After": "7"}), _ok({"verdict": "valid"})],
    )

    client, _, _ = _client(handler, waits=waits, retries=1)
    assert client.chat_json(**_args())["verdict"] == "valid"
    assert waits.waits == [7.0]


def test_http_date_retry_after_is_measured_against_the_injected_operational_clock() -> None:
    """W3-D07: an operational deadline is resolved by the injected Clock, never by replay time."""
    waits = Recorder()
    clock = Clock(mode=ClockMode.REPLAY, initial_time=OPERATIONAL_NOW)
    deadline = format_datetime(OPERATIONAL_NOW + timedelta(seconds=20), usegmt=True)
    handler = _scripted(
        waits, [httpx.Response(429, headers={"Retry-After": deadline}), _ok({"verdict": "valid"})]
    )

    client, _, _ = _client(handler, waits=waits, retries=1, operational_clock=clock)
    assert client.chat_json(**_args())["verdict"] == "valid"
    assert waits.waits == [20.0]


def test_a_malformed_retry_after_falls_back_to_the_bounded_local_backoff() -> None:
    waits = Recorder()
    handler = _scripted(
        waits,
        [httpx.Response(429, headers={"Retry-After": "soon please"}), _ok({"verdict": "valid"})],
    )

    client, _, _ = _client(handler, waits=waits, retries=1)
    assert client.chat_json(**_args())["verdict"] == "valid"
    assert waits.waits == [0.5]


def test_an_extreme_retry_after_denies_the_wait_instead_of_blocking_the_job() -> None:
    """P05.8: a bound is a bound. A fifteen-day hint ends this request, it is not obeyed."""
    waits = Recorder()
    handler = _scripted(waits, [httpx.Response(429, headers={"Retry-After": "1296000"})])

    client, guard, _ = _client(handler, waits=waits, retries=3)
    with pytest.raises(TransportFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.ATTEMPT_BUDGET_EXHAUSTED
    assert len(waits.payloads) == 1
    assert waits.waits == []
    assert guard.spent_units > 0 and guard.held_units == 0


def test_a_connect_timeout_retries_only_the_attempt_that_never_reached_the_socket() -> None:
    """P05.8: the intended ConnectTimeout handling, with nothing charged for an unsent request."""
    waits = Recorder()
    seen = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        waits.payloads.append(json.loads(request.content.decode("utf-8")))
        raise httpx.ConnectTimeout("connect timed out")

    client, guard, _ = _client(handler, waits=waits, retries=1)
    with pytest.raises(httpx.ConnectTimeout):
        client.chat_json(**_args())
    assert seen == 2
    assert waits.waits == [0.5]
    assert guard.spent_units == 0 and guard.held_units == 0


def test_retry_jitter_is_seeded_and_therefore_reproducible() -> None:
    """P05.8: jitter comes from an explicit seed, so a retry schedule stays deterministic."""
    recorded: list[list[float]] = []
    for _ in range(2):
        waits = Recorder()
        handler = _scripted(
            waits,
            [httpx.Response(500, json={"error": {"message": "boom"}})] * 3,
        )
        client, _, _ = _client(handler, waits=waits, retries=2, jitter_s=0.25, jitter_seed=7)
        with pytest.raises(TransportFailure):
            client.chat_json(**_args())
        recorded.append(waits.waits)

    assert recorded[0] == recorded[1]
    assert len(recorded[0]) == 2
    assert all(0.5 <= wait <= 1.25 for wait in recorded[0])


def test_the_attempt_tree_is_bounded_across_every_stage() -> None:
    """P05.6: the whole send tree has a declared ceiling, so retries cannot outrun it."""
    waits = Recorder()
    handler = _scripted(
        waits,
        [httpx.Response(503, json={"error": {"message": "overloaded"}})] * 3,
    )

    client, guard, _ = _client(handler, waits=waits, retries=2, max_physical_attempts=2)
    assert client.default_attempt_ceiling == 9  # three stages, three sends each
    with pytest.raises(TransportFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.ATTEMPT_BUDGET_EXHAUSTED
    assert len(waits.payloads) == 2
    assert guard.held_units == 0


def test_no_legacy_or_literal_model_alias_is_resolvable() -> None:
    """P05.9/W3-T22: a superseded asset, an unknown job and an unconfigured role all deny."""
    with pytest.raises(JobNotRegistered):
        resolve_job("reader.mail", "v1")  # superseded by v3: not a job, so it cannot dispatch
    with pytest.raises(JobNotRegistered):
        resolve_job("unknown.job", "v9")

    class _NoReaderModel:
        model_reader = ""
        model_writer = ""
        model_wording = ""
        model_exam_edits = ""
        model_synth = ""
        model_baseline = ""

    with pytest.raises(JobNotRegistered):
        model_for_job(resolve_job("reader.mail", "v3"), _NoReaderModel())  # type: ignore[arg-type]


def test_a_failed_attempt_leaves_no_cache_entry(memory_db: sqlite3.Connection) -> None:
    """P05.3: nothing unusable is persisted, so a later run cannot reuse a failure as an answer."""
    waits = Recorder()
    handler = _scripted(
        waits,
        [httpx.Response(400, json=FORMAT_REJECTION)] * 2 + [httpx.Response(400, text="still bad")],
    )

    client, _, _ = _client(handler, waits=waits)
    with pytest.raises(LLMValidationError):
        client.chat_json(**_args(conn=memory_db, situation_id="sit_x"))
    assert memory_db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0
    assert memory_db.execute("SELECT COUNT(*) FROM exposure_log").fetchone()[0] == 0
