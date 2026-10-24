"""Immutable decisions and owned corrections share atomic ledger/receipt units."""

import sqlite3

import pytest

from probation.core.enums import ActionStatus
from probation.core.lifecycle import (
    LifecycleConflict,
    LifecycleDenied,
    OutcomeEvent,
    StaleClaim,
    binding_hash,
)
from probation.core.types import Action, Situation
from probation.db.access import AccessError, Role, RoleAccess
from probation.db.ledger import verify_ledger
from probation.db.lifecycle_actions import ActionStore
from probation.db.lifecycle_attempts import AttemptStore
from probation.db.lifecycle_events import EventStore
from probation.db.lifecycle_receipts import ReceiptStore
from probation.db.lifecycle_responses import ResponseStore
from tests.unit.test_wp6_storage_edges import response_fixture


def test_event_and_consumption_receipt_rollback_together(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    request = response_fixture(memory_db, basic_situation)
    ResponseStore(RoleAccess(memory_db, Role.API)).submit(request)
    resolver = RoleAccess(memory_db, Role.RESOLVER)
    event = OutcomeEvent(
        event_id="decision",
        situation_id=basic_situation.id,
        proposal_id=request.proposal_id,
        response_id=request.request_id,
        kind="decision",
        source="user_response",
        source_key=request.request_id,
        decision="accept",
        observed_action="ARCHIVE",
        strength="STRONG",
        observed_at=request.responded_at,
        known_at=request.responded_at,
    )
    with pytest.raises(RuntimeError), resolver.transaction():
        receipt = ReceiptStore(resolver).claim_response(
            request.request_id, now=request.responded_at, owner="resolver"
        )
        assert receipt is not None
        stored = EventStore(resolver).append(event)
        ReceiptStore(resolver).finish(
            receipt,
            now=request.responded_at,
            status="succeeded",
            result={"event_id": stored.event_id},
        )
        raise RuntimeError("synthetic interruption")
    assert memory_db.execute("SELECT count(*) FROM outcome_events").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM ledger WHERE kind='outcome'").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 0
    with resolver.transaction():
        first = EventStore(resolver).append(event)
        assert EventStore(resolver).append(event) == first
    assert verify_ledger(memory_db) == (True, None)
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute("UPDATE outcome_events SET observed_action='TRASH'")
    memory_db.rollback()
    with pytest.raises(AccessError), RoleAccess(memory_db, Role.EXECUTOR).transaction():
        EventStore(RoleAccess(memory_db, Role.EXECUTOR)).append(event)


def test_reject_has_no_chosen_training_label(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    request = response_fixture(memory_db, basic_situation).model_copy(update={"response": "reject"})
    ResponseStore(RoleAccess(memory_db, Role.API)).submit(request)
    access = RoleAccess(memory_db, Role.RESOLVER)
    event = OutcomeEvent(
        event_id="rejected",
        situation_id=basic_situation.id,
        proposal_id=request.proposal_id,
        response_id=request.request_id,
        kind="decision",
        source="user_response",
        source_key=request.request_id,
        decision="reject",
        strength="STRONG",
        observed_at=request.responded_at,
        known_at=request.responded_at,
    )
    with access.transaction():
        EventStore(access).append(event)
    assert memory_db.execute("SELECT observed_action FROM outcome_events").fetchone()[0] is None


def test_executor_correction_requires_own_confirmed_effect_and_undo_request(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    initial = response_fixture(memory_db, basic_situation, executing=True)
    access = RoleAccess(memory_db, Role.EXECUTOR)
    actions = ActionStore(access)
    attempts = AttemptStore(access)
    binding = initial.reviewed_payload
    action = Action(
        id="archive",
        proposal_id=initial.proposal_id,
        pack="mail",
        type="ARCHIVE",
        params=binding.params,
        level_required=2,
        recallable=True,
        created_at=initial.responded_at,
        updated_at=initial.responded_at,
    )
    actions.create_if_absent(action, binding, "autonomous")
    time2 = "2026-01-01T10:00:02Z"
    claim = attempts.prepare(
        action.id, "execute", binding_hash(binding), {"labels": ["INBOX"]}, time2, "executor"
    )
    assert claim is not None
    attempts.mark_dispatched(claim, time2)
    with access.transaction():
        attempts.finish(claim, time2, "confirmed", {"receipt": "effect"})
        actions.transition(
            action.id,
            ActionStatus.PENDING,
            ActionStatus.DONE,
            time2,
            executed_at=time2,
            claim=claim,
        )
    undo_time = "2026-01-01T10:00:03Z"
    undo = initial.model_copy(
        update={
            "request_id": "undo",
            "response": "undo",
            "action_id": action.id,
            "responded_at": undo_time,
        }
    )
    ResponseStore(RoleAccess(memory_db, Role.API)).submit(undo)
    event = OutcomeEvent(
        event_id="undo-event",
        situation_id=basic_situation.id,
        proposal_id=initial.proposal_id,
        action_id=action.id,
        response_id=undo.request_id,
        kind="undo",
        source="undo",
        source_key="archive:undo",
        strength="STRONG",
        observed_at=undo_time,
        known_at=undo_time,
    )
    with pytest.raises(LifecycleDenied), access.transaction():
        EventStore(access).append(event)
    claim2 = attempts.prepare(
        action.id, "undo", binding_hash(binding), {"labels": []}, undo_time, "executor"
    )
    assert claim2 is not None
    attempts.mark_dispatched(claim2, undo_time)
    with access.transaction():
        attempts.finish(claim2, undo_time, "confirmed", {"receipt": "undo"})
        actions.transition(
            action.id, ActionStatus.DONE, ActionStatus.UNDONE, undo_time, claim=claim2
        )
        EventStore(access).append(event)
    assert (
        memory_db.execute("SELECT count(*) FROM outcome_events WHERE kind='undo'").fetchone()[0]
        == 1
    )
    assert verify_ledger(memory_db) == (True, None)


def test_typed_event_store_refuses_forged_source_and_consumer(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    initial = response_fixture(memory_db, basic_situation)
    ResponseStore(RoleAccess(memory_db, Role.API)).submit(initial)
    event = OutcomeEvent(
        event_id="forged",
        situation_id=basic_situation.id,
        proposal_id=initial.proposal_id,
        kind="footprint",
        source="undo",
        source_key="forged",
        strength="STRONG",
        observed_action="ARCHIVE",
        observed_at=initial.responded_at,
        known_at=initial.responded_at,
    )
    resolver = RoleAccess(memory_db, Role.RESOLVER)
    with pytest.raises(LifecycleDenied), resolver.transaction():
        EventStore(resolver).append(event)
    with pytest.raises(StaleClaim, match="future_request"):
        ReceiptStore(resolver).claim_response(
            initial.request_id, now="2025-01-01T00:00:00Z", owner="forged"
        )
    assert memory_db.execute("SELECT count(*) FROM outcome_events").fetchone()[0] == 0


def test_cross_authority_pending_collision_cannot_replace_autonomous_intent(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    request = response_fixture(memory_db, basic_situation, executing=True)
    binding = request.reviewed_payload
    access = RoleAccess(memory_db, Role.EXECUTOR)
    actions = ActionStore(access)
    original = Action(
        id="autonomous",
        proposal_id=request.proposal_id,
        pack="mail",
        type="ARCHIVE",
        params=binding.params,
        level_required=2,
        recallable=True,
        created_at=request.responded_at,
        updated_at=request.responded_at,
    )
    actions.create_if_absent(original, binding, "autonomous")
    ResponseStore(RoleAccess(memory_db, Role.API)).submit(request)
    explicit = original.model_copy(update={"id": "explicit", "level_required": 1})
    with pytest.raises(LifecycleConflict, match="resource_action_already_pending"):
        actions.create_if_absent(explicit, binding, "explicit_user", request.request_id)
    assert actions.get(original.id) == original
    assert memory_db.execute("SELECT count(*) FROM actions").fetchone()[0] == 1
