"""WP1: the final proposal, ledger entry and validated draft commit as one unit."""

import sqlite3

import pytest

from probation.core.enums import GateDecision
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess


def proposal(situation: Situation, action: str = "REPLY") -> Proposal:
    return Proposal(
        id="wp1-proposal",
        situation_id=situation.id,
        family=situation.family,
        class_key="mail|request|known",
        action=action,
        p_max=0.99,
        novel=False,
        licence_level=1,
        cap=2,
        gate=GateDecision.SUGGEST,
        params={"message_id": "synthetic-message"},
        explanation={"reason": "synthetic"},
        policy_version="synthetic-v1",
        features_hash="synthetic-features",
        proposed_at=situation.occurred_at,
    )


def test_proposal_precedes_its_draft_and_is_retry_idempotent(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    from probation.db.proposals import DraftRecord, persist_proposal

    draft = DraftRecord(
        body_text="Thank you for the update.",
        needs_user_input=False,
        validator_ok=True,
        model_id="synthetic",
        prompt_version="v1",
        created_at=basic_situation.occurred_at,
    )
    access = RoleAccess(memory_db, Role.BRAIN)
    first = persist_proposal(access, proposal(basic_situation), draft=draft)
    second = persist_proposal(access, proposal(basic_situation), draft=draft)
    assert first.ledger_seq == second.ledger_seq > 0
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 1
    assert memory_db.execute("SELECT body_text FROM drafts").fetchone()[0] == draft.body_text


def test_draft_insert_failure_rolls_back_proposal_and_ledger(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    from probation.db.proposals import DraftRecord, persist_proposal

    memory_db.execute(
        "CREATE TRIGGER synthetic_draft_failure BEFORE INSERT ON drafts BEGIN SELECT RAISE(ABORT, 'synthetic draft failure'); END"
    )
    draft = DraftRecord(
        body_text="Thank you for the update.",
        needs_user_input=False,
        validator_ok=True,
        model_id="synthetic",
        prompt_version="v1",
        created_at=basic_situation.occurred_at,
    )
    with pytest.raises(sqlite3.IntegrityError, match="synthetic draft failure"):
        persist_proposal(RoleAccess(memory_db, Role.BRAIN), proposal(basic_situation), draft=draft)
    assert memory_db.execute("SELECT count(*) FROM proposals").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0


def test_retry_cannot_change_immutable_parameters(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    from probation.db.proposals import persist_proposal

    access = RoleAccess(memory_db, Role.BRAIN)
    original = proposal(basic_situation, "ARCHIVE")
    persist_proposal(access, original)
    with pytest.raises(ValueError):
        persist_proposal(
            access, original.model_copy(update={"params": {"message_id": "different"}})
        )
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 1


@pytest.mark.parametrize("action", ["ABSTAIN", "LEAVE", "NO_RESPONSE", "NONE"])
def test_noop_predictions_never_form_permission_evidence(
    memory_db: sqlite3.Connection, basic_situation: Situation, action: str
) -> None:
    from probation.db.proposals import persist_proposal
    from probation.engine.evidence import aggregate_evidence

    original = proposal(basic_situation, action).model_copy(
        update={"gate": GateDecision.SHADOW, "cap": 0}
    )
    persist_proposal(RoleAccess(memory_db, Role.BRAIN), original)
    with memory_db:
        memory_db.execute(
            "INSERT INTO outcomes(situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq) VALUES (?, ?, 'STRONG', 'footprint', '2026-01-02T10:00:00Z', '2026-01-02T10:00:00Z', '{}', 0)",
            (basic_situation.id, action),
        )
    assert aggregate_evidence(memory_db, as_of="2026-01-03T00:00:00Z") == {}
