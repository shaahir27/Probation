"""A lost autonomous operation requests a fresh Brain-owned, restricted prediction."""

import sqlite3
from copy import deepcopy

import pytest

from probation.core.enums import GateDecision
from probation.core.history import HistoryView
from probation.core.types import Proposal
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger, verify_ledger
from probation.db.proposals import persist_proposal
from probation.engine.policy import Policy
from probation.engine.prediction import PredictionSnapshot
from probation.workers.brain_followups import process_followups
from probation.workers.executor import Executor
from tests.unit.wp5_exam_fixtures import ControlledNovelty, controlled_reader
from tests.unit.wp6_mail_fixture import NOW, seed


def test_linked_followup_is_fresh_shared_prediction_once_and_never_autonomous(tmp_path):
    conn, world = seed(tmp_path)
    worker = Executor(conn, world)
    action = worker.create_action(
        "proposal",
        "mail",
        "ARCHIVE",
        {"message_id": "<m@test.local>"},
        2,
        True,
        GateDecision.EXECUTE_UNDO,
        NOW,
    )
    at = "2026-10-01T01:01:00Z"
    conn.execute(
        "UPDATE actions SET status='CANCELLED',authority_kind='autonomous',updated_at=? WHERE id=?",
        (at, action.id),
    )
    append_ledger(
        conn,
        "action",
        action.id,
        {
            "action_id": action.id,
            "status": "CANCELLED",
            "reason": "licence_lost",
            "licence_lost_followup_requested": True,
        },
        at,
    )
    conn.commit()
    policy = Policy("email_action")
    policy.fit(
        [{"has_deadline": False}] * 120 + [{"has_deadline": True}] * 120,
        ["ARCHIVE"] * 120 + ["LEAVE"] * 120,
        [NOW] * 240,
        as_of=NOW,
    )
    snapshots = {"email_action": PredictionSnapshot(policy, ControlledNovelty(), "audit", 0.1)}
    future_policy = deepcopy(policy)
    future_policy.as_of = "2027-01-01T00:00:00Z"
    assert (
        process_followups(
            conn,
            as_of=at,
            snapshots={
                "email_action": PredictionSnapshot(future_policy, ControlledNovelty(), "audit", 0.1)
            },
            reader_callable=controlled_reader,
        )
        == []
    )
    later = "2026-10-01T01:02:00Z"
    ids = process_followups(
        conn, as_of=later, snapshots=snapshots, reader_callable=controlled_reader
    )
    assert len(ids) == 1
    result = conn.execute("SELECT * FROM proposals WHERE id=?", (ids[0],)).fetchone()
    assert result["gate"] in {"SUGGEST", "ASK", "SHADOW"}
    assert result["policy_version"] == policy.policy_version
    assert result["followup_of_action_id"] == action.id
    original = dict(conn.execute("SELECT * FROM proposals WHERE id='proposal'").fetchone())
    candidate = Proposal(
        **{
            **original,
            "id": "another",
            "probs": {"ARCHIVE": 1},
            "reasons": [],
            "params": {},
            "explanation": {},
            "web": {},
            "followup_of_action_id": action.id,
            "cap": 1,
            "proposed_at": later,
        }
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        persist_proposal(RoleAccess(conn, Role.BRAIN), candidate)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        persist_proposal(
            RoleAccess(conn, Role.BRAIN),
            candidate.model_copy(update={"followup_of_action_id": None}),
        )
    with pytest.raises(ValueError, match="authority followup"):
        persist_proposal(
            RoleAccess(conn, Role.BRAIN),
            candidate.model_copy(update={"followup_of_action_id": "missing"}),
        )
    assert conn.execute("SELECT gate FROM proposals WHERE id='proposal'").fetchone()[0] == "SUGGEST"
    assert (
        process_followups(conn, as_of=later, snapshots=snapshots, reader_callable=controlled_reader)
        == []
    )
    assert conn.execute("SELECT count(*) FROM actions").fetchone()[0] == 1
    assert verify_ledger(conn)[0]
    assert len(HistoryView(conn, at).followup_records()) == 1
    assert (
        HistoryView(conn, later).frozen().permission_history_digest()
        == HistoryView(conn, later).permission_history_digest()
    )
    world.close()
    conn.close()
