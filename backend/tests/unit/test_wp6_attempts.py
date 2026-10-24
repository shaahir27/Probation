"""D3 execution fences prohibit repeated dispatch and stale completion."""

import sqlite3

import pytest

from probation.core.enums import ActionStatus, GateDecision
from probation.core.lifecycle import ApprovalBinding, LifecycleDenied, StaleClaim, binding_hash
from probation.core.types import Action, Situation
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_actions import ActionStore
from probation.db.lifecycle_attempts import AttemptStore
from probation.db.proposals import persist_proposal
from tests.unit.test_wp1_proposals import proposal


def action_fixture(
    conn: sqlite3.Connection, situation: Situation
) -> tuple[ActionStore, ApprovalBinding]:
    persist_proposal(
        RoleAccess(conn, Role.BRAIN),
        proposal(situation, "ARCHIVE").model_copy(
            update={"gate": GateDecision.EXECUTE_UNDO, "licence_level": 2, "cap": 3}
        ),
    )
    binding = ApprovalBinding(
        owner_id="owner",
        connection_id="synthetic",
        account_id="test",
        resource_id="synthetic-ref",
        source_hash="hash",
        action="ARCHIVE",
        restriction_revision="0",
        params={},
    )
    actions = ActionStore(RoleAccess(conn, Role.EXECUTOR))
    actions.create_if_absent(
        Action(
            id="action",
            proposal_id="wp1-proposal",
            pack="mail",
            type="ARCHIVE",
            params={},
            level_required=2,
            recallable=True,
            created_at="2026-01-01T10:00:01Z",
            updated_at="2026-01-01T10:00:01Z",
        ),
        binding,
        "autonomous",
    )
    return actions, binding


def test_expired_dispatch_is_reconciliation_only_and_stale_worker_cannot_finish(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    actions, binding = action_fixture(memory_db, basic_situation)
    attempts = AttemptStore(RoleAccess(memory_db, Role.EXECUTOR))
    first = attempts.prepare(
        "action",
        "execute",
        binding_hash(binding),
        {"labels": ["INBOX"]},
        "2026-01-01T10:00:02Z",
        "worker-A",
        lease_seconds=2,
    )
    assert first is not None and first.mode == "execute"
    attempts.mark_dispatched(first, "2026-01-01T10:00:03Z")
    second = attempts.prepare(
        "action",
        "execute",
        binding_hash(binding),
        {"labels": []},
        "2026-01-01T10:00:05Z",
        "worker-B",
    )
    assert (
        second is not None
        and second.mode == "reconcile"
        and second.before_state == {"labels": ["INBOX"]}
    )
    with pytest.raises(StaleClaim):
        attempts.finish(first, "2026-01-01T10:00:06Z", "confirmed", {})
    with pytest.raises(LifecycleDenied):
        attempts.mark_dispatched(second, "2026-01-01T10:00:06Z")
    attempts.finish(second, "2026-01-01T10:00:06Z", "confirmed", {"receipt": "synthetic"})
    actions.transition(
        "action",
        ActionStatus.PENDING,
        ActionStatus.DONE,
        "2026-01-01T10:00:06Z",
        executed_at="2026-01-01T10:00:06Z",
        claim=second,
    )
    assert actions.get("action").status == ActionStatus.DONE
    assert (
        attempts.prepare(
            "action", "execute", binding_hash(binding), {}, "2026-01-01T10:00:07Z", "worker-C"
        )
        is None
    )


def test_postdispatch_failure_needs_definitive_noeffect_proof(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    _, binding = action_fixture(memory_db, basic_situation)
    attempts = AttemptStore(RoleAccess(memory_db, Role.EXECUTOR))
    claim = attempts.prepare(
        "action", "execute", binding_hash(binding), {}, "2026-01-01T10:00:02Z", "worker-A"
    )
    assert claim is not None
    attempts.mark_dispatched(claim, "2026-01-01T10:00:03Z")
    with pytest.raises(LifecycleDenied):
        attempts.finish(claim, "2026-01-01T10:00:04Z", "failed", {})
    attempts.mark_unknown(claim, "2026-01-01T10:00:04Z", "connection_lost")
    assert attempts.get("action", "execute").state == "unknown"
