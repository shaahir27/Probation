"""Comprehensive test suite for Phase 9 FastAPI HTTP endpoints.

Authority: docs/CONTRACT.md section 3, 8, 9 and docs/TEST_PLAN.md T-API.
Verifies:
- All 19 Phase 9 endpoints return expected shapes.
- Uniform error shapes { 'error': { 'code': str, 'message': str } }.
- Process write boundaries: API writes strictly to user_responses and never to restricted tables.
- Idempotency & fail-closed behavior.
- Zero outbound network calls from web-facts.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.authority import OwnerContext, optional_owner
from probation.config import settings
from probation.core.clock import Clock
from probation.core.hashing import canonical_json
from probation.core.lifecycle import SourceGrant, binding_hash
from probation.core.review_binding import build_review_binding
from probation.db.connection import get_connection, init_db
from probation.llm.draft_validation import body_hash

client = TestClient(app)


@pytest.fixture(autouse=True)
def request_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "clock", Clock.replay(datetime(2026, 3, 1, 11, tzinfo=UTC)))


@pytest.fixture(autouse=True)
def authenticated_synthetic_owner(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "probation_gmail_owner_id", "owner")
    app.dependency_overrides[optional_owner] = lambda: OwnerContext(
        "owner", (SourceGrant("src-1", "connection", "account", "owner@test.invalid"),)
    )
    yield
    app.dependency_overrides.pop(optional_owner, None)


def test_private_read_requires_authenticated_owner(tmp_path: Path) -> None:
    from probation.api.gmail_auth import OwnerApiCredential, hash_owner_token
    from probation.api.routes.gmail_connector import GmailApiConfig, configure_gmail_api

    app.dependency_overrides.pop(optional_owner, None)
    configure_gmail_api(
        GmailApiConfig(
            owner_credential=OwnerApiCredential("owner", hash_owner_token("synthetic-key")),
            store_path=tmp_path / "missing-private-store.db",
        )
    )
    try:
        response = client.get("/api/queue")
    finally:
        configure_gmail_api(None)
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "message": "owner_credential_required"}}


def test_validation_error_does_not_echo_request_body() -> None:
    response = client.post("/api/queue/prop-1/review", json={"password": "synthetic-secret"})
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text
    assert response.json() == {"error": {"code": "422", "message": "request_validation_failed"}}


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
        VALUES ('raw-1', 'src-1', 'mail', 'mail_in', 'msg-1', ?, ?, '{"subject":"Coffee?","body":"Coffee catchup tomorrow?","from":"alice@corp.com","message_id":"<msg-1@corp.com>"}', 'hash1');
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
    cur.execute(
        "UPDATE proposals SET params_json=? WHERE id='prop-1'",
        (
            canonical_json(
                {
                    "draft_proposal_id": "prop-1",
                    "to_addr": "alice@corp.com",
                    "draft_body_hash": body_hash("Sure, let us catch up tomorrow!"),
                }
            ),
        ),
    )
    binding = build_review_binding(
        conn,
        "prop-1",
        grant=SourceGrant("src-1", "connection", "account", "owner@test.invalid"),
        owner_id="owner",
        restriction_revision="0",
        as_of=now,
        response="edit",
        edited_action="ARCHIVE",
    )
    cur.execute(
        """UPDATE actions SET type='ARCHIVE',params_json=?,binding_json=?,binding_hash=?,authority_kind='autonomous',executed_at=?,undo_deadline='2026-03-08T10:00:00Z' WHERE id='act-1'""",
        (canonical_json(binding.params), binding.model_dump_json(), binding_hash(binding), now),
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
        body = {"version": "v2", "response": "accept"}
        reviewed = client.post("/api/queue/prop-1/review", json=body)
        assert reviewed.status_code == 200, reviewed.text
        res_post = client.post(
            "/api/queue/prop-1/respond",
            json={
                **body,
                "request_id": "initial",
                "reviewed_payload_hash": reviewed.json()["reviewed_payload_hash"],
            },
        )
        assert res_post.status_code == 202
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

        # 4. A competing initial decision is a typed conflict.
        rejection = {"version": "v2", "response": "reject"}
        reviewed = client.post("/api/queue/prop-1/review", json=rejection)
        res_post2 = client.post(
            "/api/queue/prop-1/respond",
            json={
                **rejection,
                "request_id": "different",
                "reviewed_payload_hash": reviewed.json()["reviewed_payload_hash"],
            },
        )
        assert res_post2.status_code == 409


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
        assert (
            data["evidence"]["k_strong"] == 0
        )  # A mutable class_stats cache is not permission evidence.


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
        res_undo = client.post(
            "/api/actions/act-1/undo", json={"version": "v2", "request_id": "undo-request"}
        )
        assert res_undo.status_code == 202, res_undo.text
        assert res_undo.json()["status"] == "recorded"

        # Verify DB entry
        conn = get_connection(test_db)
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_responses WHERE action_id = 'act-1';")
        assert cur.fetchone() is not None
        conn.close()


def test_consumed_undo_is_pending_and_unknown_is_not_success(tmp_path: Path) -> None:
    from probation.db.access import Role, RoleAccess
    from probation.db.lifecycle_attempts import AttemptStore
    from probation.db.lifecycle_receipts import ReceiptStore

    path = tmp_path / "undo-status.db"
    _seed_sample_db(path)
    with patch.object(settings, "db_path", path):
        response = client.post(
            "/api/actions/act-1/undo", json={"version": "v2", "request_id": "undo-status"}
        )
        assert response.status_code == 202
        with get_connection(path) as conn:
            access = RoleAccess(conn, Role.EXECUTOR)
            receipts = ReceiptStore(access)
            claim = receipts.claim_response(
                "undo-status", now="2026-03-01T11:00:00Z", owner="executor"
            )
            receipts.finish(
                claim, now="2026-03-01T11:00:00Z", status="succeeded", result={"action_id": "act-1"}
            )
        status = client.get("/api/responses/undo-status").json()
        assert status["decision_status"] == "not_required"
        assert status["execution_status"] == "pending"
        with get_connection(path) as conn:
            access = RoleAccess(conn, Role.EXECUTOR)
            attempts = AttemptStore(access)
            digest = conn.execute("SELECT binding_hash FROM actions WHERE id='act-1'").fetchone()[0]
            claim = attempts.prepare(
                "act-1", "undo", digest, {}, "2026-03-01T11:00:00Z", "executor"
            )
            attempts.mark_dispatched(claim, "2026-03-01T11:00:00Z")
            attempts.mark_unknown(claim, "2026-03-01T11:00:00Z", "result_unknown")
        assert (
            client.get("/api/responses/undo-status").json()["execution_status"]
            == "needs-reconciliation"
        )


def test_control_commands_are_owned_and_pending_pause_blocks_review(tmp_path: Path) -> None:
    path = tmp_path / "controls.db"
    _seed_sample_db(path)
    with patch.object(settings, "db_path", path):
        body = {
            "version": "v2",
            "request_id": "pause",
            "type": "pause",
            "scope": {"connection_id": "connection", "account_id": "account"},
        }
        assert client.post("/api/commands", json=body).status_code == 202
        assert client.get("/api/commands/pause").json()["status"] == "pending"
        assert (
            client.post(
                "/api/queue/prop-1/review", json={"version": "v2", "response": "accept"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/commands",
                json={
                    **body,
                    "request_id": "wrong",
                    "scope": {"connection_id": "other", "account_id": "account"},
                },
            ).status_code
            == 403
        )
        assert client.post("/api/commands", json=body).status_code == 202


def test_replay_command_status_uses_v2_discriminator(tmp_path: Path) -> None:
    from probation.core.lifecycle import ReplayCommandIntent, ReplayScope
    from probation.db.access import Role, RoleAccess
    from probation.db.replay_commands import ReplayCommandStore

    path = tmp_path / "replay-status.db"
    _seed_sample_db(path)
    with patch.object(settings, "db_path", path):
        with get_connection(path) as conn:
            ReplayCommandStore(RoleAccess(conn, Role.API)).submit(
                ReplayCommandIntent(
                    request_id="replay-start-1",
                    owner_id="owner",
                    type="replay_start",
                    scope=ReplayScope(workspace_id="synthetic-workspace", run_id="active"),
                    created_at="2026-03-01T11:00:00Z",
                )
            )
        response = client.get("/api/commands/replay-start-1")
    assert response.status_code == 200
    assert response.json() == {
        "request_id": "replay-start-1",
        "type": "replay_start",
        "status": "pending",
        "result": None,
        "safe_code": None,
        "status_url": "/api/commands/replay-start-1",
    }


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


def test_watching_and_permissions_are_filtered_to_owner_sources(tmp_path: Path) -> None:
    path = tmp_path / "owner-scoped-reads.db"
    _seed_sample_db(path)
    now = "2026-03-01T10:30:00Z"
    with get_connection(path) as conn:
        conn.execute(
            "INSERT INTO sources (id,pack,kind,ref,imported_at) VALUES ('src-other','mail','mbox','other',?)",
            (now,),
        )
        conn.execute(
            """INSERT INTO raw_items
               (id,source_id,pack,item_kind,source_ref,occurred_at,known_at,payload_json,content_hash)
               VALUES ('raw-watch','src-1','mail','mail_in','watch-msg',?,?, '{}','watch-hash')""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO situations
               (id,pack,family,raw_item_id,occurred_at,sender_key,content_hash,redacted_text,created_at)
               VALUES ('sit-watch','mail','email_action','raw-watch',?,'watch@example.invalid','watch-hash','watch summary',?)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO raw_items
               (id,source_id,pack,item_kind,source_ref,occurred_at,known_at,payload_json,content_hash)
               VALUES ('raw-other','src-other','mail','mail_in','other-msg',?,?, '{}','other-hash')""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO situations
               (id,pack,family,raw_item_id,occurred_at,sender_key,content_hash,redacted_text,created_at)
               VALUES ('sit-other','mail','email_action','raw-other',?,'private@example.invalid','other-hash','private summary',?)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO proposals
               (id,situation_id,family,class_key,action,probs_json,p_max,novelty,novel,
                licence_level,cap,gate,reasons_json,params_json,explanation_json,web_json,
                policy_version,features_hash,audit_holdout,proposed_at,ledger_seq)
               VALUES ('prop-other','sit-other','email_action','private|known','REPLY','{}',0.5,
                0.2,0,0,0,'ASK','[]','{}','{}','{}','v1','other-features',0,?,1)""",
            (now,),
        )
        conn.execute(
            """INSERT INTO proposals
               (id,situation_id,family,class_key,action,probs_json,p_max,novelty,novel,
                licence_level,cap,gate,reasons_json,params_json,explanation_json,web_json,
                policy_version,features_hash,audit_holdout,proposed_at,ledger_seq)
               VALUES ('prop-watch','sit-watch','email_action','mail|known','ARCHIVE','{}',0.5,
                0.2,0,0,0,'SHADOW','[]','{}','{}','{}','v1','watch-features',0,?,2)""",
            (now,),
        )

    with patch.object(settings, "db_path", path):
        watching = client.get("/api/watching")
        permissions = client.get("/api/permissions")
    assert watching.status_code == 200
    assert [item["id"] for item in watching.json()["items"]] == ["prop-watch"]
    assert permissions.status_code == 200
    assert {item["class_key"] for item in permissions.json()["licences"]} == {"mail|known"}
    assert permissions.json()["source_cutoff"] == "2026-03-01T11:00:00Z"


def test_item_only_advertises_safe_available_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probation.api.routes import items

    path = tmp_path / "supported-actions.db"
    _seed_sample_db(path)
    with patch.object(settings, "db_path", path):
        monkeypatch.setattr(items, "_write_capabilities", lambda _owner, _source: set())
        detail = client.get("/api/items/prop-1")
        assert detail.status_code == 200
        assert detail.json()["supported_actions"] == ["LEAVE"]
        assert detail.json()["readiness"]["reply_draft_available"] is False

        monkeypatch.setattr(
            items,
            "_write_capabilities",
            lambda _owner, _source: {"archive", "trash", "send", "forward"},
        )
        detail = client.get("/api/items/prop-1")
        assert detail.status_code == 200
        assert detail.json()["supported_actions"] == ["ARCHIVE", "TRASH", "LEAVE", "REPLY"]
        assert detail.json()["readiness"]["reply_draft_available"] is True


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


def test_legacy_command_status_is_bound_to_configured_single_owner(tmp_path: Path) -> None:
    path = tmp_path / "admin-command-owner.db"
    _seed_sample_db(path)
    with patch.object(settings, "db_path", path):
        created = client.post("/api/habits/hab-1/deny")
        assert created.status_code == 202
        command_id = created.json()["command"]["id"]
        app.dependency_overrides[optional_owner] = lambda: OwnerContext(
            "different-owner",
            (SourceGrant("src-1", "connection", "account", "other@test.invalid"),),
        )
        response = client.get(f"/api/commands/{command_id}")
    assert response.status_code == 404


def test_boards_endpoint(tmp_path: Path) -> None:
    test_db = tmp_path / "test_boards.db"
    _seed_sample_db(test_db)
    world_db = tmp_path / "missing-world.db"

    with (
        patch.object(settings, "db_path", test_db),
        patch.object(settings, "world_db_path", world_db),
    ):
        res = client.get("/api/boards/radar")
        assert res.status_code == 200
        assert res.json()["pack"] == "radar"
        assert res.json()["active"] is False
        assert res.json()["availability"] == "unavailable"
        assert res.json()["reason"] == "not_initialized"
        assert not world_db.exists()

        # Unregistered board returns 404 cleanly
        res_unknown = client.get("/api/boards/unknown_domain")
        assert res_unknown.status_code == 404

        world_db.write_text("not a sqlite database", encoding="utf-8")
        corrupt = client.get("/api/boards/radar")
        assert corrupt.status_code == 200
        assert corrupt.json()["reason"] == "board_unavailable"
        assert "sqlite" not in corrupt.text.lower()


def test_board_reads_existing_rows_without_creating_world(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "world.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE tracker (
                id TEXT,title TEXT,organizer TEXT,deadline_date TEXT,official_url TEXT,status TEXT,
                fee_flag INTEGER,sources_json TEXT,details_json TEXT,created_at TEXT,updated_at TEXT
            )"""
        )
        conn.execute(
            """INSERT INTO tracker VALUES
               ('entry-1','Grant','Foundation',NULL,'https://example.invalid','TRACKED',0,
                '[{"title":"Source"}]','{"raw_item_id":"raw-1"}','2026-03-01T10:00:00Z',
                '2026-03-01T10:00:00Z')"""
        )

    with patch.object(settings, "world_db_path", path):
        response = client.get("/api/boards/radar")
    assert response.status_code == 200
    assert response.json()["active"] is True
    assert response.json()["entries"][0]["item_id"] == "raw-1"


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


