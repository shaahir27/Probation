"""Actual human observations stay distinct from Probation's own effects."""

from datetime import timedelta

import pytest

from probation.core.clock import format_timestamp, parse_timestamp
from probation.core.enums import ActionStatus
from probation.core.lifecycle import HOLD_MINUTES, binding_hash
from probation.core.types import Action
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_actions import ActionStore
from probation.db.lifecycle_attempts import AttemptStore
from probation.workers.resolver import resolve_outcomes
from tests.unit.test_wp6_review_binding import build
from tests.unit.test_wp6_review_binding import review_source as review_source

CREATED_AT = "2026-01-01T10:00:01Z"


def confirmed(conn, kind="REPLY"):
    binding = build(conn, edited_action=kind)
    access = RoleAccess(conn, Role.EXECUTOR)
    actions = ActionStore(access)
    # A licence-2 send is executable only inside its hold window; a label change starts pending.
    initial = ActionStatus.HELD if kind in {"REPLY", "FORWARD"} else ActionStatus.PENDING
    hold_until = (
        format_timestamp(parse_timestamp(CREATED_AT) + timedelta(minutes=HOLD_MINUTES))
        if initial is ActionStatus.HELD
        else None
    )
    actions.create_if_absent(
        Action(
            id="system-action",
            proposal_id="review-proposal",
            pack="mail",
            type=kind,
            params=binding.params,
            level_required=2,
            recallable=kind == "ARCHIVE",
            status=initial,
            hold_until=hold_until,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        ),
        binding,
        "autonomous",
    )
    attempts = AttemptStore(access)
    before = {"payload": {"message": {"message_id": "<system@test.invalid>"}}}
    claim = attempts.prepare(
        "system-action",
        "execute",
        binding_hash(binding),
        before,
        "2026-01-01T10:00:02Z",
        "executor",
    )
    attempts.mark_dispatched(claim, "2026-01-01T10:00:02Z")
    with access.transaction():
        attempts.finish(
            claim, "2026-01-01T10:00:03Z", "confirmed", {"native_ref": "<system@test.invalid>"}
        )
        actions.transition(
            "system-action",
            initial,
            ActionStatus.DONE,
            "2026-01-01T10:00:03Z",
            executed_at="2026-01-01T10:00:02Z",
            claim=claim,
        )


class World:
    def __init__(self, human=False, override=False):
        self.human = human
        self.override = override

    def get_messages(self, **kwargs):
        messages = [
            {
                "message_id": "<system@test.invalid>",
                "from_addr": "owner@test.invalid",
                "received_at": "2026-01-01T10:00:02Z",
                "in_reply_to": "<original@test.invalid>",
                "subject": "Re: Review",
            }
        ]
        if self.human:
            messages.append(
                {
                    **messages[0],
                    "message_id": "<human@test.invalid>",
                    "received_at": "2026-01-01T10:00:04Z",
                }
            )
        return messages

    def get_message(self, message_id, as_of=None):
        return {"labels": []}

    def get_user_actions(self, item_id=None, as_of=None, actor=None):
        return (
            [
                {
                    "id": "human-override",
                    "item_id": item_id,
                    "action_type": "TRASH",
                    "acted_at": "2026-01-01T10:00:04Z",
                    "actor": "user",
                }
            ]
            if self.override
            else []
        )


@pytest.mark.parametrize("review_source", [("REPLY", True)], indirect=True)
def test_system_sent_message_is_not_human_agreement(review_source):
    confirmed(review_source)
    assert (
        resolve_outcomes(
            review_source,
            World(),
            as_of="2026-01-01T10:00:05Z",
            user_addresses=["owner@test.invalid"],
        )
        == 0
    )
    assert review_source.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 0


@pytest.mark.parametrize("review_source", [("REPLY", True)], indirect=True)
def test_later_genuine_human_reply_survives_system_message_filter(review_source):
    confirmed(review_source)
    assert (
        resolve_outcomes(
            review_source,
            World(human=True),
            as_of="2026-01-01T10:00:05Z",
            user_addresses=["owner@test.invalid"],
        )
        == 1
    )
    row = review_source.execute("SELECT details_json FROM outcomes").fetchone()
    assert "<human@test.invalid>" in row[0]


@pytest.mark.parametrize("review_source", [("ARCHIVE", True)], indirect=True)
def test_system_label_state_never_becomes_human_evidence(review_source):
    confirmed(review_source, "ARCHIVE")
    world = World()
    world.get_messages = lambda **kwargs: []
    assert (
        resolve_outcomes(
            review_source,
            world,
            as_of="2026-01-09T10:00:05Z",
            user_addresses=["owner@test.invalid"],
        )
        == 0
    )


@pytest.mark.parametrize("review_source", [("ARCHIVE", True)], indirect=True)
def test_dated_human_override_is_durable_and_deduplicated(review_source):
    confirmed(review_source, "ARCHIVE")
    world = World(override=True)
    world.get_messages = lambda **kwargs: []
    assert (
        resolve_outcomes(
            review_source,
            world,
            as_of="2026-01-01T10:00:05Z",
            user_addresses=["owner@test.invalid"],
        )
        == 1
    )
    assert (
        resolve_outcomes(
            review_source,
            world,
            as_of="2026-01-01T10:00:06Z",
            user_addresses=["owner@test.invalid"],
        )
        == 0
    )
    event = review_source.execute(
        "SELECT kind,source,observed_action FROM outcome_events"
    ).fetchall()
    assert [tuple(row) for row in event] == [("override", "override", None)]
