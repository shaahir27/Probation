"""Fresh web restrictions reach the real D3 mail lifecycle without granting authority."""

import json
import sqlite3
from pathlib import Path

import pytest

from probation.core.clock import Clock, parse_timestamp
from probation.core.enums import GateDecision
from probation.core.lifecycle import ResponseIntent, binding_hash
from probation.core.review_binding import build_review_binding
from probation.db.access import Role, RoleAccess
from probation.db.ledger import verify_ledger
from probation.db.lifecycle_responses import ResponseStore
from probation.synth.world import SimWorld
from probation.workers.executor import Executor
from probation.workers.restrictions import current_web_cap
from tests.unit.wp6_mail_fixture import GRANT, NOW, seed

LATER = "2026-10-01T01:00:02Z"


def _setup(tmp_path: Path, *, autonomous: bool) -> tuple[sqlite3.Connection, SimWorld]:
    conn, world = seed(tmp_path, autonomous=autonomous)
    conn.execute("UPDATE situations SET sender_key='sender@organization.example'")
    reader = {
        "intent": "fyi",
        "asks_me_to_do_something": False,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": False,
        "urgency": 0,
        "formality": "neutral",
        "asks_for_personal_info": False,
        "looks_automated": False,
    }
    conn.execute(
        """INSERT INTO features
        (situation_id,deterministic_json,reader_json,reader_ok,featurizer_version,features_hash,created_at)
        VALUES ('sit','{}',?,1,'d5-execution-test','features',?)""",
        (json.dumps(reader), NOW),
    )
    conn.commit()
    return conn, world


def _veto(conn: sqlite3.Connection, fetched: str, expiry: str) -> None:
    conn.execute(
        "INSERT INTO web_facts VALUES (?,?,?,?,?,?,?,?)",
        (
            "organization.example",
            "reports_found",
            "{}",
            '[{"title":"Independent report","url":"https://report.example/notice"}]',
            "tavily",
            0,
            fetched,
            expiry,
        ),
    )
    conn.commit()


@pytest.mark.parametrize(
    "fetched,expiry,restricted",
    [
        ("2026-10-01T01:00:01Z", "2026-10-02T01:00:00Z", True),
        ("2026-10-01T01:00:03Z", "2026-10-02T01:00:00Z", False),
        ("2026-09-30T01:00:00Z", "2026-10-01T01:00:02Z", False),
    ],
)
def test_d5_existing_autonomous_action_rechecks_current_web_veto(
    tmp_path: Path,
    fetched: str,
    expiry: str,
    restricted: bool,
) -> None:
    conn, world = _setup(tmp_path, autonomous=True)
    try:
        clock = Clock.replay(parse_timestamp(NOW))
        worker = Executor(
            conn, world, clock=clock, licence_checker=lambda *_: 3, grant_resolver=lambda _: GRANT
        )
        binding = build_review_binding(
            conn,
            "proposal",
            grant=GRANT,
            owner_id="owner",
            restriction_revision="0",
            as_of=NOW,
            response="accept",
        )
        action = worker.create_action(
            "proposal",
            "mail",
            "ARCHIVE",
            binding.params,
            2,
            True,
            GateDecision.EXECUTE_UNDO,
            NOW,
            binding=binding,
        )
        assert current_web_cap(conn, "proposal", NOW) == 3
        _veto(conn, fetched, expiry)
        clock.set_time(parse_timestamp(LATER))
        assert current_web_cap(conn, "proposal", LATER) == (1 if restricted else 3)
        results = worker.process_queue(LATER)
        assert len(results) == 1 and results[0].success is (not restricted)
        stored = conn.execute("SELECT status FROM actions WHERE id=?", (action.id,)).fetchone()
        assert stored[0] == ("CANCELLED" if restricted else "DONE")
        assert ("INBOX" in world.get_message("<m@test.local>")["labels"]) is restricted
        assert world.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == (
            0 if restricted else 1
        )
        assert conn.execute("SELECT cap FROM proposals WHERE id='proposal'").fetchone()[0] == 3
        assert verify_ledger(conn) == (True, None)
    finally:
        world.close()
        conn.close()


