"""HTTP handles check schema capabilities without migrating old databases."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.authority import OwnerContext, optional_owner
from probation.config import settings
from probation.core.clock import Clock
from probation.workers.gmail_runtime import GmailRuntime, RuntimeRole


@pytest.mark.parametrize("tables_only", [False, True])
def test_pre_lifecycle_database_returns_upgrade_required_without_mutation(
    tmp_path, monkeypatch, tables_only
):
    path = tmp_path / "old-capabilities.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE admin_commands(id TEXT); CREATE TABLE drift_receipts(id TEXT);"
        )
        if tables_only:
            for table in (
                "outcome_events",
                "command_receipts",
                "execution_attempts",
                "command_requests",
                "user_responses",
                "actions",
            ):
                conn.execute(f'CREATE TABLE "{table}"(id TEXT)')
        original = conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    monkeypatch.setattr(settings, "db_path", path)
    app.dependency_overrides[optional_owner] = lambda: OwnerContext("test-owner", ())
    with TestClient(app) as client:
        response = client.get("/api/queue")
    app.dependency_overrides.pop(optional_owner, None)
    assert response.status_code == 503
    assert "upgrade required" in response.json()["error"]["message"].lower()
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == original
        )


def _publish(tmp_path, roles, generated_at="2026-01-01T10:00:00Z"):
    from probation.core.runtime_status import publish_runtime_status, runtime_status_path

    path = runtime_status_path(tmp_path / "engine.db")
    assert publish_runtime_status(
        path,
        generated_at=generated_at,
        clock_mode="replay",
        roles=roles,
    )
    return path


def _role(name, ready, code=None, at=None):
    from probation.core.runtime_status import RoleReadiness

    return RoleReadiness(
        role=name, state="running" if ready else "degraded", ready=ready, code=code, last_tick_at=at
    )


def test_readiness_document_round_trip_and_ageing(tmp_path):
    """A fresh document is honoured; stale, corrupt or unknown-version documents are refused."""
    from datetime import UTC, datetime

    from probation.core.runtime_status import (
        STATUS_STALENESS_SECONDS,
        read_runtime_status,
        runtime_status_path,
    )

    missing = read_runtime_status(
        runtime_status_path(tmp_path / "none.db"),
        now=datetime.now(UTC),
        clock_mode="live",
        role_names=("brain",),
    )
    assert missing["available"] is False
    assert missing["reason"] == "status_document_absent"

    path = _publish(tmp_path, {"brain": _role("brain", True, at="2026-01-01T09:59:59Z")})
    now = datetime.fromisoformat("2026-01-01T10:00:30+00:00")
    fresh = read_runtime_status(path, now=now, clock_mode="replay", role_names=("brain", "api"))
    assert fresh["available"] is True
    assert [row["role"] for row in fresh["roles"]] == ["api", "brain"]
    assert fresh["roles"][1]["ready"] is True
    # A role the supervisor never mentioned is reported absent, never assumed ready.
    assert fresh["roles"][0] == {
        "role": "api",
        "state": "unavailable",
        "ready": False,
        "code": "status_line_absent",
        "last_tick_at": None,
    }

    later = now + timedelta(seconds=STATUS_STALENESS_SECONDS + 1)
    assert (
        read_runtime_status(path, now=later, clock_mode="replay", role_names=())["reason"]
        == "status_document_stale"
    )

    path.write_text("{not json", encoding="utf-8")
    assert (
        read_runtime_status(path, now=now, clock_mode="replay", role_names=())["reason"]
        == "status_document_unparsable"
    )
    path.write_text('{"version": 99, "generated_at": "x", "roles": []}', encoding="utf-8")
    assert (
        read_runtime_status(path, now=now, clock_mode="replay", role_names=())["reason"]
        == "status_document_unsupported"
    )


def test_readiness_endpoint_reports_absent_document_as_unavailable(tmp_path, monkeypatch):
    """GET /api/readiness is authenticated, read-only, and never optimistic without a document."""
    from probation.api.authority import OwnerContext, require_owner
    from probation.config import settings
    from probation.db.connection import init_db

    engine = tmp_path / "engine.db"
    init_db(engine)
    monkeypatch.setattr(settings, "db_path", engine)
    with TestClient(app) as client:
        # No owner credential is configured in this process: a private read is unavailable,
        # never served from an absent token.
        assert client.get("/api/readiness").status_code == 503

    app.dependency_overrides[require_owner] = lambda: OwnerContext("owner", ())
    with TestClient(app) as client:
        body = client.get("/api/readiness").json()
    app.dependency_overrides.clear()
    assert body["available"] is False
    assert body["reason"] == "status_document_absent"
    assert body["roles"] == []
    assert body["api_live"] is True


def test_supervisor_publishes_readiness_from_child_status_lines(tmp_path, monkeypatch):
    """Liveness plus a child status line makes a role ready; a dead process does not."""
    from probation.workers.gmail_role_loops import WorkEvidence, WorkLedger

    ledger = WorkLedger()
    runtime = GmailRuntime(
        db_path=tmp_path / "engine.db",
        private_store_path=tmp_path / "private" / "store.db",
        env={"CLOCK_MODE": "replay"},
        clock=Clock.replay(datetime(2026, 1, 1, tzinfo=UTC)),
        work=ledger,
        spawn=lambda role, env: None,
    )
    plans = {role: ({}, "none", True) for role in RuntimeRole}

    class _Alive:
        stderr = None

        def poll(self):
            return None

    published = runtime._publish_readiness(plans, {r: _Alive() for r in RuntimeRole}, {})
    assert published is True
    document = json.loads(
        (tmp_path / "engine.db").with_name("probation_runtime_status.json").read_text("utf-8")
    )
    rows = {row["role"]: row for row in document["roles"]}
    # No tick reported yet: every engine role is unready even though its process is alive.
    assert rows["brain"]["ready"] is False
    assert rows["brain"]["code"] == "work_status_absent"

    # The supervisor clock is scenario time; the evidence must be stamped relative to it.
    ledger.record("brain", WorkEvidence(at=runtime.clock.now_iso(), stages=("verify",)))
    runtime._publish_readiness(plans, {r: _Alive() for r in RuntimeRole}, {})
    document = json.loads(
        (tmp_path / "engine.db").with_name("probation_runtime_status.json").read_text("utf-8")
    )
    rows = {row["role"]: row for row in document["roles"]}
    assert rows["brain"]["ready"] is True
    assert rows["api"]["ready"] is True

    # A process that exited is never reported ready, no matter what it last claimed.
    class _Dead:
        stderr = None

        def poll(self):
            return 0

    runtime._publish_readiness(plans, {r: _Dead() for r in RuntimeRole}, {})
    document = json.loads(
        (tmp_path / "engine.db").with_name("probation_runtime_status.json").read_text("utf-8")
    )
    rows = {row["role"]: row for row in document["roles"]}
    assert rows["brain"]["ready"] is False
    assert rows["brain"]["state"] == "exited"


def test_supervised_roles_match_the_runtime_roles_exactly():
    """A new role cannot silently vanish from the readiness surface."""
    from probation.core.runtime_status import SUPERVISED_ROLES

    assert set(SUPERVISED_ROLES) == {role.value for role in RuntimeRole}
