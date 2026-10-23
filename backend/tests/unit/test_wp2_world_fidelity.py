"""WP2 world fidelity: an as-of projection must neither invent nor reveal a later state.

Authority: docs/CHANGES_IMPLEMENTATION_PLAN.md sections 6.2.1 and 6.2.5, docs/CONTRACT.md I-6.

A world.db stores the state every item had when the world was created, plus a dated
`user_actions` stream that evolves it. Two failures are possible and pull in opposite
directions, so both are pinned here:

* projecting the stored columns when they actually hold the *final* state leaks an outcome
  that has not happened yet;
* refusing to project them at all misreports the owner's own sent mail and self-organized
  events, which legitimately start out as SENT and ACCEPTED.

The `state_model` declaration written by the generator is what separates the two.
"""

from pathlib import Path

from probation.synth.world import SimWorld

OWNER = "meena.k@national.ac.in"
BEFORE_ALL = "2026-02-10T07:00:00Z"
DOWNLOADED = "2026-02-10T08:00:00Z"
RECEIVED = "2026-02-10T09:00:00Z"
ACTED_AT = "2026-02-11T09:00:00Z"
JUST_BEFORE_ACT = "2026-02-11T08:59:59Z"
AFTER_ALL = "2026-02-12T09:00:00Z"

INBOUND_ID = "<in@national.ac.in>"
SENT_ID = "<sent@national.ac.in>"
LATER_ID = "<later@national.ac.in>"
INVITE_UID = "inv-1@national.ac.in"
OWN_EVENT_UID = "own-1@national.ac.in"


def _populate(world: SimWorld) -> None:
    """One inbound message, the owner's own sent mail, a later arrival, two events, one file."""
    world.add_message(
        msg_id="m-in",
        message_id=INBOUND_ID,
        thread_id="t1",
        from_addr="Prof <p@national.ac.in>",
        to_addr=OWNER,
        subject="Lab report",
        body="body",
        labels=["INBOX"],
        received_at=RECEIVED,
    )
    world.add_message(
        msg_id="m-sent",
        message_id=SENT_ID,
        thread_id="t1",
        from_addr=f"Meena <{OWNER}>",
        to_addr="p@national.ac.in",
        subject="Re: Lab report",
        body="body",
        labels=["SENT"],
        received_at=RECEIVED,
        in_reply_to=INBOUND_ID,
    )
    world.add_message(
        msg_id="m-later",
        message_id=LATER_ID,
        thread_id="t2",
        from_addr="p@national.ac.in",
        to_addr=OWNER,
        subject="Later",
        body="body",
        labels=["INBOX"],
        received_at=ACTED_AT,
    )
    world.add_event(
        event_id="e-invite",
        uid=INVITE_UID,
        title="Office hours",
        description="",
        start_time=AFTER_ALL,
        end_time=AFTER_ALL,
        organizer="p@national.ac.in",
        attendees=[OWNER],
    )
    world.add_event(
        event_id="e-own",
        uid=OWN_EVENT_UID,
        title="Study block",
        description="",
        start_time=AFTER_ALL,
        end_time=AFTER_ALL,
        organizer=OWNER,
        attendees=[OWNER],
        my_status="ACCEPTED",
    )
    world.add_file(
        file_id="f1",
        path="Downloads/report.pdf",
        filename="report.pdf",
        ext=".pdf",
        size_bytes=1,
        origin_url="",
        downloaded_at=DOWNLOADED,
        sha256="h",
    )


def _build(tmp_path: Path, *, declared: bool) -> SimWorld:
    world = SimWorld(tmp_path / "world.db", user_addresses=[OWNER])
    _populate(world)
    if declared:
        world.declare_initial_state()
    return world


def test_a_declared_world_keeps_the_owners_own_sent_mail_out_of_the_inbox(tmp_path: Path) -> None:
    """The owner's reply is SENT from creation; projecting it to INBOX invents a state."""
    world = _build(tmp_path, declared=True)
    try:
        sent = world.get_message(SENT_ID, as_of=AFTER_ALL)
        assert sent is not None
        assert sent["labels"] == ["SENT"]
    finally:
        world.close()


def test_a_declared_world_keeps_a_self_organized_event_accepted(tmp_path: Path) -> None:
    """An event the owner organized is accepted from creation, not awaiting a response."""
    world = _build(tmp_path, declared=True)
    try:
        own = world.get_event(OWN_EVENT_UID, as_of=AFTER_ALL)
        assert own is not None
        assert own["my_status"] == "ACCEPTED"
    finally:
        world.close()


