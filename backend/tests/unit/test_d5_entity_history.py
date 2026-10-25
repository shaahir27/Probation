"""D5 familiarity uses genuine bounded immutable user decisions only."""

import sqlite3

import pytest

from probation.core.history import HistoryView
from probation.core.types import Situation


@pytest.mark.parametrize(
    "actor,strength,retrospective,expected",
    [
        ("user", "STRONG", False, True),
        ("executor", "STRONG", False, False),
        ("system", "STRONG", False, False),
        ("unknown", "STRONG", False, False),
        (None, "STRONG", False, False),
        ("user", "WEAK", False, False),
        ("user", "STRONG", True, False),
    ],
)
def test_d5_known_domains_use_actual_bounded_immutable_user_cohort(
    memory_db: sqlite3.Connection,
    actor: str | None,
    strength: str,
    retrospective: bool,
    expected: bool,
) -> None:
    from probation.core.enums import GateDecision
    from probation.core.types import Proposal
    from probation.db.access import Role, RoleAccess
    from probation.db.ledger import append_ledger
    from probation.db.proposals import persist_proposal

    at = "2026-10-25T10:00:00Z"
    memory_db.execute(
        "INSERT INTO sources VALUES ('source','mail','synthetic','synthetic',?)", (at,)
    )
    memory_db.execute(
        "INSERT INTO raw_items VALUES ('raw','source','mail','mail_in','native',?,?,?,?)",
        (at, at, "{}", "hash"),
    )
    situation = Situation(
        id="sit",
        pack="mail",
        family="email_action",
        raw_item_id="raw",
        occurred_at=at,
        sender_key="sender@unknown.example",
        content_hash="hash",
    )
    memory_db.execute(
        """INSERT INTO situations
        (id,raw_item_id,pack,family,occurred_at,sender_key,content_hash,created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (
            situation.id,
            situation.raw_item_id,
            situation.pack,
            situation.family,
            situation.occurred_at,
            situation.sender_key,
            situation.content_hash,
            situation.occurred_at,
        ),
    )
    memory_db.commit()
    proposal = Proposal(
        id="proposal",
        situation_id=situation.id,
        family=situation.family,
        class_key="mail|request|unknown",
        action="REPLY",
        probs={"REPLY": 1.0},
        p_max=1,
        novel=False,
        licence_level=1,
        cap=1,
        gate=GateDecision.SUGGEST,
        policy_version="test",
        features_hash="test",
        proposed_at=situation.occurred_at,
    )
    persist_proposal(RoleAccess(memory_db, Role.BRAIN), proposal)
    outcome = {
        "situation_id": situation.id,
        "proposal_id": proposal.id,
        "source": "footprint",
        "strength": strength,
        "observed_action": "REPLY",
        "known_at": "2026-10-25T11:00:00Z",
        "retrospective": retrospective,
    }
    if actor is not None:
        outcome["actor"] = actor
    append_ledger(memory_db, "outcome", "event", outcome, "2026-10-25T11:00:00Z")
    memory_db.commit()
    assert HistoryView(memory_db, "2026-10-25T10:59:59Z").known_entity_senders() == set()
    known = HistoryView(memory_db, "2026-10-25T11:00:00Z").known_entity_senders()
    assert known == ({"sender@unknown.example"} if expected else set())
