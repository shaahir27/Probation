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
    """What the reader path actually produced for one situation."""

    status: ReaderStatus
    required: bool
    fields: Mapping[str, Any] | None
    provenance: Provenance
    failure: FailureCode | None = None
    safe_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (ReaderStatus.VALIDATED, ReaderStatus.OPTIONAL_DISABLED)

    @property
    def usable_fields(self) -> Mapping[str, Any] | None:
        return self.fields if self.status is ReaderStatus.VALIDATED else None

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

    @property
    def persistable(self) -> bool:
        return self.status in (WriterStatus.DRAFTED, WriterStatus.NEEDS_USER_INPUT)


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """Result of any registered job call through the gateway."""

    data: Mapping[str, Any]
    provenance: Provenance
    cache_hit: bool
    physical_attempts: int
    cost_usd_micros: int


class PredictionStatus(StrEnum):
    COMPUTED = "computed"
    COLD_START = "cold_start"
    ABSTAIN = "abstain"