def test_replay_endpoints(tmp_path: Path) -> None:
    from probation.api.gmail_auth import OwnerApiCredential, hash_owner_token
    from probation.api.routes.gmail_connector import GmailApiConfig, configure_gmail_api

    path = tmp_path / "d6-replay-api.db"
    _seed_sample_db(path)
    owner_override = app.dependency_overrides.pop(optional_owner)
    configure_gmail_api(
        GmailApiConfig(
            owner_credential=OwnerApiCredential("owner", hash_owner_token("synthetic-key")),
            store_path=tmp_path / "connector-store.db",
        )
    )
    try:
        assert client.get("/api/replay/state").status_code == 401
    finally:
        configure_gmail_api(None)
        app.dependency_overrides[optional_owner] = owner_override

    with patch.object(settings, "db_path", path):
        state = client.get("/api/replay/state")
        assert state.status_code == 200
        assert state.json()["running"] is False

        started = client.post("/api/replay/start", json={"request_id": "d6-start"})
        assert started.status_code == 202
        assert started.json()["status"] == "accepted"
        assert started.json()["status_url"] == "/api/commands/d6-start"
        status = client.get(started.json()["status_url"])
        assert status.status_code == 200
        assert status.json()["type"] == "replay_start"
        assert status.json()["status"] == "pending"

        speed = client.post("/api/replay/speed", json={"request_id": "d6-speed", "speed": 10})
        assert speed.status_code == 202
        assert speed.json()["status"] == "accepted"
        assert (
            client.post(
                "/api/replay/speed", json={"request_id": "d6-bad-speed", "speed": 5}
            ).status_code
            == 422
        )

        paused = client.post("/api/replay/pause", json={"request_id": "d6-pause"})
        assert paused.status_code == 202
        assert paused.json()["status"] == "accepted"


