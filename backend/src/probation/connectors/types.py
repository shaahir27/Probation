"""Shared pure connector records: no transport, no credentials, no I/O.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 6 and docs/FULL_PRODUCT_SPEC.md
section 5.1. Transport lives under the pack connector modules; this file holds only
validated immutable data and typed failures.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

CredentialRole = Literal["read", "write"]

EventType = Literal[
    "message_added",
    "label_added",
    "label_removed",
    "message_deleted",
    "sent_observed",
]

TimeProvenance = Literal["provider_occurrence", "observed_locally", "unknown"]

CapabilityName = Literal[
    "read",
    "archive",
    "trash",
    "send",
    "forward",
    "reconciliation",
    "undo_history_proof",
    "conditional_write",
    "attribution",
]

ConnectionState = Literal[
    "UNCONFIGURED",
    "AUTHORIZING",
    "AUTHORIZED",
    "BACKFILLING",
    "SHADOW",
    "ACTIVE",
    "PAUSED",
    "DEGRADED",
    "AUTH_REQUIRED",
    "DISCONNECTED",
]

_MAX_REF = 512


class ConnectorError(ValueError):
    """Typed connector failure carrying only safe codes, never content or secrets."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class CredentialUnavailable(ConnectorError):
    """No grant is provisioned to this process for the requested role."""


class ScopeMismatch(ConnectorError):
    """The installed grant lacks a scope a capability requires."""


class ProviderUnavailable(ConnectorError):
    """The provider cannot serve the request; dependent work halts."""


class TransportFailure(ProviderUnavailable):
    """No HTTP status was received (connect/timeout/protocol): an effect is ambiguous."""


class SelectionViolation(ConnectorError):
    """A requested resource is not inside the owner-approved cohort."""


class CursorRejected(ConnectorError):
    """A cursor does not belong to this connection, resource or filter revision."""


class HistoryStale(CursorRejected):
    """The provider history anchor aged out; full re-sync is required."""


class BoundedInputExceeded(ConnectorError):
    """A payload exceeded an approved size, depth or part limit."""


def _checked(value: str, label: str) -> str:
    if not value or len(value) > _MAX_REF:
        raise ConnectorError(f"invalid_{label}")
    if any(ord(char) < 32 for char in value):
        raise ConnectorError(f"unsafe_{label}")
    return value


@dataclass(frozen=True)
class NativeRef:
    """Provider identity for one resource. Native, thread and RFC ids never substitute."""

    connection_id: str
    account_id: str
    native_message_id: str
    thread_id: str | None = None
    rfc_message_id: str | None = None

    def __post_init__(self) -> None:
        _checked(self.connection_id, "connection_id")
        _checked(self.account_id, "account_id")
        _checked(self.native_message_id, "native_message_id")


@dataclass(frozen=True)
class SourceSelection:
    """Owner-provisioned cohort identity. A revision change invalidates cursors."""

    connection_id: str
    account_id: str
    selection_revision: int
    label_ids: tuple[str, ...] = ()
    native_message_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _checked(self.connection_id, "connection_id")
        if self.selection_revision < 1:
            raise SelectionViolation("invalid_selection_revision")

    def covers(self, ref: NativeRef) -> bool:
        return ref.connection_id == self.connection_id and ref.account_id == self.account_id


@dataclass(frozen=True)
class SyncCursor:
    """Never shared across accounts, resources, roles, filter revisions or versions."""

    connection_id: str
    account_id: str
    resource_key: str
    role: CredentialRole
    filter_revision: int
    history_id: int
    page_token: str | None = None
    protocol_version: str = "gmail-v1"

    def __post_init__(self) -> None:
        _checked(self.connection_id, "connection_id")
        _checked(self.resource_key, "resource_key")
        if self.role not in ("read", "write"):
            raise CursorRejected("invalid_cursor_role")
        if self.history_id < 0:
            raise CursorRejected("invalid_history_id")
        if self.filter_revision < 1:
            raise CursorRejected("invalid_filter_revision")

    def matches_selection(self, selection: SourceSelection, resource_key: str) -> bool:
        return (
            self.connection_id == selection.connection_id
            and self.account_id == selection.account_id
            and self.resource_key == resource_key
            and self.filter_revision == selection.selection_revision
        )


@dataclass(frozen=True)
class SourceObservation:
    """One committed provider event. Content stays behind a local payload reference."""

    connection_id: str
    account_id: str
    native_message_id: str
    history_id: int
    event_type: EventType
    content_hash: str
    version_hash: str
    observed_at: str
    provenance: TimeProvenance
    payload_ref: str | None = None
    thread_id: str | None = None
    occurrence_time: str | None = None
    label_ids: tuple[str, ...] = ()
    rfc_message_id: str | None = None
    is_selected: bool = True

    def __post_init__(self) -> None:
        _checked(self.connection_id, "connection_id")
        _checked(self.native_message_id, "native_message_id")
        _checked(self.content_hash, "content_hash")
        _checked(self.version_hash, "version_hash")
        _checked(self.observed_at, "observed_at")
        if self.history_id < 0:
            raise ConnectorError("invalid_history_id")
        if self.event_type == "message_deleted" and self.payload_ref is not None:
            raise ConnectorError("tombstone_carries_payload")


