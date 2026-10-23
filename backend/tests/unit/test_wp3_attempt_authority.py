"""Every physical attempt needs its own authorization, and none of them is free on failure.

Authority: docs/wp3/WORK_PACKAGES.md P04.4-P04.6, W3-T15/T16/T17 (the parts reachable without
the durable store that W3-D03 still gates). Fake transport only; no provider is contacted.
"""

import json
import sqlite3
from decimal import Decimal

import httpx
import pytest

from probation.llm.budget import BudgetExceeded, BudgetGuard, cost_units, input_token_bound
from probation.llm.client import REPAIR_INSTRUCTION, LLMClient, LLMValidationError, json_mode_system

MODEL = "nvidia/priced"
TABLE = {MODEL: (Decimal("0.06"), Decimal("0.24"))}
SYSTEM = "Validator"
USER = "Validate this item"
MAX_TOKENS = 64
SCHEMA: dict[str, object] = {"type": "object"}

# Each rung of the ladder egresses its own text, so each one is authorized against its own worst
# case: the JSON-only stage carries the schema it was refused, and the repair carries both.
FALLBACK_SYSTEM = json_mode_system(SYSTEM, SCHEMA)
BOUND_IN = input_token_bound(len(SYSTEM) + len(USER))
BOUND = cost_units(BOUND_IN, MAX_TOKENS, *TABLE[MODEL])
STAGE_BOUNDS = (
    cost_units(BOUND_IN, MAX_TOKENS, *TABLE[MODEL]),
    cost_units(input_token_bound(len(FALLBACK_SYSTEM) + len(USER)), MAX_TOKENS, *TABLE[MODEL]),
    cost_units(
        input_token_bound(len(FALLBACK_SYSTEM) + len(USER) + len(REPAIR_INSTRUCTION)),
        MAX_TOKENS,
        *TABLE[MODEL],
    ),
)
LADDER_UNITS = sum(STAGE_BOUNDS)

# docs/wp3/WORK_PACKAGES.md P05.5: only a provider-specific rejection of the response format may
# start the next format, so a ladder test has to be given one rather than a bare status code.
FORMAT_REJECTION = {
    "error": {
        "message": "response_format of type json_schema is not supported by this model",
        "code": "unsupported_response_format",
    }
}


def _ok(content: object, *, usage: dict[str, int] | None = None) -> httpx.Response:
    body: dict[str, object] = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(content) if not isinstance(content, str) else content
                }
            }
        ]
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def _client(handler, *, limit: str = "1.00", retries: int = 0) -> tuple[LLMClient, BudgetGuard]:
    guard = BudgetGuard(limit_usd=limit, price_table=TABLE)
    client = LLMClient(
        api_key="test-key",
        budget_guard=guard,
        transport=httpx.MockTransport(handler),
        max_retries=retries,
    )
    return client, guard


def _json_args(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "reader",
        "model": MODEL,
        "system": SYSTEM,
        "user": USER,
        "schema": SCHEMA,
        "cache_parts": {"content_hash": "hash_attempt_authority"},
        "max_tokens": MAX_TOKENS,
    }
    base.update(kwargs)
    return base


def test_an_unpriced_model_is_denied_before_any_socket_is_opened() -> None:
    """W3-T16: no verified price means no dispatch, never a cheap fallback tier."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _ok({"verdict": "valid"}, usage={"prompt_tokens": 10, "completion_tokens": 5})

    client, _ = _client(handler)
    args = _json_args()
    args["model"] = "nvidia/unlisted"
    with pytest.raises(BudgetExceeded) as denial:
        client.chat_json(**args)  # type: ignore[arg-type]
    assert denial.value.code == "price_missing"
    assert calls == []


def test_failed_attempts_are_charged_so_totals_count_physical_attempts(
    memory_db: sqlite3.Connection,
) -> None:
    """W3-T15: the ladder sends three requests, so three attempts are booked."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json=FORMAT_REJECTION)

    client, guard = _client(handler)
    with pytest.raises(LLMValidationError):
        client.chat_json(**_json_args(conn=memory_db, situation_id="sit_a"))  # type: ignore[arg-type]
    assert calls == 3
    assert guard.held_units == 0
    assert guard.spent_units == LADDER_UNITS
    assert memory_db.execute("SELECT COUNT(*) FROM exposure_log").fetchone()[0] == 0


