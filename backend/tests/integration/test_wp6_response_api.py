"""D3 intent acceptance is not execution success; no real accounts involved."""

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.authority import OwnerContext, require_owner
from probation.config import settings
from probation.core.clock import Clock, parse_timestamp
from probation.core.lifecycle import SourceGrant
from probation.db.connection import get_connection
from tests.unit.test_wp6_review_binding import review_source as review_source


@pytest.fixture
def client(review_source, tmp_path, monkeypatch):
    path = tmp_path / "api.sqlite"
    with get_connection(path) as target:
        review_source.backup(target)
    monkeypatch.setattr(settings, "db_path", path)
    monkeypatch.setattr(app.state, "clock", Clock.replay(parse_timestamp("2026-01-01T10:00:02Z")))
    owner = OwnerContext(
        "owner", (SourceGrant("wp1-source", "connection", "account", "owner@test.invalid"),)
    )
    app.dependency_overrides[require_owner] = lambda: owner
    with TestClient(app) as result:
        yield result
    app.dependency_overrides.pop(require_owner, None)


def request(client, response="accept", **kwargs):
    payload = {"version": "v2", "response": response, **kwargs}
    reviewed = client.post("/api/queue/review-proposal/review", json=payload)
    assert reviewed.status_code == 200, reviewed.text
    return {
        **payload,
        "request_id": "request",
        "reviewed_payload_hash": reviewed.json()["reviewed_payload_hash"],
    }


def test_durable_response_stays_pending_until_workers_process(client):
    body = request(client)
    response = client.post("/api/queue/review-proposal/respond", json=body)
    assert response.status_code == 202, response.text
    status = client.get("/api/responses/request")
    assert status.status_code == 200
    assert status.json()["decision_status"] == "pending"
    assert status.json()["execution_status"] == "pending"
    assert client.post("/api/queue/review-proposal/respond", json=body).status_code == 202


def test_changed_review_payload_or_first_decision_conflicts(client):
    body = request(client)
    assert (
        client.post(
            "/api/queue/review-proposal/respond", json={**body, "response": "reject"}
        ).status_code
        == 409
    )
    assert client.post("/api/queue/review-proposal/respond", json=body).status_code == 202
    rejection = request(client, "reject")
    rejection["request_id"] = "other"
    assert client.post("/api/queue/review-proposal/respond", json=rejection).status_code == 409


def test_owner_required_and_legacy_mutation_rejected(client):
    assert (
        client.post("/api/queue/review-proposal/respond", json={"response": "accept"}).status_code
        == 422
    )
    app.dependency_overrides.pop(require_owner)
    assert (
        client.post(
            "/api/queue/review-proposal/review", json={"version": "v2", "response": "accept"}
        ).status_code
        == 403
    )


def test_response_status_owner_scope(client):
    body = request(client)
    assert client.post("/api/queue/review-proposal/respond", json=body).status_code == 202
    app.dependency_overrides[require_owner] = lambda: OwnerContext("other", ())
    assert client.get("/api/responses/request").status_code == 404


def test_reject_review_cannot_be_relabelled_as_training_leave(client):
    body = request(client, "reject")
    assert (
        client.post(
            "/api/queue/review-proposal/respond", json={**body, "response": "leave"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("decision", ["accept", "reject", "leave"])
def test_resolver_records_decision_once_without_claiming_execution(client, decision):
    from probation.workers.response_resolver import resolve_responses

    body = request(client, decision)
    assert client.post("/api/queue/review-proposal/respond", json=body).status_code == 202
    with get_connection(settings.db_path) as conn:
        assert resolve_responses(conn, as_of="2026-01-01T10:00:03Z") == 1
        assert resolve_responses(conn, as_of="2026-01-01T10:00:04Z") == 0
        event = conn.execute("SELECT * FROM outcome_events").fetchall()
        assert len(event) == 1
        assert (
            event[0]["observed_action"]
            == ({"accept": "REPLY", "leave": "LEAVE", "reject": None}[decision])
        )
        assert conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0
    status = client.get("/api/responses/request").json()
    assert status["decision_status"] == "succeeded"
    assert status["execution_status"] == ("pending" if decision == "accept" else "not_required")