@dataclass(frozen=True)
class ObservationPage:
    """One bounded result. Completed identity lets a retry prove it already committed."""

    observations: tuple[SourceObservation, ...]
    next_page_token: str | None
    completed_page_identity: str
    proposed_next_cursor: SyncCursor
    source_selection: SourceSelection
    resync_required: bool = False

    def __post_init__(self) -> None:
        _checked(self.completed_page_identity, "page_identity")
        cursor = self.proposed_next_cursor
        if not cursor.matches_selection(self.source_selection, cursor.resource_key):
            raise CursorRejected("cursor_selection_mismatch")


@dataclass(frozen=True)
class LabelTransition:
    """Provider-observed label change for one message. Never synthesised locally."""

    native_message_id: str
    label_id: str
    history_id: int
    added: bool

    def __post_init__(self) -> None:
        _checked(self.native_message_id, "native_message_id")
        _checked(self.label_id, "label_id")
        if self.history_id < 0:
            raise ConnectorError("invalid_history_id")


@dataclass(frozen=True)
class LabelVersionEvidence:
    """Per-label transition counts proven from retained provider history.

    ``continuous`` is false whenever the observation window cannot prove that no
    transition was missed. Callers must then fail closed rather than trust counts.
    """

    native_message_id: str
    versions: dict[str, int] = field(default_factory=dict)
    continuous: bool = True
    anchor_history_id: int | None = None

    def __post_init__(self) -> None:
        _checked(self.native_message_id, "native_message_id")
        if any(count < 0 for count in self.versions.values()):
            raise ConnectorError("negative_label_version")


def advance_versions(
    base: dict[str, int], transitions: tuple[LabelTransition, ...], message_id: str
) -> dict[str, int]:
    """Apply observed transitions for one message. Only the provider may add a step."""
    advanced = dict(base)
    for transition in transitions:
        if transition.native_message_id != message_id:
            continue
        current = advanced.get(transition.label_id, 0)
        advanced[transition.label_id] = current + 1
    return advanced


@dataclass(frozen=True)
class CapabilityState:
    """Versioned readiness for one operation, with a safe blocking reason."""

    name: CapabilityName
    supported: bool
    verified_at: str
    evidence: str = "unverified"
    reason: str | None = None

    def __post_init__(self) -> None:
        _checked(self.verified_at, "verified_at")
        if not self.supported and self.reason is None:
            raise ConnectorError("unsupported_needs_reason")
        if self.reason is not None:
            _checked(self.reason, "reason")


@dataclass(frozen=True)
class CapabilityManifest:
    """Honest provider limits. A local lock is never reported as provider atomicity."""

    provider: str
    provider_version: str
    states: tuple[CapabilityState, ...]
    granted_scopes: tuple[str, ...] = ()
    idempotency: Literal["provider_key", "local_correlation_only", "none"] = "none"
    reconciliation: Literal["provider_query", "bounded_local_evidence", "none"] = (
        "bounded_local_evidence"
    )

    def state(self, name: CapabilityName) -> CapabilityState | None:
        for state in self.states:
            if state.name == name:
                return state
        return None

    def supports(self, name: CapabilityName) -> bool:
        state = self.state(name)
        return bool(state and state.supported)


@dataclass(frozen=True)
class EffectReceipt:
    """Native effect provenance kept private; only hashes are publishable."""

    outcome: Literal["confirmed", "failed", "unknown"]
    native_ref_hash: str | None = None
    safe_code: str | None = None
    verified_no_effect: bool = False

    def __post_init__(self) -> None:
        if self.verified_no_effect and self.outcome != "failed":
            raise ConnectorError("no_effect_proof_needs_failure")


@dataclass(frozen=True)
class MessagePayload:
    """Bounded, already-parsed message content. Contract: docs/WP12_D4_GMAIL_CONTRACT.md §12."""

    native_message_id: str
    thread_id: str | None
    rfc_message_id: str | None
    from_addr: str
    to_addr: tuple[str, ...]
    cc_addrs: tuple[str, ...]
    subject: str
    body_text: str
    occurred_at: str | None
    attachment_present: bool
    content_hash: str

    def __post_init__(self) -> None:
        _checked(self.native_message_id, "native_message_id")
        _checked(self.from_addr, "from_addr")
        _checked(self.content_hash, "content_hash")
        for value in (*self.to_addr, *self.cc_addrs):
            _checked(value, "recipient")
        if len(self.body_text) > 2_000_000:
            raise BoundedInputExceeded("payload_body_too_large")


class PayloadWriter(Protocol):
    """Persist parsed content under the private payload root; returns the relative ref."""

    def write(self, payload: MessagePayload) -> str: ...


class PayloadReader(Protocol):
    """Read by relative ref. A missing or hash-mismatched payload must raise, never degrade."""

    def read(self, payload_ref: str) -> MessagePayload: ...


@dataclass(frozen=True)
class HttpResult:
    """One transport result. Body is bytes: decoding and trust are the caller's problem."""

    status: int
    body: bytes = b""
    retry_after_seconds: float | None = None
    request_id_hash: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class HttpTransport(Protocol):
    """The only seam through which a Gmail REST call may leave the process.

    Implementations live in pack connector modules and in tests. A fake must reproduce Gmail's
    documented limits: no conditional modify, per-message `historyId`, and 404 once a history
    anchor ages out. A fake that offers stronger atomicity proves nothing about Gmail.
    """

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | None] | None = None,
        access_token: str,
    ) -> HttpResult: ...

    def post(
        self,
        url: str,
        *,
        json_body: Mapping[str, object] | None = None,
        data: bytes | None = None,
        access_token: str,
    ) -> HttpResult: ...