def test_an_undeclared_world_fails_closed_instead_of_revealing_a_baked_final_state(
    tmp_path: Path,
) -> None:
    """Without the declaration, only a dated footprint may move a label.

    This is the guard behind the C9 hazard: honouring the stored columns unconditionally would
    let a world that recorded its final ARCHIVED label report that archive at an `as_of` before
    the owner ever acted, which is a peek (CONTRACT I-6).
    """
    world = SimWorld(tmp_path / "world.db", user_addresses=[OWNER])
    try:
        _populate(world)
        world.add_message(
            msg_id="m-final",
            message_id="<final@national.ac.in>",
            thread_id="t3",
            from_addr="p@national.ac.in",
            to_addr=OWNER,
            subject="Already archived",
            body="body",
            labels=["ARCHIVED"],
            received_at=RECEIVED,
        )
        assert world.stores_initial_state is False
        projected = world.get_message("<final@national.ac.in>", as_of=RECEIVED)
        assert projected is not None
        assert projected["labels"] == ["INBOX"]

        own = world.get_event(OWN_EVENT_UID, as_of=AFTER_ALL)
        assert own is not None
        assert own["my_status"] == "NEEDS_ACTION"
    finally:
        world.close()


def test_a_footprint_evolves_a_declared_world_only_from_its_own_timestamp(tmp_path: Path) -> None:
    """The archive is visible at `acted_at` and not one second earlier."""
    world = _build(tmp_path, declared=True)
    try:
        world.record_user_action(
            action_id="a1",
            item_id=INBOUND_ID,
            action_type="ARCHIVE",
            acted_at=ACTED_AT,
        )
        before = world.get_message(INBOUND_ID, as_of=JUST_BEFORE_ACT)
        at = world.get_message(INBOUND_ID, as_of=ACTED_AT)
        assert before is not None and before["labels"] == ["INBOX"]
        assert at is not None and at["labels"] == ["ARCHIVED"]

        # An invite stays visible before it starts; only its response is projected.
        invite_before = world.get_event(INVITE_UID, as_of=JUST_BEFORE_ACT)
        assert invite_before is not None and invite_before["my_status"] == "NEEDS_ACTION"
        world.record_user_action(
            action_id="a2", item_id=INVITE_UID, action_type="ACCEPT", acted_at=ACTED_AT
        )
        invite_at = world.get_event(INVITE_UID, as_of=ACTED_AT)
        assert invite_at is not None and invite_at["my_status"] == "ACCEPTED"
        still_before = world.get_event(INVITE_UID, as_of=JUST_BEFORE_ACT)
        assert still_before is not None and still_before["my_status"] == "NEEDS_ACTION"
    finally:
        world.close()


def test_an_item_that_has_not_arrived_yet_is_not_visible(tmp_path: Path) -> None:
    """`as_of` bounds existence, not just state, wherever an arrival timestamp exists."""
    world = _build(tmp_path, declared=True)
    try:
        assert world.get_message(LATER_ID, as_of=RECEIVED) is None
        assert world.get_message(LATER_ID, as_of=ACTED_AT) is not None

        visible = {m["message_id"] for m in world.get_messages(as_of=RECEIVED)}
        assert LATER_ID not in visible
        assert INBOUND_ID in visible

        assert world.get_files(as_of=BEFORE_ALL) == []
        assert [f["path"] for f in world.get_files(as_of=DOWNLOADED)] == ["Downloads/report.pdf"]
    finally:
        world.close()


def test_the_last_move_before_the_observation_point_decides_where_a_file_is(tmp_path: Path) -> None:
    """A file relocated twice is where the second move put it, not the first."""
    world = _build(tmp_path, declared=True)
    try:
        world.record_user_action(
            action_id="m1",
            item_id="Downloads/report.pdf",
            action_type="MOVE_TO_FOLDER",
            acted_at=RECEIVED,
            details={"destination_folder": "College", "destination_path": "College/report.pdf"},
        )
        world.record_user_action(
            action_id="m2",
            item_id="Downloads/report.pdf",
            action_type="MOVE_TO_FOLDER",
            acted_at=ACTED_AT,
            details={
                "destination_folder": "College/CO301",
                "destination_path": "College/CO301/report.pdf",
            },
        )
        assert [f["path"] for f in world.get_files(as_of=JUST_BEFORE_ACT)] == ["College/report.pdf"]
        assert [f["path"] for f in world.get_files(as_of=AFTER_ALL)] == ["College/CO301/report.pdf"]
    finally:
        world.close()


def test_an_unplaceable_arrival_time_fails_closed(tmp_path: Path) -> None:
    """A timestamp that cannot be parsed is treated as not yet present, never as present."""
    world = SimWorld(tmp_path / "world.db", user_addresses=[OWNER])
    try:
        world.add_message(
            msg_id="m-bad",
            message_id="<bad@national.ac.in>",
            thread_id="t4",
            from_addr="p@national.ac.in",
            to_addr=OWNER,
            subject="Bad time",
            body="body",
            labels=["INBOX"],
            received_at="sometime last week",
        )
        assert world.get_message("<bad@national.ac.in>", as_of=AFTER_ALL) is None
        assert world.get_messages(as_of=AFTER_ALL) == []
    finally:
        world.close()


def test_a_reopened_world_still_knows_whose_world_it_is(tmp_path: Path) -> None:
    """Identity survives a reopen so a resolver can still attribute the owner's own mail."""
    path = tmp_path / "world.db"
    with SimWorld(path, user_addresses=[OWNER]) as world:
        _populate(world)
        world.declare_initial_state()

    with SimWorld(path) as reopened:
        assert reopened.user_addresses == [OWNER]
        assert reopened.stores_initial_state is True
