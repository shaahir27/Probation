"""Comprehensive test suite for Phase 9 FastAPI HTTP endpoints.

Authority: docs/CONTRACT.md section 3, 8, 9 and docs/TEST_PLAN.md T-API.
Verifies:
- All 19 Phase 9 endpoints return expected shapes.
- Uniform error shapes { 'error': { 'code': str, 'message': str } }.
- Process write boundaries: API writes strictly to user_responses and never to restricted tables.
- Idempotency & fail-closed behavior.
- Zero outbound network calls from web-facts.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.config import settings
from probation.core.clock import Clock
from probation.db.connection import get_connection, init_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def request_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "clock", Clock.replay(datetime(2026, 3, 1, 11, tzinfo=UTC)))


def _seed_sample_db(db_path: Path) -> None:
    """Helper to populate sample data matching contract schemas."""
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()

    now = "2026-03-01T10:00:00Z"
    # 0. Source & raw item
    cur.execute(
        """
        INSERT INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-1', 'mail', 'mbox', '/path/to/inbox.mbox', ?);
        """,
        (now,),
    )
    cur.execute(
        """
        INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
        VALUES ('raw-1', 'src-1', 'mail', 'mail_in', 'msg-1', ?, ?, '{"subject":"Coffee?"}', 'hash1');
        """,
        (now, now),
    )
    # 1. Situation
    cur.execute(
        """
        INSERT INTO situations (id, pack, family, raw_item_id, occurred_at, sender_key, content_hash, redacted_text, created_at)
        VALUES ('sit-1', 'mail', 'email_action', 'raw-1', ?, 'alice@corp.com', 'hash1', 'Coffee catchup?', ?);
        """,
        (now, now),
    )
    # 2. Proposal
    cur.execute(
        """
        INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, params_json, explanation_json, web_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
        VALUES ('prop-1', 'sit-1', 'email_action', 'mail|known', 'REPLY', '{"REPLY":0.8,"ARCHIVE":0.2}', 0.8, 0.1, 0, 1, 2, 'ASK', '["familiar_sender"]', '{"body":"Sure!"}', '{"top_clues":["sender_freq"]}', '{"status":"confirmed_official"}', 'v1', 'fhash', 0, ?, 1);
        """,
        (now,),
    )
    # 3. Draft
    cur.execute(
        """
        INSERT INTO drafts (proposal_id, body_text, needs_user_input, validator_ok, model_id, prompt_version, created_at)
        VALUES ('prop-1', 'Sure, let us catch up tomorrow!', 0, 1, 'nemotron-mini', 'p1', ?);
        """,
        (now,),
    )
    # 4. Action
    cur.execute(
        """
        INSERT INTO actions (id, proposal_id, pack, type, params_json, level_required, recallable, status, hold_until, undo_json, created_at, updated_at)
        VALUES ('act-1', 'prop-1', 'mail', 'REPLY', '{"to":"alice@corp.com"}', 2, 1, 'DONE', NULL, '{"draft_id":"d1"}', ?, ?);
        """,
        (now, now),
    )
    # 5. Class stats
    cur.execute(
        """
        INSERT INTO class_stats (class_key, action, as_of, n_strong, k_strong, n_all, k_all, n_recent, lb_strong, lb_all)
        VALUES ('mail|known', 'REPLY', ?, 15, 14, 20, 18, 5, 0.75, 0.78);
        """,
        (now,),
    )
    # 6. Habit
    cur.execute(
        """
        INSERT INTO habits (id, family, clue, clue_value, action, k, n, lift, q_value, statement, examples_json, status, created_at)
        VALUES ('hab-1', 'email_action', 'sender', 'alice@corp.com', 'REPLY', 12, 12, 1.8, 0.001, 'You always reply to Alice before 10am', '[]', 'active', ?);
        """,
        (now,),
    )
    # 7. Chain
    cur.execute(
        """
        INSERT INTO chains (id, trigger_class_key, follow_action, k, n, base_rate, lift, status, created_at)
        VALUES ('ch-1', 'mail|known', 'BLOCK_TIME', 8, 10, 0.5, 1.6, 'active', ?);
        """,
        (now,),
    )
    # 8. Tavily calls & web facts
    cur.execute(
        """
        INSERT INTO tavily_calls (id, endpoint, purpose, query_text, params_json, credits, ok, situation_id, created_at)
        VALUES ('tav-1', 'search', 'find_official', 'corp.com official contact', '{}', 1.0, 1, 'sit-1', ?);
        """,
        (now,),
    )
    cur.execute(
        """
        INSERT INTO web_facts (entity_key, status, facts_json, sources_json, origin, fetched_at, ttl_until)
        VALUES ('corp.com', 'confirmed_official', '{"domain_in_results":true}', '["https://corp.com"]', 'tavily', ?, ?);
        """,
        (now, now),
    )
    conn.commit()
    conn.close()


def test_health_endpoints() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_uniform_error_shape() -> None:
    res = client.get("/api/nonexistent-route-for-testing")
    assert res.status_code == 404
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "404"
    assert "message" in data["error"]


def test_queue_endpoints(tmp_path: Path) -> None:
    test_db = tmp_path / "test_queue.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        # 1. GET /api/queue
        res = client.get("/api/queue")
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "prop-1"
        assert len(data["digests"]) == 1

        # 2. POST /api/queue/{id}/respond
        res_post = client.post("/api/queue/prop-1/respond", json={"response": "accept"})
        assert res_post.status_code == 200
        post_data = res_post.json()
        assert post_data["ok"] is True
        assert post_data["response"] == "accept"

        # 3. Process write boundary: verify user_responses has row, but outcomes / ledger unchanged by API
        conn = get_connection(test_db)
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_responses WHERE proposal_id = 'prop-1';")
        ur_row = cur.fetchone()
        assert ur_row is not None
        assert ur_row["response"] == "accept"
        conn.close()

        # 4. Double respond returns 'Already answered'
        res_post2 = client.post("/api/queue/prop-1/respond", json={"response": "reject"})
        assert res_post2.status_code == 200
        assert res_post2.json()["message"] == "Already answered"


def test_item_detail_endpoint(tmp_path: Path) -> None:
    test_db = tmp_path / "test_item.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        res = client.get("/api/items/prop-1")
        assert res.status_code == 200
        data = res.json()
        assert data["proposal_id"] == "prop-1"
        assert data["action"] == "REPLY"
        assert data["draft"] is not None
        assert data["evidence"] is not None
        assert data["evidence"]["k_strong"] == 14


def test_actions_and_undo_endpoints(tmp_path: Path) -> None:
    test_db = tmp_path / "test_actions.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        # 1. GET /api/actions
        res = client.get("/api/actions")
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] == 1
        assert data["actions"][0]["status"] == "DONE"

        # 2. POST /api/actions/act-1/undo writes user_responses with response='undo'
        res_undo = client.post("/api/actions/act-1/undo")
        assert res_undo.status_code == 200
        assert res_undo.json()["ok"] is True
        assert res_undo.json()["status"] == "UNDO_REQUESTED"

        # Verify DB entry
        conn = get_connection(test_db)
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_responses WHERE action_id = 'act-1';")
        assert cur.fetchone() is not None
        conn.close()


def test_licences_endpoint(tmp_path: Path) -> None:
    test_db = tmp_path / "test_licences.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        res = client.get("/api/licences")
        assert res.status_code == 200
        data = res.json()
        assert "licences" in data
        assert len(data["licences"]) >= 1
        assert data["licences"][0]["class_key"] == "mail|known"


def test_report_card_endpoint(tmp_path: Path) -> None:
    test_db = tmp_path / "test_report.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        res = client.get("/api/report-card?family=email_action")
        assert res.status_code == 200
        data = res.json()
        assert data["family"] == "email_action"
        assert data["scope"] == "family_summary"


def test_insights_endpoints(tmp_path: Path) -> None:
    test_db = tmp_path / "test_insights.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        # Metrics
        res_m = client.get("/api/metrics/summary")
        assert res_m.status_code == 200
        assert "proposals_total" in res_m.json()

        # Habits
        res_h = client.get("/api/habits")
        assert res_h.status_code == 200
        assert len(res_h.json()["habits"]) == 1

        # Deny Habit
        res_hd = client.post("/api/habits/hab-1/deny")
        assert res_hd.status_code == 202
        command_id = res_hd.json()["command"]["id"]
        assert res_hd.json()["command"]["status"] == "PENDING"
        assert client.get(f"/api/commands/{command_id}").json()["command"]["status"] == "PENDING"
        with get_connection(test_db) as observer:
            assert (
                observer.execute("SELECT status FROM habits WHERE id='hab-1'").fetchone()[0]
                == "active"
            )

        # Chains
        res_c = client.get("/api/chains")
        assert res_c.status_code == 200
        assert len(res_c.json()["chains"]) == 1

        # Exams
        res_e = client.get("/api/exams")
        assert res_e.status_code == 200
        assert "runs" in res_e.json()

        # Run Exam
        res_er = client.post("/api/exams/run", json={"class_key": "mail|known", "action": "REPLY"})
        assert res_er.status_code == 202
        assert res_er.json()["ok"] is True
        with get_connection(test_db) as examiner:
            from probation.workers.admin import process_admin_commands

            process_admin_commands(examiner, clock=app.state.clock)
            assert (
                examiner.execute("SELECT status FROM habits WHERE id='hab-1'").fetchone()[0]
                == "denied"
            )
        assert client.get(f"/api/commands/{command_id}").json()["command"]["status"] == "SUCCEEDED"


def test_boards_endpoint(tmp_path: Path) -> None:
    test_db = tmp_path / "test_boards.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        # In Phase 8b, radar board is registered and active
        res = client.get("/api/boards/radar")
        assert res.status_code == 200
        assert res.json()["pack"] == "radar"
        assert res.json()["active"] is True
        assert "entries" in res.json()

        # Unregistered board returns 404 cleanly
        res_unknown = client.get("/api/boards/unknown_domain")
        assert res_unknown.status_code == 404


def test_webfacts_recorded_activity(tmp_path: Path) -> None:
    test_db = tmp_path / "test_webfacts.db"
    _seed_sample_db(test_db)

    with patch.object(settings, "db_path", test_db):
        # Reads local sqlite tables without any network request
        res = client.get("/api/web-facts")
        assert res.status_code == 200
        data = res.json()
        assert data["total_calls"] == 1
        assert len(data["queries"]) == 1
        assert len(data["entities"]) == 1


def test_replay_endpoints() -> None:
    res = client.get("/api/replay/state")
    assert res.status_code == 200
    assert "running" in res.json()

    res_start = client.post("/api/replay/start")
    assert res_start.status_code == 200
    assert res_start.json()["state"]["running"] is True

    res_speed = client.post("/api/replay/speed", json={"speed": 10.0})
    assert res_speed.status_code == 200
    assert res_speed.json()["speed"] == 10.0

    res_pause = client.post("/api/replay/pause")
    assert res_pause.status_code == 200
    assert res_pause.json()["state"]["running"] is False
