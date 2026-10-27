"""Owner-scoped setup launches a scrubbed child, never a provider client in the API."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probation.api import gmail_setup as setup
from probation.api.authority import OwnerContext, require_owner
from probation.api.gmail_auth import OwnerApiCredential, hash_owner_token
from probation.api.routes.gmail_connector import GmailApiConfig, configure_gmail_api
from probation.connectors import gmail_read_grant
from probation.connectors.credentials import MODIFY_SCOPE, READONLY_SCOPE
from probation.connectors.types import ConnectorError
from probation.db.gmail_store import migrate_store, open_store


class FakeProcess:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


@pytest.fixture
def surface(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(setup.router)
    app.dependency_overrides[require_owner] = lambda: OwnerContext("owner", ())
    store = tmp_path / "private" / "gmail.db"
    monkeypatch.setattr(setup, "current_config", lambda: SimpleNamespace(store_path=store))
    spawned = []
    verified = {"value": False}

    def spawn(owner, target):
        process = FakeProcess()
        spawned.append((owner, target, process))
        return process

    manager = setup.SetupManager(spawn, lambda path, owner: verified["value"])
    write_manager = setup.SetupManager(spawn, lambda path, owner: verified["value"], kind="write")
    app.state.gmail_read_setup = manager
    app.state.gmail_write_setup = write_manager
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    return SimpleNamespace(
        app=app,
        client=client,
        manager=manager,
        write_manager=write_manager,
        store=store,
        spawned=spawned,
        verified=verified,
    )


def test_local_connection_state_is_empty_without_creating_a_store(surface):
    result = surface.client.get("/api/gmail/setup/read")
    assert result.status_code == 200
    assert result.json()["status"] == "not_connected"
    assert result.json()["connected"] is False
    write = surface.client.get("/api/gmail/setup/write")
    assert write.status_code == 200
    assert write.json()["status"] == "not_connected"
    assert write.json()["connected"] is False
    assert not surface.store.parent.exists()
    assert surface.spawned == []


def test_write_setup_is_async_and_separate_from_read(surface):
    body = {"version": "v1", "request_id": "write-1"}
    first = surface.client.post("/api/gmail/setup/write", json=body)
    assert first.status_code == 202
    assert first.json()["status"] == "awaiting_consent"
    assert first.json()["status_url"] == "/api/gmail/setup/write/write-1"
    duplicate = surface.client.post("/api/gmail/setup/write", json=body)
    assert duplicate.json()["existing"] is True
    assert len(surface.spawned) == 1
    surface.spawned[0][2].code = 0
    surface.verified["value"] = True
    result = surface.client.get("/api/gmail/setup/write/write-1").json()
    assert result["status"] == "succeeded"
    assert result["connected"] is True


def test_start_is_asynchronous_and_duplicate_request_never_relaunches(surface):
    body = {"version": "v1", "request_id": "read-1"}
    first = surface.client.post("/api/gmail/setup/read", json=body)
    assert first.status_code == 202
    assert first.json()["status"] == "awaiting_consent"
    assert first.json()["connected"] is False
    duplicate = surface.client.post("/api/gmail/setup/read", json=body)
    assert duplicate.json()["existing"] is True
    assert len(surface.spawned) == 1
    busy = surface.client.post(
        "/api/gmail/setup/read", json={"version": "v1", "request_id": "another"}
    )
    assert busy.status_code == 409
    assert len(surface.spawned) == 1


@pytest.mark.parametrize(
    "code,verified,status", [(0, True, "succeeded"), (0, False, "failed"), (1, True, "failed")]
)
def test_completion_requires_successful_child_and_readonly_registration(
    surface, code, verified, status
):
    surface.client.post("/api/gmail/setup/read", json={"version": "v1", "request_id": "flow-1"})
    surface.spawned[0][2].code = code
    surface.verified["value"] = verified
    result = surface.client.get("/api/gmail/setup/read/flow-1").json()
    assert result["status"] == status
    assert result["connected"] is (status == "succeeded")
    if status == "failed":
        surface.client.post("/api/gmail/setup/read", json={"version": "v1", "request_id": "flow-1"})
        assert len(surface.spawned) == 1


def test_foreign_owner_cannot_read_request_and_restart_does_not_resume_it(surface):
    surface.manager.start("owner", "owner-request", surface.store)
    surface.app.dependency_overrides[require_owner] = lambda: OwnerContext("foreign", ())
    assert surface.client.get("/api/gmail/setup/read/owner-request").status_code == 404
    surface.app.state.gmail_read_setup = setup.SetupManager(
        lambda *_args: pytest.fail("restarted consent"), lambda *_args: True
    )
    result = surface.client.get("/api/gmail/setup/read/owner-request").json()
    assert result["status"] == "unknown"
    assert result["connected"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"request_id": "x"},
        {"version": "v2", "request_id": "x"},
        {"version": "v1", "request_id": "../escape"},
        {"version": "v1", "request_id": "x", "account": "chosen-by-browser@example.test"},
        {"version": "v1", "request_id": "x", "refresh_token": "synthetic-refused-secret"},
    ],
)
def test_request_version_and_fields_are_closed(surface, body):
    assert surface.client.post("/api/gmail/setup/read", json=body).status_code == 422
    assert surface.spawned == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://foreign.example"},
        {"Origin": "null"},
        {"Origin": "http://localhost:bad"},
        {"Origin": "http://user:password@localhost:5173"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_foreign_or_malformed_origins_never_launch_setup(surface, headers):
    response = surface.client.post(
        "/api/gmail/setup/read", headers=headers, json={"version": "v1", "request_id": "origin"}
    )
    assert response.status_code == 403
    assert surface.spawned == []


def test_same_origin_local_frontend_can_start_setup(surface):
    response = surface.client.post(
        "/api/gmail/setup/read",
        headers={"Origin": "http://localhost:5173"},
        json={"version": "v1", "request_id": "local"},
    )
    assert response.status_code == 202


def test_real_owner_auth_rejects_missing_wrong_and_nonloopback_requests(tmp_path):
    token = "synthetic-owner-key"
    configure_gmail_api(
        GmailApiConfig(OwnerApiCredential("owner", hash_owner_token(token)), tmp_path / "absent.db")
    )
    try:
        app = FastAPI()
        app.include_router(setup.router)
        client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
        assert client.get("/api/gmail/setup/read").status_code == 401
        assert (
            client.get(
                "/api/gmail/setup/read", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        outside = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 50000))
        assert (
            outside.get(
                "/api/gmail/setup/read", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )
    finally:
        configure_gmail_api(None)


def test_child_environment_and_argv_contain_no_provider_or_owner_credentials(tmp_path, monkeypatch):
    captured = {}

    def popen(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return FakeProcess()

    monkeypatch.setenv("LLM_API_KEY", "synthetic-nebius-secret")
    monkeypatch.setenv("PROBATION_GMAIL_REFRESH_TOKEN", "synthetic-old-write-refresh")
    monkeypatch.setenv("PROBATION_GMAIL_OWNER_API_KEY", "synthetic-owner-secret")
    monkeypatch.setenv("PROBATION_ENV_FILE", "arbitrary-dotenv")
    monkeypatch.setenv("PROBATION_GMAIL_GRANT_WRITE_CANARY", "synthetic-write-grant")
    monkeypatch.setattr(setup.subprocess, "Popen", popen)
    setup._launch("owner", tmp_path / "private" / "store.db")
    child = captured["env"]
    assert child["PROBATION_WORKER_ROLE"] == "observation"
    assert child["PROBATION_GMAIL_OWNER_ID"] == "owner"
    assert child["PROBATION_GMAIL_STORE"] == str((tmp_path / "private" / "store.db").resolve())
    assert not any(
        key in child
        for key in (
            "LLM_API_KEY",
            "PROBATION_GMAIL_REFRESH_TOKEN",
            "PROBATION_GMAIL_OWNER_API_KEY",
            "PROBATION_ENV_FILE",
            "PROBATION_GMAIL_GRANT_WRITE_CANARY",
        )
    )
    assert captured["argv"][-1] == "--authorize-read"
    assert captured["shell"] is False
    assert captured["stdout"] == setup.subprocess.DEVNULL
    assert captured["stderr"] == setup.subprocess.DEVNULL
    setup._launch("owner", tmp_path / "private" / "store.db", "write")
    assert captured["argv"][-1] == "--authorize-write"


@pytest.mark.parametrize(
    "scopes,state,has_token,expected",
    [
        ([READONLY_SCOPE], "SHADOW", True, True),
        ([READONLY_SCOPE, MODIFY_SCOPE], "SHADOW", True, False),
        ([READONLY_SCOPE], "DISCONNECTED", True, False),
        ([READONLY_SCOPE], "SHADOW", False, False),
    ],
)
def test_connected_requires_exact_registered_read_identity(
    tmp_path, monkeypatch, scopes, state, has_token, expected
):
    monkeypatch.setattr(setup, "verify_owner_only", lambda path: None)
    monkeypatch.setattr(gmail_read_grant, "verify_owner_only", lambda path: None)
    store = tmp_path / "private" / "store.db"
    conn = open_store(store)
    migrate_store(conn)
    account = "synthetic@example.test"
    digest = hashlib.sha256(f"owner\0{account}\0Label_1".encode()).hexdigest()[:24]
    ref = f"cred-d6-read-{digest}"
    conn.execute(
        "INSERT INTO gmail_connections "
        "(connection_id,account_id,owner_id,state,selection_revision,label_ids,"
        "credential_ref,granted_scopes,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            f"d6-read-{digest}",
            account,
            "owner",
            state,
            1,
            '["Label_1"]',
            ref,
            json.dumps(scopes),
            "2026-10-26T10:00:00Z",
            "2026-10-26T10:00:00Z",
        ),
    )
    conn.close()
    if has_token:
        tokens = store.parent / "readonly_tokens"
        tokens.mkdir()
        (tokens / f"{ref}.refresh").write_text("synthetic-read-refresh")
    assert setup.registered_read_grant(store, "owner") is expected
    assert setup.registered_read_grant(store, "another-owner") is False


def test_connected_write_requires_read_connection_and_write_token(tmp_path, monkeypatch):
    from probation.connectors.gmail_read_grant import read_grant, write_grant

    monkeypatch.setattr(setup, "verify_owner_only", lambda path: None)
    monkeypatch.setattr(gmail_read_grant, "verify_owner_only", lambda path: None)
    store = tmp_path / "private" / "store.db"
    conn = open_store(store)
    migrate_store(conn)
    read = read_grant("owner", "synthetic@example.test", "Label_1")
    conn.execute(
        "INSERT INTO gmail_connections "
        "(connection_id,account_id,owner_id,state,selection_revision,label_ids,"
        "credential_ref,granted_scopes,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            read.connection_id,
            read.account_id,
            "owner",
            "SHADOW",
            1,
            '["Label_1"]',
            read.credential_ref,
            json.dumps([READONLY_SCOPE]),
            "2026-10-26T10:00:00Z",
            "2026-10-26T10:00:00Z",
        ),
    )
    conn.close()
    assert setup.registered_write_grant(store, "owner") is False
    write = write_grant("owner", "synthetic@example.test", "Label_1")
    tokens = store.parent / "write_tokens"
    tokens.mkdir()
    (tokens / f"{write.credential_ref}.refresh").write_text("synthetic-write-refresh")
    assert setup.registered_write_grant(store, "owner") is True
    assert setup.registered_write_grant(store, "another-owner") is False
    assert setup.registered_read_grant(store, "owner") is False


def test_launch_failure_remains_failed_until_an_explicit_new_request(surface):
    def reject(*args):
        raise OSError("synthetic-launch-denial")

    manager = setup.SetupManager(reject, lambda *_args: False)
    first = manager.start("owner", "failed-launch", surface.store)
    assert first.status == "failed"
    assert first.reason == "readonly_setup_launch_failed"
    assert manager.state("owner", "failed-launch").status == "failed"


def test_synthetic_profile_cannot_start_private_consent(surface, monkeypatch):
    monkeypatch.setattr(setup.settings, "app_profile", "synthetic")
    result = surface.client.post(
        "/api/gmail/setup/read", json={"version": "v1", "request_id": "public-refused"}
    )
    assert result.status_code == 403
    assert surface.spawned == []
    assert surface.client.get("/api/gmail/setup/read").json()["connected"] is False


def test_connection_acl_doubt_reports_disconnected(tmp_path, monkeypatch):
    store = tmp_path / "private" / "store.db"
    store.parent.mkdir()
    store.touch()

    def reject(path):
        raise ConnectorError("synthetic_acl_denial")

    monkeypatch.setattr(setup, "verify_owner_only", reject)
    assert setup.registered_read_grant(store, "owner") is False
