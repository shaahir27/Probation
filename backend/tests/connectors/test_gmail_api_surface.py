"""D4 minimum local API surface: loopback owner-authenticated Gmail connector routes.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5-7; docs/OCT29_DEMO_BUILD_PLAN.md section
12.1 ("Connections", "Health/readiness"); docs/CONTRACT.md sections 3 and 9. Offline only.
Locks: uniform typed 401 without detail leak, loopback origin enforcement, grants resolved from
verified registration rows (client-supplied account identity can never select a connection),
readiness versioned and composed from committed rows, mutations durable on D3's command path,
and an API process holding no Google credential and triggering no write transport.
"""

import json
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from probation.api import gmail_auth
from probation.api.app import app
from probation.api.gmail_auth import (
    ConnectorApiMisconfigured,
    OwnerApiCredential,
    hash_owner_token,
    verify_loopback_binding,
)
from probation.api.routes import gmail_connector
from probation.api.routes.gmail_connector import GmailApiConfig, configure_gmail_api
from probation.config import settings
from probation.connectors.readiness import READINESS_VERSION, connection_ref_hash
from probation.connectors.types import HttpResult
from probation.core.clock import Clock
from probation.db.connection import init_db
from probation.db.gmail_store import ConnectorAccess, StoreAccessError, migrate_store, open_store
from probation.packs.mail.connectors.gmail_read import GmailReadConnector

TOKEN = "owner-api-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
WATERMARK = "2026-10-24T08:59:30Z"
CREATED = "2026-10-24T08:00:00+00:00"
FORBIDDEN = (*"acct-1 acct-2 acct-3 owner-2 cred-ref-1 cohort-label gmail.readonly".split(), TOKEN)


@dataclass
class Env:
    store_path: Path
    engine_path: Path
    spy_calls: list[str] = field(default_factory=list)