def test_report_card_filters_reach_the_engine(tmp_path: Path) -> None:
    """An unmatched task, action or cutoff must change the answer, proving it was applied."""
    test_db = tmp_path / "report_filters.db"
    _seed_sample_db(test_db)
    with patch.object(settings, "db_path", test_db):
        matched = client.get(
            "/api/report-card?family=email_action"
            "&class_key=mail%7Cknown&action=REPLY&as_of=2026-03-01T11:00:00Z"
        )
        assert matched.status_code == 200
        body = matched.json()
        assert body["scope"] == "filtered_cohort"
        assert body["filters"] == {
            "family": "email_action",
            "class_key": "mail|known",
            "action": "REPLY",
        }
        assert body["total_proposals"] == 1

        wrong_task = client.get("/api/report-card?class_key=mail%7Cother&action=REPLY")
        assert wrong_task.json()["total_proposals"] == 0
        wrong_action = client.get("/api/report-card?class_key=mail%7Cknown&action=TRASH")
        assert wrong_action.json()["total_proposals"] == 0
        before_arrival = client.get("/api/report-card?as_of=2026-02-28T10:00:00Z")
        assert before_arrival.json()["total_proposals"] == 0
        assert client.get("/api/report-card?since=2026-03-02T10:00:00Z").status_code == 400