def test_d5_web_cap_does_not_change_exact_explicit_approval_authority(tmp_path: Path) -> None:
    conn, world = _setup(tmp_path, autonomous=False)
    try:
        clock = Clock.replay(parse_timestamp(NOW))
        worker = Executor(
            conn, world, clock=clock, licence_checker=lambda *_: 0, grant_resolver=lambda _: GRANT
        )
        binding = build_review_binding(
            conn,
            "proposal",
            grant=GRANT,
            owner_id="owner",
            restriction_revision="0",
            as_of=NOW,
            response="accept",
        )
        _veto(conn, "2026-10-01T01:00:01Z", "2026-10-02T01:00:00Z")
        assert current_web_cap(conn, "proposal", LATER) == 1
        ResponseStore(RoleAccess(conn, Role.API)).submit(
            ResponseIntent(
                request_id="d5-explicit",
                proposal_id="proposal",
                response="accept",
                owner_id="owner",
                responded_at=LATER,
                reviewed_payload=binding,
                reviewed_payload_hash=binding_hash(binding),
            )
        )
        clock.set_time(parse_timestamp(LATER))
        assert worker.process_responses(LATER) == 1
        results = worker.process_queue(LATER)
        assert len(results) == 1 and results[0].success
        stored = conn.execute("SELECT authority_kind,status FROM actions").fetchone()
        assert tuple(stored) == ("explicit_user", "DONE")
        assert "INBOX" not in world.get_message("<m@test.local>")["labels"]
        assert conn.execute("SELECT count(*) FROM licence_cache WHERE level>0").fetchone()[0] == 0
    finally:
        world.close()
        conn.close()


@pytest.mark.parametrize("missing_sender", [False, True])
def test_d5_execution_uses_same_distinct_domain_projection_as_verification(
    tmp_path: Path, missing_sender: bool
) -> None:
    conn, world = _setup(tmp_path, autonomous=True)
    try:
        payload = json.loads(
            conn.execute("SELECT payload_json FROM raw_items WHERE id='raw'").fetchone()[0]
        )
        payload["from"] = (
            "sender@organization.example" if missing_sender else "sender@innocent.example"
        )
        payload["body"] = " ".join(
            [
                "https://gstatic.com/one",
                "https://gstatic.com/two",
                "https://gstatic.com/three",
                "https://repeated.example/one",
                "https://repeated.example/two",
                "https://organization.example/report",
            ]
        )
        conn.execute("UPDATE raw_items SET payload_json=? WHERE id='raw'", (json.dumps(payload),))
        if missing_sender:
            payload["body"] = "https://gstatic.com/one https://repeated.example/one"
            conn.execute(
                "UPDATE raw_items SET payload_json=? WHERE id='raw'", (json.dumps(payload),)
            )
            conn.execute("UPDATE situations SET sender_key=NULL")
        else:
            conn.execute("UPDATE situations SET sender_key='sender@innocent.example'")
        conn.commit()
        clock = Clock.replay(parse_timestamp(NOW))
        worker = Executor(
            conn, world, clock=clock, licence_checker=lambda *_: 3, grant_resolver=lambda _: GRANT
        )
        binding = build_review_binding(
            conn,
            "proposal",
            grant=GRANT,
            owner_id="owner",
            restriction_revision="0",
            as_of=NOW,
            response="accept",
        )
        worker.create_action(
            "proposal",
            "mail",
            "ARCHIVE",
            binding.params,
            2,
            True,
            GateDecision.EXECUTE_UNDO,
            NOW,
            binding=binding,
        )
        _veto(conn, "2026-10-01T01:00:01Z", "2026-10-02T01:00:00Z")
        clock.set_time(parse_timestamp(LATER))
        assert current_web_cap(conn, "proposal", LATER) == 1
        results = worker.process_queue(LATER)
        assert len(results) == 1 and not results[0].success
        assert results[0].error == "licence_lost"
        assert "INBOX" in world.get_message("<m@test.local>")["labels"]
        assert world.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 0
    finally:
        world.close()
        conn.close()
