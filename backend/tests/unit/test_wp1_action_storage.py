"""WP1: local action intent and ledger storage form a caller-safe unit."""

import sqlite3

import pytest

from probation.core.enums import GateDecision
from probation.core.types import Action, Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.proposals import persist_proposal
from probation.workers.executor import Executor


def _proposal(conn: sqlite3.Connection, situation: Situation) -> None:
    persist_proposal(
        RoleAccess(conn, Role.BRAIN),
        Proposal(
            id="action-storage-proposal",
            situation_id=situation.id,
            family=situation.family,
            class_key="mail|request|known",
            action="ARCHIVE",
            p_max=0.99,
            novel=False,
            gate=GateDecision.EXECUTE_UNDO,
            policy_version="wp1",
            features_hash="wp1",
            params={"message_id": "synthetic"},
            proposed_at=situation.occurred_at,
        ),
    )
    conn.commit()


def _create(conn: sqlite3.Connection) -> Action:
    return Executor(conn).create_action(
        "action-storage-proposal",
        "mail",
        "ARCHIVE",
        {"message_id": "synthetic"},
        2,
        True,
        GateDecision.EXECUTE_UNDO,
        "2026-01-01T10:00:00Z",
    )


def test_action_ledger_failure_rolls_back_action_intent(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    _proposal(memory_db, basic_situation)
    memory_db.execute(
        "CREATE TRIGGER reject_action_ledger BEFORE INSERT ON ledger WHEN NEW.kind='action' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        _create(memory_db)
    assert memory_db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0


def test_action_creation_preserves_parent_transaction(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    _proposal(memory_db, basic_situation)
    memory_db.execute("BEGIN")
    _create(memory_db)
    memory_db.rollback()
    assert memory_db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0


def test_retry_does_not_reset_a_completed_action(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    _proposal(memory_db, basic_situation)
    first = _create(memory_db)
    memory_db.execute("UPDATE actions SET status='DONE' WHERE id=?", (first.id,))
    memory_db.commit()
    retry = _create(memory_db)
    assert retry.status.value == "DONE"
    assert memory_db.execute("SELECT count(*) FROM ledger WHERE kind='action'").fetchone()[0] == 1


def test_executor_refuses_to_consume_uncommitted_intent(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    _proposal(memory_db, basic_situation)
    memory_db.execute("BEGIN")
    _create(memory_db)
    with pytest.raises(ValueError):
        Executor(memory_db).process_queue(as_of="2026-01-01T10:01:00Z")
    memory_db.rollback()
    assert memory_db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