class _SpyTransport:
    """Any transport use by the API process is a contract violation; record and fail."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | None] | None = None,
        access_token: str,
    ) -> HttpResult:
        self._calls.append(f"GET {url}")
        return HttpResult(status=200)

    def post(
        self,
        url: str,
        *,
        json_body: Mapping[str, object] | None = None,
        data: bytes | None = None,
        access_token: str,
    ) -> HttpResult:
        self._calls.append(f"POST {url}")
        return HttpResult(status=200)


_CAPABILITY = """INSERT INTO gmail_capabilities
 (connection_id,account_id,name,owner_role,supported,evidence,reason,manifest_version,verified_at)
 VALUES ('conn-1','acct-1',?,?,?,?,?,3,?)"""


def _register(
    access: ConnectorAccess, connection_id: str, account_id: str, owner_id: str, state: str
) -> None:
    access.write(
        "gmail_connections",
        """INSERT INTO gmail_connections
        (connection_id,account_id,owner_id,state,selection_revision,label_ids,credential_ref,
         granted_scopes,created_at,updated_at)
        VALUES (?,?,?,?,1,'["cohort-label"]','cred-ref-1','["gmail.readonly"]',?,?)""",
        (connection_id, account_id, owner_id, state, CREATED, CREATED),
    )


def _capability(
    access: ConnectorAccess, name: str, role: str, supported: bool, reason: str | None = None
) -> None:
    evidence = "supported" if supported else "unsupported"
    access.write(
        "gmail_capabilities",
        _CAPABILITY,
        (name, role, int(supported), evidence, reason, CREATED),
    )


def _seed(store_path: Path) -> None:
    boot = open_store(store_path)
    assert migrate_store(boot) is True
    boot.close()

    admin = ConnectorAccess(open_store(store_path), "administration")
    _register(admin, "conn-1", "acct-1", "owner-1", "ACTIVE")
    _register(admin, "conn-2", "acct-2", "owner-2", "ACTIVE")
    _register(admin, "conn-3", "acct-3", "owner-1", "AUTHORIZED")
    admin.conn.close()

    reader = ConnectorAccess(open_store(store_path), "read_worker")
    _capability(reader, "read", "read", True)
    reader.conn.close()

    cursor = ConnectorAccess(open_store(store_path), "ingestor")
    cursor.write(
        "gmail_sync_cursors",
        """INSERT INTO gmail_sync_cursors
        (connection_id,account_id,resource_key,role,filter_revision,committed_history_id,fence,
         watermark_at,catchup_complete,created_at,updated_at)
        VALUES ('conn-1','acct-1','cohort','read',1,42,1,?,1,?,?)""",
        (WATERMARK, CREATED, CREATED),
    )
    cursor.conn.close()

    executor = ConnectorAccess(open_store(store_path), "executor")
    for name in ("archive", "trash", "send", "reconciliation", "undo_history_proof"):
        _capability(executor, name, "write", True)
    _capability(executor, "conditional_write", "write", False, "modify_has_no_precondition_c1")
    executor.conn.close()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    store_path = tmp_path / "private" / "connectors" / "gmail_metadata.db"
    engine_path = tmp_path / "engine.db"
    init_db(engine_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    _seed(store_path)
    monkeypatch.setattr(settings, "db_path", engine_path)
    monkeypatch.setattr(app.state, "clock", Clock.replay(NOW))
    configure_gmail_api(
        GmailApiConfig(
            owner_credential=OwnerApiCredential("owner-1", hash_owner_token(TOKEN)),
            store_path=store_path,
        )
    )
    environment = Env(store_path=store_path, engine_path=engine_path)
    yield environment
    configure_gmail_api(None)


def _client(origin: tuple[str, int] = ("127.0.0.1", 51234)) -> TestClient:
    return TestClient(app, client=origin)


def _assert_clean(payload_text: str) -> None:
    for forbidden in FORBIDDEN:
        assert forbidden not in payload_text


def _post_command(client: TestClient, ref: str, request_id: str, command: str) -> Response:
    body = {"version": "v1", "request_id": request_id, "command": command}
    return client.post(f"/api/gmail/connections/{ref}/commands", headers=AUTH, json=body)


def test_configured_bind_hosts_are_loopback_only() -> None:
    assert gmail_auth.CONNECTOR_API_BIND_HOSTS == ("127.0.0.1", "::1")
    assert verify_loopback_binding("127.0.0.1") == "127.0.0.1"
    assert verify_loopback_binding("::1") == "::1"
    for host in ("0.0.0.0", "192.168.1.5", "203.0.113.9", ""):
        with pytest.raises(ConnectorApiMisconfigured):
            verify_loopback_binding(host)
        assert not gmail_auth.is_loopback_host(host)


def test_config_rejects_non_loopback_bind_host(tmp_path: Path) -> None:
    credential = OwnerApiCredential("owner-1", hash_owner_token(TOKEN))
    with pytest.raises(ConnectorApiMisconfigured):
        GmailApiConfig(
            owner_credential=credential, store_path=tmp_path / "s.db", bind_host="0.0.0.0"
        )


def test_non_loopback_client_origin_denied_even_with_valid_credential(env: Env) -> None:
    response = _client(("203.0.113.9", 51234)).get("/api/gmail/connections", headers=AUTH)
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "401", "message": "owner_credential_required"}}


def test_missing_or_wrong_credential_is_uniform_typed_401(env: Env) -> None:
    client = _client()
    missing = client.get("/api/gmail/connections")
    wrong = client.get("/api/gmail/connections", headers={"Authorization": "Bearer not-the-token"})
    malformed = client.get("/api/gmail/connections", headers={"Authorization": TOKEN})
    for response in (missing, wrong, malformed):
        assert response.status_code == 401
        assert response.json() == {"error": {"code": "401", "message": "owner_credential_required"}}
    # Mutations and per-connection routes are authenticated exactly like the list route.
    for path in ("/api/gmail/connections/conn-1", "/api/gmail/connections/conn-1/readiness"):
        assert client.get(path).status_code == 401
    body = {"version": "v1", "request_id": "r-no-auth", "command": "pause"}
    mutation = client.post("/api/gmail/connections/conn-1/commands", json=body)
    assert mutation.status_code == 401


def test_unconfigured_api_fails_closed(env: Env) -> None:
    configure_gmail_api(None)
    response = _client().get("/api/gmail/connections", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "connector_api_not_configured"


def test_connections_list_scoped_to_verified_owner_and_hides_identity(env: Env) -> None:
    response = _client().get("/api/gmail/connections", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    listed = {item["connection_id"] for item in body["connections"]}
    assert listed == {"conn-1", "conn-3"}  # owner-2's conn-2 is invisible
    for item in body["connections"]:
        assert set(item) == {"connection_id", "connection_ref", "state"}
        assert item["connection_ref"] == connection_ref_hash(item["connection_id"])
    _assert_clean(response.text)


def test_client_supplied_account_id_cannot_select_another_connection(env: Env) -> None:
    client = _client()
    # owner-1 cannot read owner-2's connection by id, by ref hash, or via a forged account id.
    assert client.get("/api/gmail/connections/conn-2", headers=AUTH).status_code == 404
    assert client.get("/api/gmail/connections/conn-2/readiness", headers=AUTH).status_code == 404
    ref_hash = connection_ref_hash("conn-2")
    assert client.get(f"/api/gmail/connections/{ref_hash}", headers=AUTH).status_code == 404
    assert _post_command(client, "conn-2", "r-forge", "pause").status_code == 404
    # A client-supplied account id in the query string is ignored: the recorded command scope
    # carries the account from the verified registration row, never the claimed one.
    body = {"version": "v1", "request_id": "r-scope", "command": "pause"}
    response = client.post(
        "/api/gmail/connections/conn-1/commands?account_id=acct-2", headers=AUTH, json=body
    )
    assert response.status_code == 202
    scope = json.loads(_command_rows(env, "r-scope")[2])
    assert scope["connection_id"] == "conn-1"
    assert scope["account_id"] == "acct-1"
    _assert_clean(response.text)


def test_mutation_body_cannot_carry_account_identity(env: Env) -> None:
    body = {"version": "v1", "request_id": "r-extra", "command": "pause", "account_id": "acct-2"}
    response = _client().post("/api/gmail/connections/conn-1/commands", headers=AUTH, json=body)
    assert response.status_code == 422  # extra fields forbidden; identity is never client input


def test_detail_and_readiness_reachable_by_published_ref_hash(env: Env) -> None:
    ref = connection_ref_hash("conn-1")
    response = _client().get(f"/api/gmail/connections/{ref}", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["connection_id"] == "conn-1"
    readiness = _client().get(f"/api/gmail/connections/{ref}/readiness", headers=AUTH)
    assert readiness.status_code == 200
    assert readiness.json()["connection_id"] == "conn-1"


def test_readiness_is_versioned_and_composed_from_committed_rows(env: Env) -> None:
    response = _client().get("/api/gmail/connections/conn-1/readiness", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["readiness_version"] == READINESS_VERSION
    assert body["manifest_version"] == 3  # committed capability rows, never a live call
    assert body["state"] == "ACTIVE"
    assert body["blocking_reason"] is None
    assert body["observation_allowed"] is True
    assert body["dependent_autonomy_permitted"] is True
    capabilities = {item["name"]: item for item in body["capabilities"]}
    expected = "read archive trash send reconciliation undo_history_proof conditional_write"
    assert set(capabilities) == {*expected.split(), "attribution"}
    assert capabilities["read"]["supported"] is True
    assert capabilities["send"]["supported"] is True
    # C1: conditional write is unsupported no matter what any local row claims.
    assert capabilities["conditional_write"]["supported"] is False
    assert capabilities["conditional_write"]["reason"] == "modify_has_no_precondition_c1"
    # C9: Gmail history carries no actor identity.
    assert capabilities["attribution"]["supported"] is False
    # Undo proof fails closed: the API holds no effect anchor and invents none.
    assert capabilities["undo_history_proof"]["supported"] is False
    assert capabilities["undo_history_proof"]["reason"] == "undo_history_anchor_unresolved"
    freshness = body["freshness"]
    assert freshness["committed_history_id"] == 42
    assert freshness["watermark_at"] == WATERMARK
    assert freshness["catchup_complete"] is True
    assert freshness["stale"] is False
    assert freshness["fresh"] is True
    assert freshness["age_seconds"] == pytest.approx(30.0)
    _assert_clean(response.text)


def test_readiness_without_committed_cursor_fails_closed(env: Env) -> None:
    response = _client().get("/api/gmail/connections/conn-3/readiness", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["manifest_version"] == 0
    assert body["freshness"]["resync_required"] is True
    assert body["freshness"]["stale"] is True
    assert body["blocking_reason"] == "resync_required"
    assert body["dependent_autonomy_permitted"] is False
    fresh = _client().get("/api/gmail/connections/conn-3", headers=AUTH).json()["freshness"]
    assert fresh["committed_history_id"] is None and fresh["watermark_at"] is None
    assert fresh["catchup_complete"] is False and fresh["resync_required"] is True


def _command_rows(env: Env, request_id: str) -> tuple[str, str, str]:
    with sqlite3.connect(env.engine_path) as engine:
        return engine.execute(  # type: ignore[return-value]
            "SELECT type, owner_id, scope_json FROM command_requests WHERE id=?", (request_id,)
        ).fetchone()


def test_pause_and_disconnect_record_durable_idempotent_commands(env: Env) -> None:
    client = _client()
    first = _post_command(client, "conn-1", "r-pause-1", "pause")
    assert first.status_code == 202
    payload = first.json()
    assert payload["status"] == "recorded"
    assert payload["status_url"] == "/api/commands/r-pause-1"
    # Idempotent replay of the identical immutable request is not a duplicate.
    assert _post_command(client, "conn-1", "r-pause-1", "pause").status_code == 202
    command_type, owner_id, scope_json = _command_rows(env, "r-pause-1")
    assert command_type == "pause"
    assert owner_id == "owner-1"
    assert json.loads(scope_json)["account_id"] == "acct-1"
    # Same request id, different payload: a conflict, never a silent overwrite.
    assert _post_command(client, "conn-1", "r-pause-1", "resume").status_code == 409
    disconnect = _post_command(client, "conn-1", "r-cut-1", "disconnect")
    assert disconnect.status_code == 202
    assert _command_rows(env, "r-cut-1")[0] == "revoke"
    _assert_clean(first.text + disconnect.text)


def test_api_store_authority_cannot_write(env: Env) -> None:
    api = ConnectorAccess(open_store(env.store_path), "api")
    try:
        for table in ("gmail_connections", "gmail_capabilities", "gmail_sync_cursors"):
            with pytest.raises(StoreAccessError):
                api.write(table, "INSERT INTO x VALUES (1)")
    finally:
        api.conn.close()


def test_api_holds_no_google_credential_and_triggers_no_transport(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Inject a read provider (the strongest thing the API process may ever see) and prove the
    # routes give it no reach: no route touches its transport, and it exposes no write method.
    connector = GmailReadConnector(
        _SpyTransport(env.spy_calls),
        connection_id="conn-1",
        account_id="acct-1",
        access_token="injected-read-token",
        clock=Clock.replay(NOW),
    )
    monkeypatch.setattr(app.state, "gmail_read_provider", connector, raising=False)
    client = _client()
    assert client.get("/api/gmail/connections", headers=AUTH).status_code == 200
    assert client.get("/api/gmail/connections/conn-1", headers=AUTH).status_code == 200
    assert client.get("/api/gmail/connections/conn-1/readiness", headers=AUTH).status_code == 200
    assert _post_command(client, "conn-1", "r-transport", "pause").status_code == 202
    assert env.spy_calls == []  # no route triggered any provider call, read or write
    # The injected read provider exposes no write surface, and the API gained none from it.
    assert not hasattr(connector, "apply_mail")
    assert not hasattr(connector, "send_mail")
    assert not hasattr(app.state, "gmail_write_provider")


def test_api_modules_reference_no_google_credential_or_write_transport() -> None:
    sources = ""
    for module in (gmail_connector, gmail_auth):
        sources += Path(module.__file__).read_text(encoding="utf-8")
    forbidden = "gmail_write HttpTransport access_token googleapis refresh_token client_secret"
    for token in forbidden.split():
        assert token not in sources
