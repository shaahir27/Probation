"""Versioned replay intents preserve old controls and checkpoint state durably."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.authority import OwnerContext, optional_owner
from probation.config import settings
from probation.core.clock import Clock
from probation.core.lifecycle import CommandIntent, CommandScope
from probation.core.replay_controls import (
    ReplayCommandIntent,
    ReplayScope,
    server_replay_scope,
)
from probation.db.access import AccessError, Role, RoleAccess
from probation.db.connection import get_connection, init_db
from probation.db.lifecycle_commands import CommandStore
from probation.db.replay_commands import ReplayCommandStore
from probation.db.replay_migration import migrate_replay_commands
from probation.workers.replay_controller import ReplayController


@pytest.fixture
def replay_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    path = tmp_path / "replay-wire.db"
    init_db(path)
    monkeypatch.setattr(settings, "db_path", path)
    app.dependency_overrides[optional_owner] = lambda: OwnerContext("owner", ())
    monkeypatch.setattr(app.state, "clock", Clock.replay(datetime(2026, 3, 1, 11, tzinfo=UTC)))
    yield TestClient(app)
    app.dependency_overrides.pop(optional_owner, None)


def test_replay_migration_preserves_v1_rows_and_receipt_foreign_key() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """CREATE TABLE command_requests(
            id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL CHECK(schema_version=1),
            owner_id TEXT NOT NULL,request_key TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN('pause','resume','revoke')),
            scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,UNIQUE(owner_id,request_key));
        CREATE TABLE command_receipts(
            id TEXT PRIMARY KEY,command_id TEXT REFERENCES command_requests(id),
            response_id TEXT,consumer TEXT,state TEXT,claim_owner TEXT,fence INTEGER,
            lease_until TEXT,result_json TEXT,safe_code TEXT,created_at TEXT,updated_at TEXT);
        CREATE TRIGGER d3_commands_immutable_update BEFORE UPDATE ON command_requests
        BEGIN SELECT RAISE(ABORT,'immutable command'); END;
        CREATE TRIGGER d3_commands_immutable_delete BEFORE DELETE ON command_requests
        BEGIN SELECT RAISE(ABORT,'immutable command'); END;"""
    )
    conn.execute(
        "INSERT INTO command_requests VALUES(?,?,?,?,?,?,?,?)",
        ("old", 1, "owner", "old", "pause", "{}", "hash", "2026-10-24T00:00:00Z"),
    )
    conn.commit()

    assert migrate_replay_commands(conn)
    assert not migrate_replay_commands(conn)
    assert conn.execute("SELECT type FROM command_requests WHERE id='old'").fetchone()[0] == "pause"
    assert (
        conn.execute("PRAGMA foreign_key_list(command_receipts)").fetchone()[2]
        == "command_requests"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM command_requests WHERE id='old'")


def test_replay_commands_use_examiner_receipts_and_ledger_checkpoints(
    memory_db: sqlite3.Connection,
) -> None:
    api = ReplayCommandStore(RoleAccess(memory_db, Role.API))
    intent = ReplayCommandIntent(
        request_id="replay-1",
        owner_id="owner",
        type="replay_start",
        scope=ReplayScope(workspace_id="demo", run_id="run-1"),
        created_at="2026-10-24T00:00:00Z",
    )
    assert not api.submit(intent).existing
    assert api.submit(intent).existing
    examiner = RoleAccess(memory_db, Role.EXAMINER)
    controller = ReplayController(
        examiner,
        workspace_id="demo",
        run_id="run-1",
        controller_id="examiner-test",
    )
    assert (
        controller.process_pending(
            operational_at="2026-10-24T00:00:01Z",
            initial_simulated_at="2026-01-01T00:00:00Z",
        )
        == 1
    )
    checkpoint = api.checkpoint(workspace_id="demo", run_id="run-1")
    assert checkpoint is not None and checkpoint["receipt_state"] == "claimed"
    assert controller.state()["running"] is True
    assert (
        controller.advance(elapsed_seconds=2, operational_at="2026-10-24T00:00:03Z")["simulated_at"]
        == "2026-01-01T00:00:02Z"
    )
    checkpoint = api.checkpoint(workspace_id="demo", run_id="run-1")
    assert checkpoint is not None and checkpoint["simulated_at"] == "2026-01-01T00:00:02Z"
    assert checkpoint["receipt_state"] == "claimed"
    assert (
        memory_db.execute(
            "SELECT count(*) FROM command_receipts WHERE consumer='examiner' AND state='claimed'"
        ).fetchone()[0]
        == 1
    )
    assert ReplayCommandStore(examiner).pending("2026-10-24T00:00:03Z") == []
    api.submit(
        ReplayCommandIntent(
            request_id="replay-pause",
            owner_id="owner",
            type="replay_pause",
            scope=ReplayScope(workspace_id="demo", run_id="run-1"),
            created_at="2026-10-24T00:00:04Z",
        )
    )
    assert (
        controller.process_pending(
            operational_at="2026-10-24T00:00:05Z",
            initial_simulated_at="2026-01-01T00:00:00Z",
        )
        == 1
    )
    assert controller.state()["running"] is False
    checkpoint = api.checkpoint(workspace_id="demo", run_id="run-1")
    assert checkpoint is not None and checkpoint["receipt_state"] == "succeeded"
    assert checkpoint["running"] is False


def test_replay_restart_does_not_count_time_without_an_examiner_lease(
    memory_db: sqlite3.Connection,
) -> None:
    api = ReplayCommandStore(RoleAccess(memory_db, Role.API))
    api.submit(
        ReplayCommandIntent(
            request_id="replay-start",
            owner_id="owner",
            type="replay_start",
            scope=ReplayScope(workspace_id="demo", run_id="restart"),
            created_at="2026-10-24T00:00:00Z",
        )
    )
    examiner = RoleAccess(memory_db, Role.EXAMINER)
    first = ReplayController(
        examiner,
        workspace_id="demo",
        run_id="restart",
        controller_id="examiner-first",
    )
    first.process_pending(
        operational_at="2026-10-24T00:00:01Z",
        initial_simulated_at="2026-01-01T00:00:00Z",
    )
    first.advance(elapsed_seconds=5, operational_at="2026-10-24T00:00:06Z")

    restarted = ReplayController(
        examiner,
        workspace_id="demo",
        run_id="restart",
        controller_id="examiner-restarted",
    )
    restarted.process_pending(
        operational_at="2026-10-24T00:01:00Z",
        initial_simulated_at="2026-01-01T00:00:00Z",
    )
    assert restarted.state()["running"] is True
    assert restarted.state()["simulated_at"] == "2026-01-01T00:00:05Z"
    restarted.advance(elapsed_seconds=2, operational_at="2026-10-24T00:01:02Z")
    checkpoint = api.checkpoint(workspace_id="demo", run_id="restart")
    assert checkpoint is not None
    assert checkpoint["simulated_at"] == "2026-01-01T00:00:07Z"
    assert checkpoint["operational_at"] == "2026-10-24T00:01:02Z"


def test_replay_store_does_not_expand_v1_command_permissions(memory_db: sqlite3.Connection) -> None:
    legacy = CommandIntent(
        request_id="legacy-pause",
        owner_id="owner",
        type="pause",
        scope=CommandScope(connection_id="test", account_id="account"),
        created_at="2026-10-24T00:00:00Z",
    )
    assert not CommandStore(RoleAccess(memory_db, Role.API)).submit(legacy).existing
    assert CommandStore(RoleAccess(memory_db, Role.API)).get(legacy.request_id) == legacy
    with pytest.raises(AccessError):
        ReplayCommandStore(RoleAccess(memory_db, Role.EXECUTOR)).submit(
            ReplayCommandIntent(
                request_id="forged",
                owner_id="owner",
                type="replay_pause",
                scope=ReplayScope(workspace_id="demo", run_id="run-1"),
                created_at="2026-10-24T00:00:00Z",
            )
        )


# ---------------------------------------------------------------- wire contract --


def test_replay_controls_accept_exactly_the_documented_request_bodies(
    replay_api: TestClient,
) -> None:
    """The frozen D6 bodies work end to end; the UI's payload must match this, not more."""
    started = replay_api.post("/api/replay/start", json={"request_id": "wire-start"})
    paused = replay_api.post("/api/replay/pause", json={"request_id": "wire-pause"})
    speed = replay_api.post("/api/replay/speed", json={"request_id": "wire-speed", "speed": 10})
    for response in (started, paused, speed):
        assert response.status_code == 202
        assert set(response.json()) == {"ok", "request_id", "status", "status_url", "existing"}
        assert response.json()["status"] == "accepted"
        assert response.json()["ok"] is True
    assert started.json()["status_url"] == "/api/commands/wire-start"

    state = replay_api.get("/api/replay/state")
    assert state.status_code == 200
    assert {"running", "speed", "simulated_date", "mode", "available"} <= set(state.json())
    assert state.json()["speed"] in (1, 10, 100)


