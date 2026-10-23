"""Typed failure classification for the LLM transport.

Authority: docs/CONTRACT.md invariants I-3 and I-15, docs/wp3/WORK_PACKAGES.md P05.5 and P05.8.

A provider's own message body is untrusted text. It is examined here only to choose a code, and
is never returned, logged, cached or re-sent: what travels further is a `FailureCode` and a short
safe reason written by this program. Keeping the classification in one place is what stops a 401
from being re-labelled as "this model dislikes structured output" and starting extra paid calls.
"""

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from probation.llm.results import FailureCode

# Reviewed bounds. A longer hint is a denial, not a schedule to obey.
INITIAL_BACKOFF_S = 0.5
BACKOFF_FACTOR = 2.0
MAX_RETRY_AFTER_S = 300.0
MAX_TREE_STAGES = 3  # structured, JSON-only and one repair: see P05.6

# Statuses this program is allowed to re-send for. Anything else is terminal.
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Narrow, explicitly documented provider signatures. Both halves must appear for a format
# rejection, because "unsupported" on its own appears in messages that are not about formats.
_FORMAT_TOKENS = ("response_format", "json_schema", "json schema", "structured output")
_REJECT_TOKENS = ("not supported", "unsupported", "does not support", "is not available")
_MODEL_TOKENS = ("model not found", "no such model", "does not exist", "unknown model")


class LLMValidationError(Exception):
    """A safe, machine-readable LLM failure.

    `code` is the contract-level statement of what happened and `safe_reason` is text this
    program wrote, never a provider body. Every caller that guards an LLM call catches this
    class and fails closed; the two subclasses say which half of the request failed.
    """

    def __init__(self, safe_reason: str, *, code: FailureCode = FailureCode.INVALID_OUTPUT) -> None:
        super().__init__(f"{code.value}: {safe_reason}")
        self.code = code
        self.safe_reason = safe_reason


class TransportFailure(LLMValidationError):
    """The request itself failed: authority, endpoint, model, transport or the attempt ceiling."""


class OutputFailure(LLMValidationError):
    """A request came back and its final message is not usable as an answer."""


def error_text(response: httpx.Response) -> str:
    """Extract the provider's error string for classification only; never returned or logged."""
    try:
        body: Any = response.json()
    except ValueError:
        return _clip(response.text)
    if not isinstance(body, dict):
        return _clip(str(body))
    error = body.get("error", body)
    if isinstance(error, dict):
        parts = [str(error.get(key, "")) for key in ("code", "type", "message")]
        return _clip(" ".join(part for part in parts if part))
    return _clip(str(error))


def _clip(value: str) -> str:
    return value[:500].lower()


def classify_response(response: httpx.Response) -> FailureCode | None:
    """One status, one code. A code that is not transient cannot be retried or re-formatted."""
    status = response.status_code
    if 200 <= status < 300:
        return None
    if status in (401, 403):
        return FailureCode.AUTH
    if status == 404:
        return FailureCode.UNKNOWN_MODEL
    text = error_text(response)
    if status in (400, 422):
        if is_unsupported_format(text):
            return FailureCode.UNSUPPORTED_FORMAT
        if any(token in text for token in _MODEL_TOKENS):
            return FailureCode.UNKNOWN_MODEL
    return FailureCode.TRANSPORT


def is_unsupported_format(text: str) -> bool:
    """The only condition that authorizes the JSON-only fallback (P05.5)."""
    return any(token in text for token in _FORMAT_TOKENS) and any(
        token in text for token in _REJECT_TOKENS
    )


def is_transient(response: httpx.Response) -> bool:
    return response.status_code in TRANSIENT_STATUS


def retry_after_seconds(response: httpx.Response, *, now: datetime) -> float | None:
    """Parse `Retry-After` as seconds or as an HTTP date against the injected operational clock.

    A malformed value is not a schedule: the caller uses its own bounded backoff instead.
    """
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return None
    if raw.replace(".", "", 1).isdigit():
        try:
            value = float(raw)
        except ValueError:
            return None
    else:
        try:
            deadline = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        value = (deadline - now).total_seconds()
    if not math.isfinite(value):
        return None
    return max(0.0, value)


def bounded_wait(response: httpx.Response, *, now: datetime, backoff: float) -> float | None:
    """The wait before the next authorized send, or None when the hint is too extreme to obey."""
    hinted = retry_after_seconds(response, now=now)
    if hinted is None:
        hinted = backoff
    if hinted > MAX_RETRY_AFTER_S:
        return None
    return hinted
