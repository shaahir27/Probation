"""Contract test T-RESOLVE: Outcome resolution table and priority test suite.

Authority: docs/PACKS_SPEC.md sections 1.6 and 2.5 and docs/TEST_PLAN.md (T-RESOLVE).
Verifies:
1. Mail outcome priority ranking: REPLY > FORWARD > TRASH > ARCHIVE > LEAVE.
2. Mail censoring window behavior (returns None before window close).
3. Calendar outcome transitions: ACCEPT, DECLINE, TENTATIVE, NO_RESPONSE.
4. Calendar censoring window behavior before event start.
"""

from datetime import UTC, datetime
from typing import Any

from probation.core.enums import EvidenceStrength
from probation.core.types import Situation
from probation.packs.calendar.resolver import resolve_calendar_outcome
from probation.packs.mail.resolver import resolve_mail_outcome


class MockWorldView:
    """Mock WorldView with configurable messages and events.

    A message may carry ``label_history``: a list of ``[valid_from_iso, labels]`` pairs in ascending
    order, with ``initial_labels`` for the state before the first entry. Resolvers ask for the state
    at an observation point, so a double that can only answer with its final state cannot exercise
    them.
    """

    def __init__(
        self,
        messages: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.messages = messages or []
        self.events = events or []

    @staticmethod
    def _project(message: dict[str, Any], as_of: str | None) -> dict[str, Any]:
        history = message.get("label_history")
        if as_of is None or not history:
            return message
        labels = message.get("initial_labels", ["INBOX"])
        for valid_from, current in history:
            if str(valid_from) > as_of:
                break
            labels = current
        return {**message, "labels": list(labels)}

    def get_messages(
        self, label: str | None = None, as_of: str | None = None
    ) -> list[dict[str, Any]]:
        return [self._project(m, as_of) for m in self.messages]

    def get_message(self, message_id: str, as_of: str | None = None) -> dict[str, Any] | None:
        for m in self.messages:
            if m.get("message_id") == message_id:
                return self._project(m, as_of)
        return None

    def get_events(self, as_of: str | None = None) -> list[dict[str, Any]]:
        return self.events

    def get_event(self, uid: str, as_of: str | None = None) -> dict[str, Any] | None:
        for e in self.events:
            if e.get("uid") == uid:
                return e
        return None


def test_t_resolve_mail_priority_order() -> None:
    """T-RESOLVE: Verify strict mail resolution priority ranking."""
    sit = Situation(
        id="sit-mail-prio",
        raw_item_id="raw-1",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-01T10:00:00Z",
        content_hash="h1",
        created_at="2026-03-01T10:00:00Z",
    )
    raw_payload = {
        "message_id": "<orig@domain.test>",
        "subject": "Important Project Review",
        "labels": ["INBOX", "TRASH"],  # Has TRASH label
    }

    # Case 1: Message has a reply AND a forward AND is trashed -> REPLY must win!
    reply_msg = {
        "message_id": "<rep@local>",
        "from_addr": "meena@example.test",
        "in_reply_to": "<orig@domain.test>",
        "received_at": "2026-03-02T11:00:00Z",
    }
    forward_msg = {
        "message_id": "<fwd@local>",
        "from_addr": "meena@example.test",
        "subject": "Fwd: Important Project Review",
        "body": "See <orig@domain.test>",
        "received_at": "2026-03-03T11:00:00Z",
    }
    orig_msg = {
        "message_id": "<orig@domain.test>",
        "labels": ["TRASH"],
    }

    world = MockWorldView(messages=[reply_msg, forward_msg, orig_msg])
    now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)  # Past the 7-day window

    out_reply = resolve_mail_outcome(sit, world, now, raw_payload)
    assert out_reply is not None
    assert out_reply.observed_action == "REPLY"
    assert out_reply.strength == EvidenceStrength.STRONG
    assert out_reply.known_at == "2026-03-02T11:00:00Z"

    # Case 2: No reply, but Forward exists AND message is trashed -> FORWARD must win!
    world_no_reply = MockWorldView(messages=[forward_msg, orig_msg])
    out_fwd = resolve_mail_outcome(sit, world_no_reply, now, raw_payload)
    assert out_fwd is not None
    assert out_fwd.observed_action == "FORWARD"
    assert out_fwd.strength == EvidenceStrength.STRONG
    assert out_fwd.known_at == "2026-03-03T11:00:00Z"

    # Case 3: No reply, no forward, message in TRASH -> TRASH wins!
    world_trash = MockWorldView(messages=[orig_msg])
    out_trash = resolve_mail_outcome(sit, world_trash, now, raw_payload)
    assert out_trash is not None
    assert out_trash.observed_action == "TRASH"
    assert out_trash.strength == EvidenceStrength.STRONG

    # Case 4: No reply, no forward, not in TRASH, no INBOX label -> ARCHIVE wins!
    arch_msg = {"message_id": "<orig@domain.test>", "labels": ["CUSTOM_LABEL"]}
    world_arch = MockWorldView(messages=[arch_msg])
    out_arch = resolve_mail_outcome(sit, world_arch, now, raw_payload)
    assert out_arch is not None
    assert out_arch.observed_action == "ARCHIVE"
    assert out_arch.strength == EvidenceStrength.STRONG

    # Case 5: Still in INBOX -> LEAVE (WEAK)
    inbox_msg = {"message_id": "<orig@domain.test>", "labels": ["INBOX"]}
    world_inbox = MockWorldView(messages=[inbox_msg])
    out_leave = resolve_mail_outcome(sit, world_inbox, now, raw_payload)
    assert out_leave is not None
    assert out_leave.observed_action == "LEAVE"
    assert out_leave.strength == EvidenceStrength.WEAK


