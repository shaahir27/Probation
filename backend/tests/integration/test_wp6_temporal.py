"""Fifty fixed cuts keep new event/control projections stable after future writes."""

import random
from datetime import timedelta

import pytest

from probation.core.clock import format_timestamp, parse_timestamp
from probation.core.history import HistoryView
from probation.core.lifecycle import CommandIntent, CommandScope, OutcomeEvent
from probation.db.access import Role, RoleAccess
from probation.db.ledger import verify_ledger
from probation.db.lifecycle_commands import CommandStore
from probation.db.lifecycle_events import EventStore
from probation.workers.restrictions import process_restriction_commands
from tests.unit.wp6_mail_fixture import NOW, seed


def projection(view):
    return (
        view.permission_history_digest(),
        view.permission_records(),
        view.get_decision_projection(),
        view.get_training_records("email_action"),
        view.control_records(),
        view.followup_records(),
    )


@pytest.mark.parametrize("seed_number", range(50))
def test_future_events_and_control_completion_cannot_change_a_cut(tmp_path, seed_number):
    conn, world = seed(tmp_path)
    rng = random.Random(seed_number)
    cut = format_timestamp(parse_timestamp(NOW) + timedelta(seconds=rng.randrange(10, 3600)))
    future = format_timestamp(parse_timestamp(cut) + timedelta(seconds=rng.randrange(1, 600)))
    resolver = RoleAccess(conn, Role.RESOLVER)
    with resolver.transaction():
        EventStore(resolver).append(
            OutcomeEvent(
                event_id="human",
                situation_id="sit",
                proposal_id="proposal",
                kind="footprint",
                source="footprint",
                source_key="human",
                observed_action="ARCHIVE",
                strength="STRONG",
                observed_at="2026-10-01T01:00:01Z",
                known_at="2026-10-01T01:00:01Z",
            )
        )
    commands = CommandStore(RoleAccess(conn, Role.API))
    commands.submit(
        CommandIntent(
            request_id="pause",
            owner_id="owner",
            type="pause",
            scope=CommandScope(connection_id="connection", account_id="account"),
            created_at=NOW,
        )
    )
    view = HistoryView(conn, cut)
    before = projection(view)
    frozen = view.frozen()
    assert projection(frozen) == before
    with resolver.transaction():
        EventStore(resolver).append(
            OutcomeEvent(
                event_id="later-correction",
                situation_id="sit",
                proposal_id="proposal",
                kind="override",
                source="override",
                source_key="later-correction",
                strength="STRONG",
                observed_at=future,
                known_at=future,
            )
        )
    commands.submit(
        CommandIntent(
            request_id="revoke",
            owner_id="owner",
            type="revoke",
            scope=CommandScope(connection_id="connection", account_id="account"),
            created_at=future,
        )
    )
    process_restriction_commands(conn, as_of=future)
    assert projection(view) == before
    assert projection(frozen) == before
    assert projection(HistoryView(conn, cut).frozen()) == before
    assert HistoryView(conn, future).permission_history_digest() != before[0]
    assert verify_ledger(conn) == (True, None)
    world.close()
    conn.close()
