"""Tests for pack executors and exam perturbation operators.

Authority: docs/PACKS_SPEC.md sections 1.7, 2.6, 2.7 and docs/CONTRACT.md section 8.
"""

from typing import Any

from probation.core.types import Action
from probation.packs.calendar.exam_ops import (
    CALENDAR_EXAM_OPERATORS,
    apply_calendar_code_operator,
    validate_calendar_operator_result,
)
from probation.packs.calendar.executor import (
    execute_calendar_action,
    undo_calendar_action,
)
from probation.packs.mail.exam_ops import (
    MAIL_EXAM_OPERATORS,
    apply_mail_code_operator,
    validate_mail_operator_result,
)
from probation.packs.mail.executor import execute_mail_action, undo_mail_action


class MemoryExecutorIO:
    """Mock ExecutorIO recording side-effects in memory."""

    def __init__(self) -> None:
        self.message_labels: dict[str, set[str]] = {}
        self.sent_messages: list[dict[str, Any]] = []
        self.rsvps: dict[str, str] = {}
        self.events: list[dict[str, Any]] = []

    def update_message_labels(
        self,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> None:
        labels = self.message_labels.setdefault(message_id, set())
        if add_labels:
            labels.update(add_labels)
        if remove_labels:
            labels.difference_update(remove_labels)

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
        self.sent_messages.append(
            {
                "msg_id": msg_id,
                "message_id": message_id,
                "thread_id": thread_id,
                "from_addr": from_addr,
                "to_addr": to_addr,
                "subject": subject,
                "body": body,
                "labels": labels,
                "received_at": received_at,
                "in_reply_to": in_reply_to,
                "has_attachment": has_attachment,
            }
        )

    def update_rsvp(self, uid: str, status: str) -> None:
        self.rsvps[uid] = status

    def add_event(
        self,
        event_id: str,
        uid: str,
        title: str,
        description: str,
        start_time: str,
        end_time: str,
        organizer: str,
        attendees: list[dict[str, Any]],
        status: str,
        my_status: str,
    ) -> None:
        self.events.append(
            {
                "event_id": event_id,
                "uid": uid,
                "title": title,
                "description": description,
                "start_time": start_time,
                "end_time": end_time,
                "organizer": organizer,
                "attendees": attendees,
                "status": status,
                "my_status": my_status,
            }
        )


def test_mail_executor_archive_and_undo() -> None:
    """Test ARCHIVE action updates labels and undo restores INBOX."""
    io = MemoryExecutorIO()
    io.message_labels["msg-1"] = {"INBOX", "UNREAD"}

    action = Action(
        id="act-1",
        proposal_id="prop-1",
        pack="mail",
        type="ARCHIVE",
        params={"message_id": "msg-1"},
        level_required=2,
        recallable=True,
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:00Z",
    )

    res = execute_mail_action(action, io)
    assert res.success is True
    assert "INBOX" not in io.message_labels["msg-1"]
    assert res.undo_data is not None

    # Undo
    undo_action = action.model_copy(update={"undo": res.undo_data})
    undo_res = undo_mail_action(undo_action, io)
    assert undo_res.success is True
    assert "INBOX" in io.message_labels["msg-1"]


def test_mail_executor_trash_and_undo() -> None:
    """Test TRASH action adds TRASH label and undo removes it."""
    io = MemoryExecutorIO()
    io.message_labels["msg-2"] = {"INBOX"}

    action = Action(
        id="act-2",
        proposal_id="prop-2",
        pack="mail",
        type="TRASH",
        params={"message_id": "msg-2"},
        level_required=2,
        recallable=True,
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:00Z",
    )

    res = execute_mail_action(action, io)
    assert res.success is True
    assert "TRASH" in io.message_labels["msg-2"]

    # Undo
    undo_action = action.model_copy(update={"undo": res.undo_data})
    undo_res = undo_mail_action(undo_action, io)
    assert undo_res.success is True
    assert "TRASH" not in io.message_labels["msg-2"]


def test_mail_executor_reply() -> None:
    """Test REPLY action sends message to thread."""
    io = MemoryExecutorIO()
    action = Action(
        id="act-3",
        proposal_id="prop-3",
        pack="mail",
        type="REPLY",
        params={
            "message_id": "msg-3",
            "body": "Sounds good, thanks!",
            "to_addr": "colleague@example.test",
        },
        level_required=2,
        recallable=False,
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:00Z",
    )

    res = execute_mail_action(action, io)
    assert res.success is True
    assert len(io.sent_messages) == 1
    assert io.sent_messages[0]["body"] == "Sounds good, thanks!"
    assert res.undo_data is None  # Non-recallable external send


def test_mail_executor_unsupported_action() -> None:
    """Unsupported action type returns failure result."""
    io = MemoryExecutorIO()
    action = Action(
        id="act-4",
        proposal_id="prop-4",
        pack="mail",
        type="UNKNOWN_ACTION",
        params={"message_id": "msg-4"},
        level_required=1,
        recallable=True,
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:00Z",
    )
    res = execute_mail_action(action, io)
    assert res.success is False
    assert "Unsupported mail action type" in (res.error or "")


def test_calendar_executor_accept_and_undo() -> None:
    """Test ACCEPT sets RSVP to ACCEPTED and undo restores previous status."""
    io = MemoryExecutorIO()
    io.rsvps["evt-1"] = "NEEDS_ACTION"

    action = Action(
        id="act-cal-1",
        proposal_id="prop-cal-1",
        pack="calendar",
        type="ACCEPT",
        params={"uid": "evt-1"},
        level_required=2,
        recallable=True,
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:00Z",
    )

    res = execute_calendar_action(action, io)
    assert res.success is True
    assert io.rsvps["evt-1"] == "ACCEPTED"

    # Undo
    undo_action = action.model_copy(update={"undo": res.undo_data})
    undo_res = undo_calendar_action(undo_action, io)
    assert undo_res.success is True
    assert io.rsvps["evt-1"] == "NEEDS_ACTION"


def test_calendar_executor_block_time() -> None:
    """Test BLOCK_TIME creates focused private event."""
    io = MemoryExecutorIO()
    action = Action(
        id="act-cal-2",
        proposal_id="prop-cal-2",
        pack="calendar",
        type="BLOCK_TIME",
        params={
            "uid": "block-123",
            "title": "Deep Work Block",
            "start_time": "2026-03-02T10:00:00Z",
            "end_time": "2026-03-02T12:00:00Z",
        },
        level_required=2,
        recallable=True,
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:00Z",
    )
    res = execute_calendar_action(action, io)
    assert res.success is True
    assert len(io.events) == 1
    assert io.events[0]["title"] == "Deep Work Block"


def test_mail_exam_operators() -> None:
    """Test all code-based perturbation operators for the Mail pack."""
    assert len(MAIL_EXAM_OPERATORS) == 10

    orig_text = "Hi Team,\nPlease review the document attached.\nBest regards,\nMeena"
    orig_payload = {"subject": "Weekly review", "from_addr": "lead@company.test"}

    # 1. change_greeting
    mut_text, _ = apply_mail_code_operator("change_greeting", orig_text, orig_payload)
    assert validate_mail_operator_result("change_greeting", orig_text, mut_text)

    # 2. add_typos
    mut_text, _ = apply_mail_code_operator("add_typos", orig_text, orig_payload)
    assert validate_mail_operator_result("add_typos", orig_text, mut_text)

    # 3. add_footer
    mut_text, _ = apply_mail_code_operator("add_footer", orig_text, orig_payload)
    assert validate_mail_operator_result("add_footer", orig_text, mut_text)

    # 4. inject_instruction
    mut_text, _ = apply_mail_code_operator("inject_instruction", orig_text, orig_payload)
    assert validate_mail_operator_result("inject_instruction", orig_text, mut_text)

    # 5. tighten_deadline
    mut_text, _ = apply_mail_code_operator("tighten_deadline", orig_text, orig_payload)
    assert validate_mail_operator_result("tighten_deadline", orig_text, mut_text)

    # 6. add_link_unknown_domain
    mut_text, _ = apply_mail_code_operator("add_link_unknown_domain", orig_text, orig_payload)
    assert validate_mail_operator_result("add_link_unknown_domain", orig_text, mut_text)


def test_calendar_exam_operators() -> None:
    """Test all code-based perturbation operators for the Calendar pack."""
    assert len(CALENDAR_EXAM_OPERATORS) == 6

    orig_payload = {
        "title": "Sprint Planning",
        "description": "Discuss sprint goals.",
        "organizer": "scrum@company.test",
        "conflicts_count": 0,
        "start_time": "2026-03-15T14:00:00Z",
    }

    # 1. add_boilerplate
    mut1 = apply_calendar_code_operator("add_boilerplate", orig_payload)
    assert validate_calendar_operator_result("add_boilerplate", orig_payload, mut1)

    # 2. organizer_unknown
    mut2 = apply_calendar_code_operator("organizer_unknown", orig_payload)
    assert validate_calendar_operator_result("organizer_unknown", orig_payload, mut2)

    # 3. add_fee_mention
    mut3 = apply_calendar_code_operator("add_fee_mention", orig_payload)
    assert validate_calendar_operator_result("add_fee_mention", orig_payload, mut3)

    # 4. introduce_conflict
    mut4 = apply_calendar_code_operator("introduce_conflict", orig_payload)
    assert validate_calendar_operator_result("introduce_conflict", orig_payload, mut4)

    # 5. unusual_hour
    mut5 = apply_calendar_code_operator("unusual_hour", orig_payload)
    assert validate_calendar_operator_result("unusual_hour", orig_payload, mut5)
