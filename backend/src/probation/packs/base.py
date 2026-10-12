"""PackAdapter protocol defining domain pack capabilities.

Authority: docs/PACKS_SPEC.md section 0 and docs/CONTRACT.md section 5.
"""

from datetime import datetime, timedelta
from typing import Any, Protocol

from probation.core.history import HistoryView
from probation.core.types import (
    Action,
    ActionSpec,
    ExamOperator,
    ExecResult,
    Features,
    Outcome,
    RawItem,
    ReaderSpec,
    Situation,
)


class WorldView(Protocol):
    """Read-only view over simulated or live external world state."""

    def get_messages(self, label: str | None = None) -> list[dict[str, Any]]:
        """Retrieve simulated messages."""
        ...

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Retrieve single message by Message-ID."""
        ...

    def get_events(self) -> list[dict[str, Any]]:
        """Retrieve simulated calendar events."""
        ...

    def get_event(self, uid: str) -> dict[str, Any] | None:
        """Retrieve single calendar event by UID."""
        ...


class ExecutorIO(Protocol):
    """Side-effect write interface over simulated or live external world state."""

    def update_message_labels(
        self,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> None:
        """Update label set for a message."""
        ...

    def add_message(
        self,
        msg_id: str,
        message_id: str,
        thread_id: str,
        from_addr: str,
        to_addr: str,
        subject: str,
        body: str,
        labels: list[str],
        received_at: str,
        in_reply_to: str | None = None,
        has_attachment: bool = False,
    ) -> None:
        """Add sent message to thread."""
        ...

    def update_rsvp(self, uid: str, rsvp_status: str) -> None:
        """Update user attendee response status (ACCEPTED, DECLINED, TENTATIVE)."""
        ...

    def add_event(
        self,
        event_id: str,
        uid: str,
        title: str,
        description: str,
        start_time: str,
        end_time: str,
        organizer: str,
        attendees: list[str],
        status: str = "CONFIRMED",
        my_status: str = "NEEDS_ACTION",
    ) -> None:
        """Add calendar event (e.g. for BLOCK_TIME)."""
        ...

    def delete_event(self, uid: str) -> None:
        """Delete an event (e.g. for undoing BLOCK_TIME)."""
        ...


class PackAdapter(Protocol):
    """Protocol for domain-specific packs (mail, calendar, files, chains, radar, reading).

    Authority: docs/CONTRACT.md section 5.
    """

    name: str
    families: tuple[str, ...]

    # 1. What shows up that needs a decision?
    def iter_situations(self, raw_item: RawItem | dict[str, Any]) -> list[Situation]:
        """Extract atomic situations from an ingested raw record."""
        ...

    # 2. What facts can we count? (history ONLY via HistoryView)
    def deterministic_clues(self, s: Situation, hist: HistoryView) -> dict[str, float | str | bool]:
        """Compute clues deterministically strictly through HistoryView (Invariant I-6)."""
        ...

    def reader_spec(self) -> ReaderSpec | None:
        """Prompt id, JSON schema, and redaction profile for LLM reader."""
        ...

    def class_key(self, s: Situation, f: Features) -> str:
        """Derive the partition class key for this situation."""
        ...

    # 3. What may the AI do?
    def action_catalog(self) -> list[ActionSpec]:
        """Action type, recallable flag, base cap, and economic loss."""
        ...

    def level_cap(self, action: str, s: Situation, f: Features) -> int:
        """Conditional caps (unknown sender, money, personal info, web veto)."""
        ...

    def hands_off(self, s: Situation) -> str | None:
        """Return non-null string reason if auto-acting is strictly forbidden."""
        ...

    # 4. Do it safely, and undo it (Executor process only)
    def execute(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Perform side-effect action."""
        ...

    def undo(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Reverse executed side-effect action."""
        ...

    # 5/6. What did the user actually do, and when is it final?
    def window(self, s: Situation) -> timedelta:
        """Observation window duration before resolution is final."""
        ...

    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None:
        """Resolve observed human action from the world state."""
        ...

    # Exam
    def exam_operators(self) -> list[ExamOperator]:
        """Perturbation operators for exam board evaluation."""
        ...
