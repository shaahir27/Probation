"""Immutable D3 lifecycle contracts; provider capabilities remain outside these records.

The versioned replay control records are owned by ``core/replay_controls.py`` and re-exported
here only so established import paths keep resolving to the same classes.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from probation.core.hashing import canonical_json
from probation.core.replay_controls import (
    ReplayCommandIntent as ReplayCommandIntent,
)
from probation.core.replay_controls import (
    ReplayScope as ReplayScope,
)

HOLD_MINUTES = 10


class LifecycleError(Exception):
    """Safe machine-readable failure without private payloads."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class LifecycleConflict(LifecycleError):
    pass


class LifecycleDenied(LifecycleError):
    pass


class LifecycleStoreUnavailable(LifecycleError):
    pass


class StaleClaim(LifecycleError):
    pass


class LifecycleRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True, slots=True)
class SourceGrant:
    source_id: str
    connection_id: str
    account_id: str
    from_addr: str


class ApprovalBinding(LifecycleRecord):
    owner_id: str
    connection_id: str
    account_id: str
    resource_id: str
    source_hash: str
    action: str
    restriction_revision: str
    params: dict[str, Any] = Field(default_factory=dict)
    body_text: str | None = None
    recipient: str | None = None
    native_thread_id: str | None = None
    native_message_id: str | None = None
    pack: str = "mail"


def binding_hash(binding: ApprovalBinding) -> str:
    return hashlib.sha256(canonical_json(binding.model_dump()).encode()).hexdigest()


class ResponseIntent(LifecycleRecord):
    request_id: str
    proposal_id: str
    response: Literal["accept", "reject", "edit", "undo"]
    owner_id: str
    responded_at: str
    reviewed_payload: ApprovalBinding
    reviewed_payload_hash: str
    action_id: str | None = None
    edited_action: str | None = None


class Submission(LifecycleRecord):
    request_id: str
    existing: bool


class CommandScope(LifecycleRecord):
    connection_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    resource_id: str | None = None
    class_key: str | None = None
    action: str | None = None

    @model_validator(mode="after")
    def complete_pair(self) -> Self:
        if (self.class_key is None) != (self.action is None):
            raise ValueError("class_key and action must be supplied together")
        if any(isinstance(v, str) and not v.strip() for v in self.model_dump().values()):
            raise ValueError("scope identifiers must not be blank")
        return self


class CommandIntent(LifecycleRecord):
    request_id: str
    owner_id: str
    type: Literal["pause", "resume", "revoke"]
    scope: CommandScope
    created_at: str


class ReceiptClaim(LifecycleRecord):
    receipt_id: str
    request_id: str
    request_kind: Literal["response", "command"]
    consumer: str
    owner: str
    fence: int


class ReceiptRecord(LifecycleRecord):
    receipt_id: str
    request_id: str
    request_kind: Literal["response", "command"]
    consumer: str
    state: str
    result: dict[str, Any] | None = None
    safe_code: str | None = None


class OutcomeEvent(LifecycleRecord):
    event_id: str
    situation_id: str
    proposal_id: str
    kind: Literal["decision", "footprint", "override", "undo", "cancel"]
    source: Literal["user_response", "footprint", "window_close", "override", "undo"]
    source_key: str
    strength: Literal["STRONG", "WEAK"]
    observed_at: str
    known_at: str
    response_id: str | None = None
    action_id: str | None = None
    decision: Literal["accept", "reject", "edit"] | None = None
    observed_action: str | None = None
    actor: Literal["human", "system"] = "human"
    correction_of: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class StoredEvent(LifecycleRecord):
    event_id: str
    ledger_seq: int


class AttemptClaim(LifecycleRecord):
    attempt_id: str
    action_id: str
    operation: Literal["execute", "undo"]
    owner: str
    fence: int
    mode: Literal["execute", "reconcile"]
    stage: str
    before_state: dict[str, Any]
    binding_hash: str


class AttemptRecord(LifecycleRecord):
    attempt_id: str
    action_id: str
    operation: Literal["execute", "undo"]
    state: str
    binding_hash: str
    before_state: dict[str, Any]
    result: dict[str, Any] | None = None
    safe_code: str | None = None


class ActionAuthority(LifecycleRecord):
    kind: Literal["autonomous", "explicit_user"]
    approval_response_id: str | None
    binding_hash: str
    undo_deadline: str | None
