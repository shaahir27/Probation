"""Correction review is durable, bounded, idempotent and Examiner-owned."""

import sqlite3
from pathlib import Path

import pytest

from probation.core.enums import GateDecision
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.connection import get_role_connection, init_db
from probation.db.ledger import append_ledger, verify_ledger
from probation.db.proposals import persist_proposal
from probation.workers.drift import has_pending_drift, review_outcome_events


def seed_corrections(conn: sqlite3.Connection, sit: Situation) -> None:
    persist_proposal(
        RoleAccess(conn, Role.BRAIN),
        Proposal(
            id="correction-proposal",
            situation_id=sit.id,
            family=sit.family,
            class_key="mail|known",
            action="ARCHIVE",
            p_max=0.99,
            novel=False,
            gate=GateDecision.SHADOW,
            proposed_at=sit.occurred_at,
            policy_version="wp1",
            features_hash="wp1",
        ),
    )
    for day in [2, 3]:
        append_ledger(
            conn,
            "outcome",
            f"correction-{day}",
            {
                "situation_id": sit.id,
                "observed_action": "UNDO",
                "strength": "STRONG",
                "source": "undo",
                "known_at": f"2026-01-0{day}T00:00:00Z",
            },
            f"2026-01-0{day}T00:00:00Z",
        )
    conn.commit()


def test_corrections_survive_review_restart_and_future_cut(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    seed_corrections(memory_db, basic_situation)
    assert has_pending_drift(memory_db, "mail|known", "ARCHIVE", "2026-01-02T00:00:00Z")
    assert review_outcome_events(memory_db, as_of="2026-01-02T00:00:00Z") == 1
    assert not has_pending_drift(memory_db, "mail|known", "ARCHIVE", "2026-01-02T00:00:00Z")
    assert memory_db.execute("SELECT last_alarm_at FROM drift_state").fetchone()[0] is None
    assert review_outcome_events(memory_db, as_of="2026-01-03T00:00:00Z") == 1
    assert (
        memory_db.execute("SELECT last_alarm_at FROM drift_state").fetchone()[0]
        == "2026-01-03T00:00:00Z"
    )
    assert review_outcome_events(memory_db, as_of="2026-01-03T00:00:00Z") == 0
    assert (
        memory_db.execute("SELECT count(*) FROM ledger WHERE kind='drift_alarm'").fetchone()[0] == 1
    )
    assert verify_ledger(memory_db)[0]


def test_failed_review_rolls_back_state_receipt_and_alarm(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    seed_corrections(memory_db, basic_situation)
    memory_db.execute(
        "CREATE TRIGGER reject_review BEFORE INSERT ON drift_receipts BEGIN SELECT RAISE(ABORT,'synthetic'); END"
    )
    memory_db.commit()
    with pytest.raises(sqlite3.DatabaseError):
        review_outcome_events(memory_db, as_of="2026-01-03T00:00:00Z")
    assert memory_db.execute("SELECT count(*) FROM drift_state").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM drift_receipts").fetchone()[0] == 0
    assert (
        memory_db.execute("SELECT count(*) FROM ledger WHERE kind='drift_alarm'").fetchone()[0] == 0
    )


def test_executor_cannot_write_examiner_state_or_receipts(tmp_path: Path) -> None:
    path = tmp_path / "drift-roles.db"
    init_db(path)
    with get_role_connection(path, Role.EXECUTOR) as executor:
        for table in ["drift_state", "drift_receipts"]:
            with pytest.raises(sqlite3.DatabaseError):
                executor.execute(f"DELETE FROM {table}")


def test_pending_review_blocks_even_an_injected_licence_checker(
    memory_db: sqlite3.Connection, basic_situation: Situation, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probation.packs.registry import registry
    from probation.workers.executor import Executor

    seed_corrections(memory_db, basic_situation)
    calls: list[str] = []

    def forbidden_adapter(pack: str) -> None:
        calls.append(pack)
        raise AssertionError("Adapter must not be loaded before review")

    executor = Executor(memory_db, licence_checker=lambda *args: 3)
    executor.create_action(
        proposal_id="correction-proposal",
        pack="mail",
        action_type="ARCHIVE",
        params={"message_id": "synthetic"},
        level_required=2,
        recallable=True,
        gate_decision=GateDecision.EXECUTE_UNDO,
        as_of="2026-01-01T11:00:00Z",
    )
    memory_db.commit()
    monkeypatch.setattr(registry, "get", forbidden_adapter)
    result = executor.process_queue(as_of="2026-01-02T00:00:00Z")
    assert len(result) == 1 and result[0].error == "Drift review pending"
    assert calls == []
