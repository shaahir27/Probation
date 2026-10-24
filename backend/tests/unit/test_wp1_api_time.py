"""WP1: response timestamps require actual strict ordering, never a fabricated tick."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.authority import OwnerContext, optional_owner
from probation.config import settings
from probation.core.clock import Clock, parse_timestamp
from probation.core.enums import GateDecision
from probation.core.lifecycle import SourceGrant
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.connection import get_connection
from probation.db.proposals import persist_proposal


@pytest.mark.parametrize("microseconds,status", [(-1, 409), (0, 409), (1, 202)])
def test_response_time_must_be_after_proposal(
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    microseconds: int,
    status: int,
) -> None:
    persist_proposal(
        RoleAccess(memory_db, Role.BRAIN),
        Proposal(
            id="time-api-proposal",
            situation_id=basic_situation.id,
            family=basic_situation.family,
            class_key="mail|request|known",
            action="REPLY",
            p_max=0.99,
            novel=False,
            gate=GateDecision.SUGGEST,
            licence_level=1,
            cap=2,
            policy_version="wp1",
            features_hash="wp1",
            proposed_at=basic_situation.occurred_at,
        ),
    )
    memory_db.commit()
    path = tmp_path / "api-time.sqlite"
    with get_connection(path) as target:
        memory_db.backup(target)
    monkeypatch.setattr(settings, "db_path", path)
    clock = Clock.replay(
        parse_timestamp(basic_situation.occurred_at) + timedelta(microseconds=microseconds)
    )
    monkeypatch.setattr(app.state, "clock", clock)
    app.dependency_overrides[optional_owner] = lambda: OwnerContext(
        "owner", (SourceGrant("wp1-source", "connection", "account", "owner@test.invalid"),)
    )
    try:
        with TestClient(app) as client:
            monkeypatch.setattr(
                app.state,
                "clock",
                Clock.replay(
                    parse_timestamp(basic_situation.occurred_at) + timedelta(microseconds=1)
                ),
            )
            body = {"version": "v2", "response": "reject"}
            reviewed = client.post("/api/queue/time-api-proposal/review", json=body)
            assert reviewed.status_code == 200
            monkeypatch.setattr(app.state, "clock", clock)
            response = client.post(
                "/api/queue/time-api-proposal/respond",
                json={
                    **body,
                    "request_id": "time-request",
                    "reviewed_payload_hash": reviewed.json()["reviewed_payload_hash"],
                },
            )
    finally:
        app.dependency_overrides.pop(optional_owner, None)
    assert response.status_code == status
    with get_connection(path) as observer:
        rows = observer.execute("SELECT responded_at FROM user_responses").fetchall()
        assert len(rows) == int(status == 202)
        if rows:
            assert rows[0][0] == clock.now_iso()
            assert parse_timestamp(rows[0][0]) > parse_timestamp(basic_situation.occurred_at)
