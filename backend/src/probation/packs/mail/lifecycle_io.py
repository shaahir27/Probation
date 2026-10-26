"""Executor mail capabilities: compare-and-set effects and honest reconciliation."""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


class MailConflict(ValueError):
    """Stable operation identity or observed resource state changed."""


@dataclass(frozen=True)
class MailSnapshot:
    resource_id: str
    native_message_id: str
    thread_id: str
    labels: tuple[str, ...]
    revision: str
    label_versions: dict[str, int] = field(default_factory=dict)
    # The provider history point before the effect. Persisted with the undo proof so a later
    # undo can prove label versions even after the cursor has moved past the effect.
    message_history_id: int = 0


@dataclass(frozen=True)
class MailReceipt:
    outcome: Literal["confirmed", "failed", "unknown"]
    native_ref: str | None = None
    safe_code: str | None = None
    after_state: dict[str, Any] = field(default_factory=dict)
    confirmed_no_effect: bool = False


@runtime_checkable
class MailExecutionIO(Protocol):
    def snapshot_mail(self, resource_id: str) -> MailSnapshot: ...

    def apply_mail(
        self,
        operation_id: str,
        payload_hash: str,
        payload: dict[str, Any],
        expected_revision: str,
    ) -> MailReceipt: ...

    def reconcile_mail(self, operation_id: str, payload_hash: str) -> MailReceipt: ...
