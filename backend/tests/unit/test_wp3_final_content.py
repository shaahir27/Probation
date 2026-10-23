"""Only a nonempty final message is an answer, and a terminal model state is not a paid ladder.

Authority: docs/wp3/WORK_PACKAGES.md P05.6-P05.7, W3-T24. A reasoning channel, a refusal, a tool
call or a truncated output is not a formatting accident to re-bill around, and none of them may
reach the cache or a feature row as a success.
"""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.llm.budget import BudgetGuard
from probation.llm.client import LLMClient
from probation.llm.errors import LLMValidationError, OutputFailure
from probation.llm.results import FailureCode

MODEL = "nvidia/priced"
RATES = {MODEL: (Decimal("0.06"), Decimal("0.24"))}
FENCE = "`" * 3
THOUGHT = "<thought>working on it</thought>\n" + json.dumps({"verdict": "valid"})
SCHEMA = {
    "type": "object",
    "required": ["verdict"],
    "properties": {"verdict": {"type": "string"}},
}
VALID = {"verdict": "valid"}
VALID_JSON = json.dumps(VALID)


def _response(*, message: dict[str, Any], finish: str | None = None) -> httpx.Response:
    choice: dict[str, Any] = {"message": message}
    if finish is not None:
        choice["finish_reason"] = finish
    return httpx.Response(
        200,
        json={"choices": [choice], "usage": {"prompt_tokens": 40, "completion_tokens": 10}},
    )


def _fenced(payload: str, *, lang: str = "json") -> str:
    return f"{FENCE}{lang}\n{payload}\n{FENCE}"


def _client(handler: Callable[[int], httpx.Response], *, retries: int = 0):
    guard = BudgetGuard(limit_usd="10.00", price_table=RATES)
    sent: list[dict[str, Any]] = []

    def recording(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content.decode("utf-8")))
        return handler(len(sent))

    client = LLMClient(
        api_key="test-key",
        budget_guard=guard,
        transport=httpx.MockTransport(recording),
        max_retries=retries,
        sleeper=lambda _seconds: None,
        clock=Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 10, 23, 12, 0, tzinfo=UTC)),
    )
    return client, guard, sent


def _args(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "reader",
        "model": MODEL,
        "system": "System",
        "user": "Email text",
        "schema": SCHEMA,
        "cache_parts": {"content_hash": "hash_content_rules"},
        "max_tokens": 64,
    }
    base.update(overrides)
    return base


def test_a_plain_json_object_is_accepted() -> None:
    client, _, sent = _client(lambda _n: _response(message={"content": VALID_JSON}))
    assert client.chat_json(**_args()) == VALID
    assert len(sent) == 1


def test_a_whole_fenced_block_is_unwrapped_and_a_prelude_is_not_scraped() -> None:
    """P05.7: fence extraction is documented and narrow, not a brace search across the reply."""
    client, _, _ = _client(lambda _n: _response(message={"content": _fenced(VALID_JSON)}))
    assert client.chat_json(**_args()) == VALID

    prelude = f"Certainly. The result is {VALID_JSON} and that is final."
    client, _, sent = _client(lambda _n: _response(message={"content": prelude}))
    with pytest.raises(OutputFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.INVALID_OUTPUT
    assert len(sent) == 3  # structured, JSON-only and exactly one repair: the whole tree


def test_a_closed_reasoning_block_is_stripped_but_an_unterminated_one_is_not_an_answer() -> None:
    client, _, _ = _client(lambda _n: _response(message={"content": THOUGHT}))
    assert client.chat_json(**_args()) == VALID

    dangling = "<thought>working " + VALID_JSON
    client, _, _ = _client(lambda _n: _response(message={"content": dangling}))
    with pytest.raises(OutputFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.INVALID_OUTPUT


def test_a_reasoning_channel_is_never_accepted_as_the_final_answer(
    memory_db: sqlite3.Connection,
) -> None:
    reasoning = {"content": "", "reasoning_content": VALID_JSON}
    client, _, sent = _client(lambda _n: _response(message=reasoning))
    with pytest.raises(OutputFailure) as failure:
        client.chat_json(**_args(conn=memory_db, cache_parts={"content_hash": "hash_reasoning"}))
    assert failure.value.code is FailureCode.REASONING_ONLY
    assert len(sent) == 3
    assert memory_db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0

    client, _, sent = _client(lambda _n: _response(message=reasoning))
    args = _args()
    args.pop("schema")
    args["cache_parts"] = {"content_hash": "hash_reasoning_text"}
    with pytest.raises(OutputFailure) as failure:
        client.chat_text(**args)
    assert failure.value.code is FailureCode.REASONING_ONLY
    assert len(sent) == 1


def test_empty_or_absent_final_content_is_denied() -> None:
    client, _, _ = _client(lambda _n: _response(message={"content": "   "}))
    with pytest.raises(OutputFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.EMPTY_CONTENT


def test_a_response_without_choices_is_not_an_answer() -> None:
    def handler(_n: int) -> httpx.Response:
        body = {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 0}}
        return httpx.Response(200, json=body)

    client, _, _ = _client(handler)
    with pytest.raises(OutputFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.INVALID_OUTPUT


@pytest.mark.parametrize(
    ("finish", "message", "code"),
    [
        ("length", {"content": VALID_JSON}, FailureCode.TRUNCATED),
        ("content_filter", {"content": VALID_JSON}, FailureCode.REFUSAL),
        ("stop", {"content": "", "refusal": "I cannot help with that."}, FailureCode.REFUSAL),
        (
            "tool_calls",
            {"content": VALID_JSON, "tool_calls": [{"id": "call_1"}]},
            FailureCode.TOOL_CALLS,
        ),
    ],
)
def test_a_terminal_model_state_ends_the_request_without_another_send(
    finish: str, message: dict[str, Any], code: FailureCode
) -> None:
    """P05.6: a refusal, a tool call or a cut-off output is a result, not a formatting slip."""
    client, guard, sent = _client(lambda _n: _response(message=message, finish=finish))
    with pytest.raises(OutputFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is code
    assert len(sent) == 1
    assert guard.spent_units > 0 and guard.held_units == 0


def test_json_that_is_not_an_object_is_denied() -> None:
    client, _, _ = _client(lambda _n: _response(message={"content": json.dumps([VALID])}))
    with pytest.raises(OutputFailure) as failure:
        client.chat_json(**_args())
    assert failure.value.code is FailureCode.INVALID_OUTPUT


def test_a_schema_shaped_answer_is_still_revalidated_before_use() -> None:
    """P05.1: the compiled wire schema is re-checked locally; provider strictness is not proof."""
    client, _, sent = _client(lambda _n: _response(message={"content": json.dumps({"verdict": 7})}))
    with pytest.raises(LLMValidationError):
        client.chat_json(**_args())
    assert len(sent) == 3