def test_absent_usage_is_charged_and_recorded_at_the_bound_not_at_an_invented_number(
    memory_db: sqlite3.Connection,
) -> None:
    """Regression: a missing usage block used to be recorded as 800 in / 150 out."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok({"verdict": "valid"})

    client, guard = _client(handler)
    client.chat_json(**_json_args(conn=memory_db, situation_id="sit_b"))  # type: ignore[arg-type]

    row = memory_db.execute("SELECT tokens_in, tokens_out, cost_usd FROM exposure_log").fetchone()
    assert (row["tokens_in"], row["tokens_out"]) == (BOUND_IN, MAX_TOKENS)
    assert (row["tokens_in"], row["tokens_out"]) != (800, 150)
    assert guard.spent_units == BOUND
    assert Decimal(str(row["cost_usd"])) > 0


def test_reported_usage_is_charged_exactly_and_a_larger_charge_is_not_hidden(
    memory_db: sqlite3.Connection,
) -> None:
    """The provider's own count wins, even when it exceeds what this process reserved."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok({"verdict": "valid"}, usage={"prompt_tokens": 900, "completion_tokens": 40})

    client, guard = _client(handler, limit="1.00")
    client.chat_json(**_json_args(conn=memory_db))  # type: ignore[arg-type]
    reported = cost_units(900, 40, *TABLE[MODEL])
    assert reported > BOUND  # the answer is longer than the reservation allowed for
    assert guard.spent_units == reported
    assert guard.held_units == 0
    row = memory_db.execute("SELECT tokens_in, tokens_out FROM exposure_log").fetchone()
    assert (row["tokens_in"], row["tokens_out"]) == (900, 40)


def test_each_attempt_in_the_ladder_needs_its_own_authorization() -> None:
    """A cap that affords one physical request must deny the fallback request, not allow it."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json=FORMAT_REJECTION)

    limit = f"{Decimal(BOUND) * 2 - Decimal(1)}e-8"
    client, guard = _client(handler, limit=limit)
    with pytest.raises(BudgetExceeded) as denial:
        client.chat_json(**_json_args())  # type: ignore[arg-type]
    assert denial.value.code == "cap_exceeded"
    assert calls == 1, "the second format is denied before its bytes are built or sent"
    assert guard.spent_units == BOUND  # only the first, already-answered-for attempt is booked


def test_a_request_that_never_left_the_process_is_not_billed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client, guard = _client(handler)
    with pytest.raises(httpx.ConnectError):
        client.chat_json(**_json_args())  # type: ignore[arg-type]
    assert guard.spent_units == 0
    assert guard.held_units == 0


def test_a_timeout_after_dispatch_stays_charged() -> None:
    """W3-T17: a timed-out attempt may already be billed, so time cannot make it free."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    client, guard = _client(handler)
    with pytest.raises(httpx.ReadTimeout):
        client.chat_json(**_json_args())  # type: ignore[arg-type]
    assert guard.held_units == 0
    assert guard.spent_units == BOUND


def test_text_generation_counts_its_attempt_and_its_absent_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok("Dear Ramesh, noted.")

    client, guard = _client(handler)
    args = _json_args()
    args.pop("schema")
    args["cache_parts"] = {"content_hash": "hash_text_authority"}
    text = client.chat_text(**args)  # type: ignore[arg-type]
    assert text.startswith("Dear")
    assert guard.spent_units == BOUND and guard.held_units == 0
