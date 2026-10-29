"""Typed outcomes for the reader, prediction and writer paths.

Authority: docs/CONTRACT.md invariants I-1, I-3, I-5, I-6, I-14, I-15.
A status is a claim about what actually happened to this request. Defaults here are all
failure states: nothing in this module can report success because a component was absent.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FailureCode(StrEnum):
    """Safe, machine-readable reasons. Never a provider body or a raw exception string."""

    NOT_REGISTERED = "not_registered"
    NO_TRANSPORT_AUTHORITY = "no_transport_authority"
    BUDGET_DENIED = "budget_denied"
    ACCOUNTING_UNAVAILABLE = "accounting_unavailable"
    REDACTION_FAILED = "redaction_failed"
    CONTEXT_UNBOUND = "context_unbound"
    CONTEXT_TOO_LARGE = "context_too_large"
    ASSET_MISSING = "asset_missing"
    ASSET_MISMATCH = "asset_mismatch"
    TRANSPORT = "transport"
    AUTH = "auth"
    UNKNOWN_MODEL = "unknown_model"
    UNSUPPORTED_FORMAT = "unsupported_format"
    EMPTY_CONTENT = "empty_content"
    REASONING_ONLY = "reasoning_only"
    REFUSAL = "refusal"
    TOOL_CALLS = "tool_calls"
    TRUNCATED = "truncated"
    INVALID_OUTPUT = "invalid_output"
    CACHE_PROVENANCE = "cache_provenance"
    HEADER_CONFLICT = "header_conflict"
    CLUES_INVALID = "clues_invalid"
    DRAFT_UNAVAILABLE = "draft_unavailable"
    DRAFT_INVALID = "draft_invalid"
    BINDING_MISSING = "binding_missing"
    ATTEMPT_BUDGET_EXHAUSTED = "attempt_budget_exhausted"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything a later reader needs to decide whether a stored result is still current."""

    prompt_id: str
    prompt_version: str
    model_id: str | None
    template_hash: str | None
    schema_fingerprint: str | None
    context_version: str
    encoder_version: str
    redaction_profile: str
    redaction_counts: Mapping[str, int] = field(default_factory=dict)
    transport: str = "none"
    request_id: str | None = None
    attempt_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "model_id": self.model_id,
            "template_hash": self.template_hash,
            "schema_fingerprint": self.schema_fingerprint,
            "context_version": self.context_version,
            "encoder_version": self.encoder_version,
            "redaction_profile": self.redaction_profile,
            "redaction_counts": dict(self.redaction_counts),
            "transport": self.transport,
            "request_id": self.request_id,
            "attempt_id": self.attempt_id,
        }


class ReaderStatus(StrEnum):
    """Required and optional-disabled readers are different facts and must not be conflated."""

    VALIDATED = "validated"
    OPTIONAL_DISABLED = "optional_disabled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReaderOutcome:
    """What the reader path actually produced for one situation.

    The shape is checked because a status is a claim: a required reader that reports
    `optional_disabled`, or a `validated` reader carrying no fields, would let a gate decide
    to act on a read that never happened.
    """

    status: ReaderStatus
    required: bool
    fields: Mapping[str, Any] | None
    provenance: Provenance
    failure: FailureCode | None = None
    safe_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is ReaderStatus.VALIDATED:
            if self.fields is None or self.failure is not None:
                raise ValueError("a validated reader must carry fields and no failure")
        elif self.status is ReaderStatus.OPTIONAL_DISABLED:
            if self.required or self.fields is not None or self.failure is not None:
                raise ValueError("only an optional reader may report itself disabled")
        elif self.fields is not None or self.failure is None:
            raise ValueError("a failed reader carries no fields and one typed failure")

    @property
    def ok(self) -> bool:
        return self.status in (ReaderStatus.VALIDATED, ReaderStatus.OPTIONAL_DISABLED)

    @property
    def usable_fields(self) -> Mapping[str, Any] | None:
        return self.fields if self.status is ReaderStatus.VALIDATED else None

    @property
    def reason(self) -> str | None:
        return self.safe_reason

    @classmethod
    def failed(
        cls, required: bool, provenance: Provenance, failure: FailureCode, reason: str
    ) -> "ReaderOutcome":
        return cls(
            status=ReaderStatus.FAILED,
            required=required,
            fields=None,
            provenance=provenance,
            failure=failure,
            safe_reason=reason,
        )


class WriterStatus(StrEnum):
    DRAFTED = "drafted"
    NEEDS_USER_INPUT = "needs_user_input"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WriterOutcome:
    """Draft generation is separate from prediction and wholly separate from execution right."""

    status: WriterStatus
    body: str | None
    needs_user_input: bool
    recipient: str | None
    provenance: Provenance
    validation_notes: tuple[str, ...] = ()
    attempts: int = 0
    failure: FailureCode | None = None

    def __post_init__(self) -> None:
        if self.needs_user_input is not (self.status is WriterStatus.NEEDS_USER_INPUT):
            raise ValueError("only a needs_user_input draft may ask the user")
        if self.status is WriterStatus.DRAFTED and not self.body:
            raise ValueError("a drafted writer must carry a body")
        if self.attempts < 0:
            raise ValueError("attempt counts cannot be negative")

    @property
    def persistable(self) -> bool:
        return self.status in (WriterStatus.DRAFTED, WriterStatus.NEEDS_USER_INPUT)


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Result of any registered job call through the gateway.

    `physical_attempts` counts sends, not the logical request, and `cost_units` is the exact
    1e-8 USD unit that `llm/budget.py` reserves in. Micros or floats would re-round the
    sub-micro-cent charges that the cap has to see.
    """

    data: Mapping[str, Any]
    provenance: Provenance
    cache_hit: bool
    physical_attempts: int
    cost_units: int
    tokens_in: int = 0
    tokens_out: int = 0

    def __post_init__(self) -> None:
        if self.cache_hit and self.physical_attempts != 0:
            raise ValueError("a cache hit dispatches nothing")
        if self.cost_units < 0 or self.physical_attempts < 0:
            raise ValueError("attempt and cost counts cannot be negative")
        if self.tokens_in < 0 or self.tokens_out < 0:
            raise ValueError("token counts cannot be negative")
        if not self.cache_hit and (self.physical_attempts < 1 or self.cost_units < 1):
            raise ValueError("a dispatched job records at least one attempt and one unit")


class PredictionStatus(StrEnum):
    COMPUTED = "computed"
    COLD_START = "cold_start"
    ABSTAIN = "abstain"