def test_replay_controls_refuse_unknown_fields_and_paths(replay_api: TestClient) -> None:
    """No client may name a workspace, run, database or an undocumented envelope field."""
    assert (
        replay_api.post("/api/replay/start", json={"request_id": "x", "version": "v2"}).status_code
        == 422
    )
    assert (
        replay_api.post(
            "/api/replay/start", json={"request_id": "x", "workspace_id": "someone-elses"}
        ).status_code
        == 422
    )
    for request_id in ("../../secret", "a/b", r"c\d", "", "x" * 200):
        assert (
            replay_api.post("/api/replay/start", json={"request_id": request_id}).status_code == 422
        )
    assert replay_api.post("/api/replay/start", json={}).status_code == 422


def test_replay_speed_refuses_non_finite_and_unsupported_values(replay_api: TestClient) -> None:
    """Infinity and NaN cannot even be expressed in the JSON envelope, so the model refuses them."""
    from probation.api.routes.replay import ReplaySpeedBody
    from probation.core.replay_controls import ReplayCommandIntent, ReplayScope

    for speed in (float("inf"), float("nan")):
        with pytest.raises(ValueError):
            ReplaySpeedBody.model_validate({"request_id": "x", "speed": speed})
        with pytest.raises(ValueError):
            ReplayCommandIntent(
                request_id="x",
                owner_id="owner",
                type="replay_speed",
                scope=ReplayScope(workspace_id="demo", run_id="active"),
                speed=speed,
                created_at="2026-03-01T11:00:00Z",
            )
    for speed in (0, -1, 5, 1.5, "10", True):
        assert (
            replay_api.post(
                "/api/replay/speed", json={"request_id": f"s-{speed}", "speed": speed}
            ).status_code
            == 422
        )
    for speed in (1, 10, 100):
        assert (
            replay_api.post(
                "/api/replay/speed", json={"request_id": f"s-{speed}", "speed": speed}
            ).status_code
            == 202
        )


