"""D2 evidence: immutable prospective commitments, never mutable final state."""

import sqlite3

import pytest

from probation.core.enums import LedgerKind
from probation.db.access import Role, RoleAccess
from probation.engine.evidence import aggregate_evidence

PAIR = ("mail|request|known", "ARCHIVE")
T = "2026-06-01T00:00:00Z"
P = "2026-05-31T10:00:00.123456Z"
OUTCOME_TIME = "2026-05-31T11:00:00Z"


def seed(
    conn: sqlite3.Connection,
    *,
    gate="SUGGEST",
    action="ARCHIVE",
    outcome="ARCHIVE",
    strength="STRONG",
    source="footprint",
    committed=True,
    details=None,
):
    conn.execute("INSERT INTO sources VALUES ('s','mail','synthetic','fixture',?)", (P,))
    conn.execute(
        "INSERT INTO raw_items VALUES ('r','s','mail','mail_in','r',?,?, '{}','h')", (P, P)
    )
    conn.execute(
        """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,content_hash,created_at)
                 VALUES ('x','r','mail','email_action',?,'h',?)""",
        (P, P),
    )
    payload = {
        "situation_id": "x",
        "class_key": PAIR[0],
        "action": action,
        "gate": gate,
        "policy_version": "fitted",
        **(details or {}),
    }
    seq = (
        RoleAccess(conn, Role.BRAIN).append_ledger(LedgerKind.PROPOSAL, "p", payload, created_at=P)
        if committed
        else 0
    )
    conn.execute(
        """INSERT INTO proposals(id,situation_id,family,class_key,action,probs_json,p_max,
       novelty,novel,licence_level,cap,gate,reasons_json,policy_version,features_hash,proposed_at,ledger_seq)
       VALUES ('p','x','email_action',?,?,'{}',.99,0,0,1,3,?,'[]','fitted','h',?,?)""",
        (PAIR[0], action, gate, P, seq),
    )
    event = {
        "situation_id": "x",
        "observed_action": outcome,
        "strength": strength,
        "source": source,
        "known_at": OUTCOME_TIME,
    }
    event_seq = RoleAccess(conn, Role.RESOLVER).append_ledger(
        LedgerKind.OUTCOME, "x", event, created_at=OUTCOME_TIME
    )
    conn.execute(
        "INSERT INTO outcomes VALUES ('x',?,?,?,?,?,'{}',?)",
        (outcome, strength, source, OUTCOME_TIME, OUTCOME_TIME, event_seq),
    )
    conn.commit()


def test_mutable_outcome_cannot_rewrite_evidence(memory_db):
    seed(memory_db)
    memory_db.execute("UPDATE outcomes SET observed_action='TRASH',source='undo'")
    result = aggregate_evidence(memory_db, T, persist=False)[PAIR]
    assert (result.n_strong, result.k_strong) == (1, 1)


@pytest.mark.parametrize(
    "committed,details",
    [(False, None), (True, {"retrospective": True}), (True, {"evidence_context": "backfill"})],
)
def test_uncommitted_or_backfilled_predictions_do_not_qualify(memory_db, committed, details):
    seed(memory_db, committed=committed, details=details)
    assert PAIR not in aggregate_evidence(memory_db, T, persist=False)


def test_rejection_disagrees_without_policy_label_and_correction_is_not_a_vote(memory_db):
    seed(memory_db, outcome="REJECT", source="user_response")
    access = RoleAccess(memory_db, Role.EXAMINER)
    # Append only: later correction cannot change the earlier decision's vote.
    access.append_ledger(
        LedgerKind.OUTCOME,
        "correction",
        {
            "situation_id": "x",
            "observed_action": "UNDO",
            "source": "undo",
            "strength": "STRONG",
            "known_at": "2026-05-31T12:00:00Z",
        },
        created_at="2026-05-31T12:00:00Z",
    )
    result = aggregate_evidence(memory_db, T, persist=False)[PAIR]
    assert (result.n_strong, result.k_strong) == (1, 0)


@pytest.mark.parametrize(
    "gate,strength,n_strong,n_all",
    [
        ("SHADOW", "STRONG", 1, 1),
        ("SUGGEST", "WEAK", 0, 1),
        ("EXECUTE_UNDO", "STRONG", 0, 0),
        ("HOLD_THEN_EXECUTE", "WEAK", 0, 0),
    ],
)
def test_counts_and_audit_semantics(memory_db, gate, strength, n_strong, n_all):
    seed(memory_db, gate=gate, strength=strength)
    result = aggregate_evidence(memory_db, T, persist=False).get(PAIR)
    assert ((result.n_strong, result.n_all) if result else (0, 0)) == (n_strong, n_all)


def test_future_decisions_and_duplicate_events_do_not_change_past(memory_db):
    seed(memory_db)
    before = aggregate_evidence(memory_db, T, persist=False)
    RoleAccess(memory_db, Role.RESOLVER).append_ledger(
        LedgerKind.OUTCOME,
        "duplicate",
        {
            "situation_id": "x",
            "observed_action": "ARCHIVE",
            "strength": "STRONG",
            "source": "footprint",
            "known_at": OUTCOME_TIME,
        },
        created_at=OUTCOME_TIME,
    )
    RoleAccess(memory_db, Role.RESOLVER).append_ledger(
        LedgerKind.OUTCOME,
        "future",
        {
            "situation_id": "x",
            "observed_action": "TRASH",
            "strength": "STRONG",
            "source": "footprint",
            "known_at": "2026-07-01T00:00:00Z",
        },
        created_at="2026-07-01T00:00:00Z",
    )
    assert aggregate_evidence(memory_db, T, persist=False) == before
