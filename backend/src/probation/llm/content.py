"""Read exactly one answer out of a provider response, and say why the rest is not one.

Authority: docs/CONTRACT.md invariants I-1, I-3, I-14; docs/wp3/WORK_PACKAGES.md P05.6-P05.7.

A completion is untrusted text. This module never searches it for a plausible object: the final
message must *be* the answer, or the request has no answer. That is what stops a prose preamble
that happens to contain a brace from becoming a stored feature, and what stops a reasoning
channel, a tool call, a refusal or a cut-off output from being re-billed as a formatting slip.
"""

import json
import re
from typing import Any, NoReturn, cast

import httpx
from pydantic import TypeAdapter, ValidationError

from probation.llm.errors import OutputFailure
from probation.llm.jobs import validate_job_output
from probation.llm.results import FailureCode
from probation.llm.schema import validate_json_schema

# Only these tags are stripped, only when closed, and only before the answer is read.
THOUGHT_TAGS = ("think", "thought")

# A provider that stopped for a policy or length reason has answered. Re-asking costs money
# and cannot change that verdict, so these codes end the request instead of the ladder.
TERMINAL_OUTPUT_CODES = frozenset(
    {FailureCode.TRUNCATED, FailureCode.REFUSAL, FailureCode.TOOL_CALLS}
)

_WHOLE_FENCE = re.compile(r"\A\s*```(?:[A-Za-z0-9_+-]+)?\s*\n(?P<body>.*?)\n\s*```\s*\Z", re.DOTALL)


def _deny(code: FailureCode, reason: str) -> NoReturn:
    raise OutputFailure(reason, code=code)


def _choice(response: httpx.Response) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        body = response.json()
    except ValueError:
        _deny(FailureCode.INVALID_OUTPUT, "response body is not JSON")
    if not isinstance(body, dict):
        _deny(FailureCode.INVALID_OUTPUT, "response body is not an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        _deny(FailureCode.INVALID_OUTPUT, "response carries no completion choice")
    first = choices[0]
    if not isinstance(first, dict):
        _deny(FailureCode.INVALID_OUTPUT, "completion choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        _deny(FailureCode.INVALID_OUTPUT, "completion carries no message")
    return cast("dict[str, Any]", first), cast("dict[str, Any]", message)


def _final_text(choice: dict[str, Any], message: dict[str, Any]) -> str:
    """The nonempty final message content, or the typed reason this response has no answer."""
    if message.get("tool_calls"):
        _deny(FailureCode.TOOL_CALLS, "model asked for a tool call instead of an answer")
    finish = choice.get("finish_reason")
    if finish == "length":
        _deny(FailureCode.TRUNCATED, "model output was cut off by its token limit")
    if finish == "content_filter":
        _deny(FailureCode.REFUSAL, "model output was withheld by the provider filter")
    if isinstance(message.get("refusal"), str) and message["refusal"].strip():
        _deny(FailureCode.REFUSAL, "model refused to answer")
    raw = message.get("content")
    reasoning = message.get("reasoning_content")
    has_reasoning = isinstance(reasoning, str) and bool(reasoning.strip())
    if not isinstance(raw, str) or not raw.strip():
        if has_reasoning:
            # A chain of thought is not an answer. Accepting it would put private reasoning
            # into a feature row and record a paid call that never produced a result.
            _deny(FailureCode.REASONING_ONLY, "model filled the reasoning channel only")
        _deny(FailureCode.EMPTY_CONTENT, "model returned no final content")
    return _strip_thought_blocks(raw.strip())


def _strip_thought_blocks(text: str) -> str:
    cleaned = text
    for tag in THOUGHT_TAGS:
        open_tag, close_tag = f"<{tag}>", f"</{tag}>"
        span = re.compile(rf"{re.escape(open_tag)}.*?{re.escape(close_tag)}", re.DOTALL)
        cleaned = span.sub("", cleaned)
        if open_tag in cleaned or close_tag in cleaned:
            _deny(FailureCode.INVALID_OUTPUT, f"model left a {tag} block that never closed")
    return cleaned.strip()


def _unwrap_fence(text: str) -> str:
    """Accept a fence only when the whole message is that one block.

    The previous parser sliced from the first brace to the last one anywhere in the reply, so
    "The result is {"a":1} and that is final" became a JSON object. Narrow extraction, documented
    here, is the whole rule: nothing is scraped out of surrounding prose.
    """
    match = _WHOLE_FENCE.match(text)
    return match.group("body").strip() if match else text


def parse_json(
    response: httpx.Response,
    *,
    schema: dict[str, Any],
    adapter: TypeAdapter[Any] | None = None,
    prompt_id: str,
    prompt_version: str,
) -> dict[str, Any]:
    """Strict final-content JSON, revalidated locally against the wire schema and the job model."""
    choice, message = _choice(response)
    text = _final_text(choice, message)
    candidate = _unwrap_fence(text)
    try:
        parsed = json.loads(candidate)
    except ValueError:
        _deny(FailureCode.INVALID_OUTPUT, "final content is not a JSON document")
    if not isinstance(parsed, dict):
        _deny(FailureCode.INVALID_OUTPUT, "final content is not a JSON object")
    if adapter is not None:
        try:
            adapter.validate_python(parsed, strict=True)
        except ValidationError:
            _deny(FailureCode.INVALID_OUTPUT, "answer violates the compiled schema")
    else:
        valid, _ = validate_json_schema(parsed, schema)
        if not valid:
            _deny(FailureCode.INVALID_OUTPUT, "answer violates the request schema")
    if not validate_job_output(parsed, prompt_id, prompt_version):
        _deny(FailureCode.INVALID_OUTPUT, "answer violates the registered job model")
    return cast("dict[str, Any]", parsed)


def parse_text(response: httpx.Response) -> str:
    """Strict final content for a prose job, with the same terminal-state rules."""
    choice, message = _choice(response)
    return _final_text(choice, message)


def safe_content(response: httpx.Response) -> str:
    """The final content if this response has one, else nothing at all.

    Used only to show the model its own rejected answer in the single authorized repair. A
    reasoning channel, a refusal or a truncated turn is not replayed, so none of them can be
    carried forward into a feature row by way of the next request.
    """
    try:
        choice, message = _choice(response)
        return _final_text(choice, message)
    except OutputFailure:
        return ""


__all__ = [
    "TERMINAL_OUTPUT_CODES",
    "THOUGHT_TAGS",
    "parse_json",
    "parse_text",
    "safe_content",
]