def test_replay_duplicate_command_is_idempotent_and_changed_payload_conflicts(
    replay_api: TestClient,
) -> None:
    first = replay_api.post("/api/replay/start", json={"request_id": "dupe"})
    again = replay_api.post("/api/replay/start", json={"request_id": "dupe"})
    assert first.json()["existing"] is False
    assert again.status_code == 202
    assert again.json()["existing"] is True
    conflict = replay_api.post("/api/replay/pause", json={"request_id": "dupe"})
    assert conflict.status_code == 409


def test_replay_scope_is_derived_from_server_configuration_only(
    replay_api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scope comes from the authenticated owner plus the configured database, never a body.

    A different owner over the same database is a different workspace, and reusing that owner's
    request id is a payload conflict rather than a silent dedupe: identity is server-derived and
    the stored row is never rewritten.
    """
    expected = server_replay_scope("owner", settings.db_path.resolve())
    assert expected.run_id == "active"
    assert (
        replay_api.post("/api/replay/start", json={"request_id": "scope-check"}).status_code == 202
    )
    with get_connection(settings.db_path) as conn:
        stored = ReplayCommandStore(RoleAccess(conn, Role.API)).get("scope-check")
    assert stored is not None and stored.scope == expected

    monkeypatch.setitem(app.dependency_overrides, optional_owner, lambda: OwnerContext("other", ()))
    second = replay_api.post("/api/replay/start", json={"request_id": "scope-check"})
    assert second.status_code == 409
    with get_connection(settings.db_path) as conn:
        still = ReplayCommandStore(RoleAccess(conn, Role.API)).get("scope-check")
    assert still is not None and still.owner_id == "owner" and still.scope == expected
    assert (
        expected.workspace_id
        != server_replay_scope("other", settings.db_path.resolve()).workspace_id
    )
