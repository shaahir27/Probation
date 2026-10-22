"""PackAdapter protocol defining domain pack capabilities.

Authority: docs/PACKS_SPEC.md section 0 and docs/CONTRACT.md section 5.
"""

from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
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

    def get_files(self) -> list[dict[str, Any]]:
        """Retrieve simulated file records."""
        ...

    def get_tracker_entries(self, status: str | None = None) -> list[dict[str, Any]]:
        """Retrieve simulated opportunity tracker entries."""
        ...

    def get_tracker_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Retrieve single tracker entry by ID."""
        ...

    def get_library_entries(self, collection: str | None = None) -> list[dict[str, Any]]:
        """Retrieve simulated reading library entries."""
        ...

    def get_library_entry(self, url: str) -> dict[str, Any] | None:
        """Retrieve single library entry by URL."""
        ...

    def get_user_actions(
        self,
        item_id: str | None = None,
        as_of: str | None = None,
        actor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recorded user actions."""
        ...


@runtime_checkable
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

    def add_file(
        self,
        file_id: str,
        path: str,
        filename: str,
        ext: str,
        size_bytes: int,
        origin_url: str,
        downloaded_at: str,
        sha256: str,
    ) -> None:
        """Add or update file record."""
        ...

    def add_tracker_entry(
        self,
        entry_id: str,
        title: str,
        organizer: str,
        opp_type: str = "other",
        deadline_date: str | None = None,
        official_url: str | None = None,
        status: str = "TRACKED",
        fee_flag: bool = False,
        sources: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> None:
        """Add opportunity to tracker."""
        ...

    def update_tracker_status(self, entry_id: str, status: str) -> None:
        """Update status of tracker entry."""
        ...

    def delete_tracker_entry(self, entry_id: str) -> None:
        """Delete opportunity from tracker."""
        ...

    def get_tracker_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Retrieve single tracker entry by ID."""
        ...

    def add_library_entry(
        self,
        entry_id: str,
        url: str,
        title: str = "",
        collection: str = "inbox",
        topic: str = "other",
        content_type: str = "article",
        saved_at: str | None = None,
    ) -> None:
        """Add link to library."""
        ...

    def update_library_collection(self, url: str, collection: str) -> None:
        """Update collection category for a saved link."""
        ...

    def get_library_entry(self, url: str) -> dict[str, Any] | None:
        """Retrieve single library entry by URL."""
        ...

    def delete_library_entry(self, url: str) -> None:
        """Delete link from library."""
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