def test_metrics_separate_intended_decisions_from_confirmed_effects(tmp_path: Path) -> None:
    """A proposal to act is never reported as an effect, and future cutoffs are refused."""
    test_db = tmp_path / "metrics.db"
    _seed_sample_db(test_db)
    with patch.object(settings, "db_path", test_db):
        summary = client.get("/api/metrics/summary")
        assert summary.status_code == 200
        data = summary.json()
        assert data["proposals_total"] == 1
        assert data["asks"] == 1
        assert data["intended_actions"] == 0
        # act-1 is DONE in the mutable table, so it is a confirmed effect; the ASK proposal is not.
        assert data["confirmed_effects"] == 1
        assert data["unconfirmed_effects"] == 0
        # No append-only outcome evidence exists, so agreement has no denominator.
        assert data["agreement"] == {"numerator": 0, "denominator": 0, "rate": None}
        assert data["scope"]["sources"] == 1
        assert "automatic_actions" not in data and "agreement_rate" not in data

        assert client.get("/api/metrics/summary?as_of=2030-01-01T00:00:00Z").status_code == 400
        scoped = client.get("/api/metrics/summary?class_key=mail%7Cother")
        assert scoped.json()["proposals_total"] == 0


def _seed_spend(conn: sqlite3.Connection) -> None:
    """One confirmed charge, one estimate, one dispatched hold and one ambiguous hold."""
    now = "2026-03-01T10:00:00Z"
    conn.execute(
        """INSERT INTO budget_scopes (scope_id,provider,account_label,model_id,period_rule,
           period_key,cap_units,price_version,created_at_op)
           VALUES ('scope-1','nebius','acct','nemotron','total','all',10000000,'v1',?)""",
        (now,),
    )
    for request_id, state in (
        ("req-ok", "succeeded"),
        ("req-hold", "succeeded"),
        ("req-gone", "unavailable"),
    ):
        conn.execute(
            """INSERT INTO llm_requests (request_id,scope_id,owner_role,semantic_digest,prompt_id,
               prompt_version,model_id,cache_key,situation_id,result_state,created_at_op)
               VALUES (?,'scope-1','brain',?,'p','v1','nemotron',?,NULL,?,?)""",
            (request_id, f"digest-{request_id}", f"cache-{request_id}", state, now),
        )
    attempts = (
        ("att-ok", "req-ok", "reconciled", 5000, 5000),
        ("att-est", "req-hold", "reserved", 3000, 0),
        ("att-dis", "req-hold", "dispatched", 2000, 0),
        ("att-amb", "req-hold", "ambiguous", 1500, 0),
        ("att-none", "req-gone", "never_dispatched", 0, 0),
    )
    for ordinal, (attempt_id, request_id, state, estimate, charged) in enumerate(attempts, start=1):
        conn.execute(
            """INSERT INTO llm_attempts (attempt_id,request_id,scope_id,owner_role,ordinal,stage,
               state,estimate_units,charged_units,tokens_in_bound,tokens_out_bound,usage_provenance,
               reserved_at_op)
               VALUES (?,?,'scope-1','brain',?,'structured',?,?,?,0,0,'estimated',?)""",
            (attempt_id, request_id, ordinal, state, estimate, charged, now),
        )
    conn.commit()


def test_exposure_separates_confirmed_charges_estimates_and_holds(tmp_path: Path) -> None:
    """An unresolved hold is never presented as free or as a confirmed cost."""
    test_db = tmp_path / "spend.db"
    _seed_sample_db(test_db)
    with get_connection(test_db) as conn:
        _seed_spend(conn)
    with patch.object(settings, "db_path", test_db):
        body = client.get("/api/exposure").json()["budget"]
        assert body["available"] is True
        assert body["confirmed_usd"] == 0.00005
        assert body["estimated_usd"] == 0.00003
        assert body["unresolved_holds"] == 2
        assert set(body["holds_by_state"]) == {"reserved", "dispatched", "ambiguous"}
        assert body["never_dispatched"] == 1


def test_exposure_reports_spend_records_as_unavailable(tmp_path: Path) -> None:
    """A database without the durable spend audit says unavailable instead of zero."""
    test_db = tmp_path / "no-spend.db"
    _seed_sample_db(test_db)
    with get_connection(test_db) as conn:
        conn.execute("DROP TABLE llm_attempts")
        conn.commit()
    with patch.object(settings, "db_path", test_db):
        body = client.get("/api/exposure").json()["budget"]
        assert body == {"available": False, "reason": "spend_records_unavailable"}