def test_t_resolve_mail_censoring() -> None:
    """T-RESOLVE: Verify mail window right-censoring."""
    sit = Situation(
        id="sit-mail-censor",
        raw_item_id="raw-censor",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-05T10:00:00Z",
        content_hash="hcensor",
        created_at="2026-03-05T10:00:00Z",
    )
    raw_payload = {"message_id": "<msg-censor@test.local>", "labels": ["INBOX"]}
    world = MockWorldView(messages=[{"message_id": "<msg-censor@test.local>", "labels": ["INBOX"]}])

    # Now is day 3 (within 7 day window) and no reply happened
    now_early = datetime(2026, 3, 8, 10, 0, tzinfo=UTC)
    out_censored = resolve_mail_outcome(sit, world, now_early, raw_payload)
    assert out_censored is None, "Expected outcome to be censored while window is open"

    # Now is day 9 (window closed) -> LEAVE resolves
    now_past = datetime(2026, 3, 14, 10, 0, tzinfo=UTC)
    out_resolved = resolve_mail_outcome(sit, world, now_past, raw_payload)
    assert out_resolved is not None
    assert out_resolved.observed_action == "LEAVE"


def test_a_label_applied_after_the_window_is_not_knowledge_at_the_deadline() -> None:
    """C9: a late archive must not be reported as something the system could know at window close.

    Every label outcome carries ``known_at = window close``. Reading the label state "as of now"
    made a full-persona run resolve against the end of the story, so an owner who archived on day 20
    produced evidence dated day 12 -- earlier than the fact -- and the policy learned from it.
    """
    sit = Situation(
        id="sit-mail-late",
        raw_item_id="raw-late",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-05T10:00:00Z",
        content_hash="hlate",
        created_at="2026-03-05T10:00:00Z",
    )
    late_archive = {
        "message_id": "<msg-late@test.local>",
        "initial_labels": ["INBOX"],
        "labels": ["ARCHIVED"],
        "label_history": [["2026-03-25T09:00:00Z", ["ARCHIVED"]]],
    }
    world = MockWorldView(messages=[late_archive])
    payload = {"message_id": "<msg-late@test.local>", "labels": ["ARCHIVED"]}

    out = resolve_mail_outcome(sit, world, datetime(2026, 4, 1, tzinfo=UTC), payload)
    assert out is not None
    assert out.observed_action == "LEAVE"
    assert out.known_at == "2026-03-12T10:00:00Z"
    # The exported payload still carries the final label set for later resolution; what changed is
    # that it can no longer answer a question dated at the deadline.
    assert payload["labels"] == ["ARCHIVED"]

    # An archive applied before the deadline is still read as an archive, so nothing about the
    # world has been forgotten -- only dated to when it was true.
    as_of_archive = MockWorldView(
        messages=[{**late_archive, "label_history": [["2026-03-11T09:00:00Z", ["ARCHIVED"]]]}]
    )
    early_owner_action = resolve_mail_outcome(
        sit, as_of_archive, datetime(2026, 4, 1, tzinfo=UTC), payload
    )
    assert early_owner_action is not None
    assert early_owner_action.observed_action == "ARCHIVE"


