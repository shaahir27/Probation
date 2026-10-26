"""One genuine vote per situation, with exact proposal-bound follow-up outcomes."""

import json
import sqlite3

import pytest

from probation.core.permission_history import permission_records


@pytest.fixture
def history():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.create_collation("UTC_TIMESTAMP", lambda left, right: (left > right) - (left < right))
    conn.executescript("""
    CREATE TABLE proposals(id,situation_id,family,class_key,action,gate,proposed_at,ledger_seq,followup_of_action_id);
    CREATE TABLE situations(id,pack,raw_item_id,occurred_at,sender_key,content_hash,redacted_text,hands_off_reason,variant);
    CREATE TABLE sources(id,kind);
    CREATE TABLE raw_items(id,source_id,known_at,payload_json);
    CREATE TABLE ledger(seq,kind,ref_id,payload_json,created_at);
    INSERT INTO situations VALUES('s','mail','r','2026-01-01T00:00:00Z',NULL,'hash','text',NULL,'');
    INSERT INTO sources VALUES('synthetic-source','synthetic');
    INSERT INTO raw_items VALUES('r','synthetic-source','2026-01-01T00:00:00Z','{}');
    """)
    yield conn
    conn.close()


def proposal(conn, key, seq, at, action="ARCHIVE", gate="SUGGEST", followup=None):
    conn.execute(
        "INSERT INTO proposals VALUES(?,'s','email_action','mail|fyi|frequent',?,?,?,?,?)",
        (key, action, gate, at, seq, followup),
    )
    payload = {
        "situation_id": "s",
        "class_key": "mail|fyi|frequent",
        "action": action,
        "gate": gate,
    }
    conn.execute(
        "INSERT INTO ledger VALUES(?,'proposal',?,?,?)", (seq, key, json.dumps(payload), at)
    )


def decision(conn, seq, at, action="ARCHIVE", proposal_id=None):
    payload = {
        "situation_id": "s",
        "observed_action": action,
        "strength": "STRONG",
        "source": "footprint",
        "known_at": at,
    }
    if proposal_id is not None:
        payload["proposal_id"] = proposal_id
    conn.execute("INSERT INTO ledger VALUES(?,'outcome','s',?,?)", (seq, json.dumps(payload), at))


def test_followup_cannot_duplicate_or_replace_eligible_initial_vote(history):
    proposal(history, "initial", 1, "2026-01-01T00:00:01Z")
    decision(history, 2, "2026-01-01T00:00:02Z", proposal_id="initial")
    proposal(history, "followup", 3, "2026-01-01T00:00:03Z", "TRASH", followup="cancelled-action")
    decision(history, 4, "2026-01-01T00:00:04Z", "TRASH", "followup")
    rows = permission_records(history, "2026-01-01T00:00:05Z", None)
    assert [row["id"] for row in rows] == ["initial"]


def test_ambiguous_legacy_outcome_never_binds_to_followup(history):
    proposal(history, "initial", 1, "2026-01-01T00:00:01Z", gate="EXECUTE_UNDO")
    proposal(history, "followup", 2, "2026-01-01T00:00:03Z", followup="cancelled-action")
    decision(history, 3, "2026-01-01T00:00:04Z")
    assert permission_records(history, "2026-01-01T00:00:05Z", None) == []


def test_genuine_followup_decision_counts_once_when_initial_was_automatic(history):
    proposal(history, "initial", 1, "2026-01-01T00:00:01Z", gate="EXECUTE_UNDO")
    proposal(history, "followup", 2, "2026-01-01T00:00:03Z", followup="cancelled-action")
    decision(history, 3, "2026-01-01T00:00:04Z", proposal_id="followup")
    assert permission_records(history, "2026-01-01T00:00:02Z", None) == []
    assert [row["id"] for row in permission_records(history, "2026-01-01T00:00:05Z", None)] == [
        "followup"
    ]