def test_a_world_that_cannot_answer_as_of_yields_no_label_outcome() -> None:
    """Plan 6.2.6: an adapter without an observation point is not a licence to read the final state."""

    class NoHorizonWorld:
        def get_messages(self, label: str | None = None) -> list[dict[str, Any]]:
            return []

        def get_message(self, message_id: str) -> dict[str, Any] | None:
            return {"message_id": message_id, "labels": ["TRASH"]}

        def get_events(self) -> list[dict[str, Any]]:
            return []

        def get_event(self, uid: str) -> dict[str, Any] | None:
            return None

    sit = Situation(
        id="sit-mail-no-horizon",
        raw_item_id="raw-nh",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-01T10:00:00Z",
        content_hash="hnh",
        created_at="2026-03-01T10:00:00Z",
    )
    payload = {"message_id": "<nh@domain.test>", "labels": ["INBOX", "TRASH"]}

    assert resolve_mail_outcome(
        sit, NoHorizonWorld(), datetime(2026, 3, 10, tzinfo=UTC), payload
    ) is (None)


def test_a_message_missing_from_the_world_is_unresolved_not_read_from_the_export() -> None:
    """Failing closed beats inventing a verdict from the archive's own label header."""
    sit = Situation(
        id="sit-mail-absent",
        raw_item_id="raw-abs",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-01T10:00:00Z",
        content_hash="habs",
        created_at="2026-03-01T10:00:00Z",
    )
    world = MockWorldView(messages=[])

    assert (
        resolve_mail_outcome(
            sit, world, datetime(2026, 3, 10, tzinfo=UTC), {"message_id": "<gone@domain.test>"}
        )
        is None
    )


def test_t_resolve_calendar_outcomes_and_censoring() -> None:
    """T-RESOLVE: Verify calendar RSVP transitions and window censoring."""
    sit = Situation(
        id="sit-cal-resolve",
        raw_item_id="raw-cal-res",
        pack="calendar",
        family="invite_rsvp",
        occurred_at="2026-03-01T10:00:00Z",
        content_hash="hcal",
        created_at="2026-03-01T10:00:00Z",
    )
    raw_payload = {
        "uid": "event-res-uid",
        "start_time": "2026-03-05T14:00:00Z",
        "responded_at": "2026-03-02T09:00:00Z",
    }

    # Case 1: Status ACCEPTED -> ACCEPT (STRONG)
    ev_accept = {"uid": "event-res-uid", "my_status": "ACCEPTED"}
    world_acc = MockWorldView(events=[ev_accept])
    now = datetime(2026, 3, 3, 10, 0, tzinfo=UTC)
    out_acc = resolve_calendar_outcome(sit, world_acc, now, raw_payload)
    assert out_acc is not None
    assert out_acc.observed_action == "ACCEPT"
    assert out_acc.strength == EvidenceStrength.STRONG
    assert out_acc.known_at == "2026-03-02T09:00:00Z"

    # Case 2: Status DECLINED -> DECLINE (STRONG)
    ev_decl = {"uid": "event-res-uid", "my_status": "DECLINED"}
    world_decl = MockWorldView(events=[ev_decl])
    out_decl = resolve_calendar_outcome(sit, world_decl, now, raw_payload)
    assert out_decl is not None
    assert out_decl.observed_action == "DECLINE"
    assert out_decl.strength == EvidenceStrength.STRONG

    # Case 3: Still NEEDS_ACTION and before event start (2026-03-05) -> Censored
    ev_pending = {"uid": "event-res-uid", "my_status": "NEEDS_ACTION"}
    world_pend = MockWorldView(events=[ev_pending])
    now_before_start = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
    out_pend_censored = resolve_calendar_outcome(sit, world_pend, now_before_start, raw_payload)
    assert out_pend_censored is None

    # Case 4: Still NEEDS_ACTION after event start -> NO_RESPONSE (WEAK)
    now_after_start = datetime(2026, 3, 6, 10, 0, tzinfo=UTC)
    out_no_resp = resolve_calendar_outcome(sit, world_pend, now_after_start, raw_payload)
    assert out_no_resp is not None
    assert out_no_resp.observed_action == "NO_RESPONSE"
    assert out_no_resp.strength == EvidenceStrength.WEAK
