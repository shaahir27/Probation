"""Tests for live Gmail connector wiring, credential flow, and runtime entrypoints.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 11 (row 31), docs/D4_LIVE_TEST_MANIFEST.md section 9.
All tests in this module run offline and synthetic. Live network calls stay Phase 7.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.routes.gmail_connector import (
    configure_gmail_api,
    configure_gmail_api_from_env,
)
from probation.config import settings
from probation.connectors.credentials import RoleCredentialProvider
from probation.connectors.credentials_state import (
    ProvisionedGrant,
    RefreshTokenStore,
    apply_owner_only,
)
from probation.connectors.types import (
    ConnectorError,
    CredentialUnavailable,
    HttpResult,
    HttpTransport,
    PayloadReader,
)
from probation.core.clock import Clock, parse_timestamp
from probation.db.access import Role
from probation.db.connection import get_role_connection, init_db
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
from probation.packs.mail.connectors.gmail_auth import TokenHttpResponse
from probation.packs.mail.connectors.gmail_transport import (
    GmailHttpTransport,
    GoogleTokenTransport,
)
from probation.workers.gmail_live import (
    build_live_provider,
    parse_live_client,
)
from probation.workers.gmail_runtime import (
    GmailRuntime,
    RuntimeRole,
    build_role_context,
    main,
)
from probation.workers.gmail_runtime_provisioning import (
    EXECUTOR_PROVISIONS,
    LiveExecutorDeps,
    _live_effects,
    executor_steps,
)


@pytest.fixture
def engine(tmp_path: Path) -> Path:
    path = tmp_path / "engine.db"
    init_db(path)
    return path


@pytest.fixture
def private_store(tmp_path: Path) -> Path:
    path = tmp_path / "private" / "gmail_metadata.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    apply_owner_only(path.parent, is_dir=True)
    conn = open_store(path)
    assert migrate_store(conn) is True
    conn.close()
    return path


@pytest.fixture
def clock() -> Clock:
    return Clock.replay(parse_timestamp("2026-10-24T09:00:00Z"))


def test_default_off_keeps_observation_not_provisioned(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    context = build_role_context(
        RuntimeRole.OBSERVATION,
        db_path=engine,
        private_store_path=private_store,
        env={},
        clock=clock,
        live=False,
    )
    try:
        assert context.provisioning.not_provisioned == ("observation",)
    finally:
        context.close()

    exit_code = main(
        ["--role", "observation", "--db", str(engine), "--private-store", str(private_store)]
    )
    assert exit_code == 2


def test_live_opt_in_requires_env(
    engine: Path,
    private_store: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("PROBATION_RUNTIME_LIVE", raising=False)
    exit_code = main(
        [
            "--role",
            "observation",
            "--db",
            str(engine),
            "--private-store",
            str(private_store),
            "--live",
        ]
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "runtime_refused: live_runtime_unauthorized" in captured.err


def test_bundle_parse_refuses_missing_fields() -> None:
    for invalid in ("", "not-json", "[]", "123"):
        with pytest.raises(ConnectorError) as exc_info:
            parse_live_client(invalid)
        assert exc_info.value.safe_code == "live_grant_malformed"

    missing_cases = [
        {"client_secret": "s", "refresh_token": "r"},
        {"client_id": "c", "refresh_token": "r"},
        {"client_id": "c", "client_secret": "s"},
        {"client_id": "c", "client_secret": "s", "refresh_token": "r", "extra": "x"},
        {"client_id": "", "client_secret": "s", "refresh_token": "r"},
        {"client_id": "c", "client_secret": "s", "refresh_token": "x" * 5000},
    ]
    for case in missing_cases:
        with pytest.raises(ConnectorError) as exc_info:
            parse_live_client(json.dumps(case))
        assert exc_info.value.safe_code == "live_grant_malformed"

    parsed = parse_live_client(
        json.dumps({"client_id": "client-id-123", "client_secret": "csec", "refresh_token": "rtok"})
    )
    assert parsed.client_id == "client-id-123"
    assert parsed.client_secret == "csec"
    assert parsed.refresh_token == "rtok"


def test_initial_bundle_installed_and_refresh_lazy(clock: Clock) -> None:
    grant = ProvisionedGrant("read", "conn-1", "user@example.com", "cred-ref-1")
    env = {
        grant.env_name: json.dumps(
            {"client_id": "client-id-123", "client_secret": "csec", "refresh_token": "rtok"}
        )
    }

    class FakeApiTransport:
        def get(
            self, url: str, *, params: dict[str, object] | None = None, access_token: str
        ) -> HttpResult:
            if "profile" in url or "userinfo" in url:
                return HttpResult(
                    200, json.dumps({"emailAddress": "user@example.com"}).encode(), {}
                )
            raise AssertionError(f"unexpected url: {url}")

    class FakeTokenTransport:
        def post_form(
            self,
            url: str,
            form: Mapping[str, str],
        ) -> TokenHttpResponse:
            return TokenHttpResponse(
                200,
                {
                    "access_token": "live-tok-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                },
            )

    provider = build_live_provider(
        grant=grant,
        env=env,
        clock=clock,
        api_transport=FakeApiTransport(),  # type: ignore[arg-type]
        token_transport=FakeTokenTransport(),  # type: ignore[arg-type]
    )
    assert provider.resolve_access("read").reveal() == "live-tok-1"

    class MismatchApiTransport:
        def get(
            self, url: str, *, params: dict[str, object] | None = None, access_token: str
        ) -> HttpResult:
            return HttpResult(200, json.dumps({"emailAddress": "other@example.com"}).encode(), {})

    with pytest.raises(CredentialUnavailable) as exc_info:
        build_live_provider(
            grant=grant,
            env=env,
            clock=clock,
            api_transport=MismatchApiTransport(),  # type: ignore[arg-type]
            token_transport=FakeTokenTransport(),  # type: ignore[arg-type]
        )
    assert exc_info.value.safe_code == "account_binding_mismatch"


def test_initial_refresh_is_persisted_to_the_acl_token_store(tmp_path: Path, clock: Clock) -> None:
    grant = ProvisionedGrant("read", "conn-1", "user@example.com", "cred-ref-1")
    env = {
        grant.env_name: json.dumps(
            {"client_id": "client-id-123", "client_secret": "csec", "refresh_token": "rtok"}
        )
    }

    class FakeApiTransport:
        def get(
            self, url: str, *, params: dict[str, object] | None = None, access_token: str
        ) -> HttpResult:
            return HttpResult(200, json.dumps({"emailAddress": "user@example.com"}).encode(), {})

    class FakeTokenTransport:
        def post_form(self, url: str, form: Mapping[str, str]) -> TokenHttpResponse:
            return TokenHttpResponse(
                200,
                {
                    "access_token": "live-tok-1",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "refresh_token": "rotated-refresh",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                },
            )

    token_store = RefreshTokenStore(tmp_path / "readonly_tokens", enforce_acl=False)
    provider = build_live_provider(
        grant=grant,
        env=env,
        clock=clock,
        api_transport=FakeApiTransport(),  # type: ignore[arg-type]
        token_transport=FakeTokenTransport(),  # type: ignore[arg-type]
        token_store=token_store,
    )
    assert provider.resolve_access("read").reveal() == "live-tok-1"
    persisted = tmp_path / "readonly_tokens" / f"{grant.credential_ref}.refresh"
    assert persisted.read_text(encoding="utf-8") == "rotated-refresh"


def test_executor_live_effects_provisioned(
    engine: Path, private_store: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    grant = ProvisionedGrant("write", "conn-1", "user@example.com", "cred-ref-1")
    env = {
        "PROBATION_RUNTIME_LIVE": "1",
        "PROBATION_RUNTIME_GRANT": "conn-1|user@example.com|cred-ref-1",
        grant.env_name: json.dumps(
            {"client_id": "client-id-123", "client_secret": "csec", "refresh_token": "rtok"}
        ),
    }

    conn = open_store(private_store)
    conn.execute(
        "INSERT INTO gmail_connections (connection_id, account_id, owner_id, state, selection_revision, label_ids, credential_ref, granted_scopes, created_at, updated_at) "
        "VALUES ('conn-1', 'user@example.com', 'owner-1', 'ACTIVE', 1, '[\"PROBATION\"]', 'cred-ref-1', '[\"https://www.googleapis.com/auth/gmail.modify\", \"https://www.googleapis.com/auth/gmail.send\"]', '2026-10-24T08:00:00Z', '2026-10-24T08:00:00Z')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        GoogleTokenTransport,
        "post_form",
        lambda self, url, form: TokenHttpResponse(
            200,
            {
                "access_token": "write-tok-1",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.send",
            },
        ),
    )
    monkeypatch.setattr(
        GmailHttpTransport,
        "get",
        lambda self, url, params=None, access_token="": HttpResult(
            200,
            json.dumps(
                {"emailAddress": "user@example.com", "id": "PROBATION", "name": "PROBATION"}
            ).encode(),
            {},
        ),
    )

    ctx = build_role_context(
        RuntimeRole.EXECUTOR,
        db_path=engine,
        private_store_path=private_store,
        env=env,
        clock=clock,
        live=True,
    )
    try:
        assert ctx.provisioning.status_of("effects") == "provisioned"
        assert "effects" not in ctx.provisioning.not_provisioned
    finally:
        ctx.close()


def test_executor_refuses_without_connection_or_label(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    conn = get_role_connection(engine, Role.EXECUTOR)
    connectors = (
        ConnectorAccess(open_store(private_store), "executor"),
        ConnectorAccess(open_store(private_store), "administration"),
    )
    try:
        executor_steps(conn, connectors, clock, live=None)
        provisions = EXECUTOR_PROVISIONS
        assert any(p.status == "not_provisioned" for p in provisions)
    finally:
        for c in connectors:
            c.conn.close()
        conn.close()


def test_executor_effects_runs_responses_then_queue(
    engine: Path, private_store: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn_store = open_store(private_store)
    conn_store.execute(
        "INSERT INTO gmail_connections (connection_id, account_id, owner_id, state, selection_revision, label_ids, credential_ref, granted_scopes, created_at, updated_at) "
        "VALUES ('conn-1', 'user@example.com', 'owner-1', 'ACTIVE', 1, '[\"PROBATION\"]', 'cred-ref-1', '[\"https://www.googleapis.com/auth/gmail.modify\"]', '2026-10-24T08:00:00Z', '2026-10-24T08:00:00Z')"
    )
    conn_store.commit()
    conn_store.close()

    connectors = (
        ConnectorAccess(open_store(private_store), "executor"),
        ConnectorAccess(open_store(private_store), "administration"),
    )
    engine_conn = get_role_connection(engine, Role.EXECUTOR)

    mock_executor = MagicMock()
    mock_executor.process_responses.return_value = 2
    mock_executor.process_queue.return_value = ["act-1", "act-2"]

    monkeypatch.setattr(
        "probation.workers.gmail_runtime_provisioning.Executor",
        lambda *args, **kwargs: mock_executor,
    )
    monkeypatch.setattr(
        "probation.workers.gmail_runtime_provisioning.GmailReadConnector.enumerate_cohort",
        lambda self, sel: None,
    )
    monkeypatch.setattr(
        "probation.workers.gmail_runtime_provisioning.build_write_manifest",
        lambda *args, **kwargs: MagicMock(states=()),
    )
    monkeypatch.setattr(
        "probation.workers.gmail_runtime_provisioning.persist_write_capabilities",
        lambda *args, **kwargs: None,
    )

    mock_provider = MagicMock(spec=RoleCredentialProvider)
    mock_provider.granted_scopes.return_value = ("https://www.googleapis.com/auth/gmail.modify",)
    mock_provider.resolve_access.return_value = MagicMock(reveal=lambda: "dummy-tok")

    live_deps = LiveExecutorDeps(
        transport=MagicMock(spec=HttpTransport),
        provider=mock_provider,
        payloads=MagicMock(spec=PayloadReader),
        forward_allowlist=("test@forward.test",),
    )

    try:
        effects_fn = _live_effects(engine_conn, connectors, clock, live_deps)
        result = effects_fn(engine_conn, "2026-10-24T09:00:00Z", 10)
        assert result == 4
        mock_executor.process_responses.assert_called_once_with("2026-10-24T09:00:00Z", 10)
        mock_executor.process_queue.assert_called_once_with("2026-10-24T09:00:00Z")
    finally:
        for c in connectors:
            c.conn.close()
        engine_conn.close()


def test_child_env_carries_own_identity_and_live_flag(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    grant_read = ProvisionedGrant("read", "conn-1", "user@example.com", "cred-ref-read")
    grant_write = ProvisionedGrant("write", "conn-1", "user@example.com", "cred-ref-write")
    env = {
        "PROBATION_RUNTIME_LIVE": "1",
        "PROBATION_RUNTIME_GRANT": "conn-1|user@example.com|cred-ref-read",
        grant_read.env_name: "read-json-bundle",
        grant_write.env_name: "write-json-bundle",
        "PATH": "C:\\Windows",
    }
    runtime = GmailRuntime(
        db_path=engine,
        private_store_path=private_store,
        env=env,
        clock=clock,
    )
    child_env_read = runtime._child_env(RuntimeRole.OBSERVATION, grant_read)
    assert child_env_read.get("PROBATION_RUNTIME_LIVE") == "1"
    assert child_env_read.get("PROBATION_RUNTIME_GRANT") == "conn-1|user@example.com|cred-ref-read"
    assert child_env_read.get(grant_read.env_name) == "read-json-bundle"
    assert grant_write.env_name not in child_env_read


def test_api_unconfigured_503_and_configured_serves(engine: Path, private_store: Path) -> None:
    configure_gmail_api(None)

    client = TestClient(app, client=("127.0.0.1", 50000))
    resp = client.get("/api/gmail/connections", headers={"Authorization": "Bearer any-token"})
    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "connector_api_not_configured"

    env = {
        "PROBATION_GMAIL_OWNER_API_KEY": "test-key-123",
        "PROBATION_GMAIL_OWNER_ID": "owner-1",
        "PROBATION_GMAIL_STORE": str(private_store),
    }
    ok = configure_gmail_api_from_env(env)
    assert ok is True

    resp = client.get(
        "/api/gmail/connections",
        headers={"Authorization": "Bearer test-key-123"},
    )
    assert resp.status_code == 200
    assert "connections" in resp.json()

    resp = client.get(
        "/api/gmail/connections",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


def test_owner_can_sign_in_before_gmail_store_exists(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "data" / "db" / "probation.db"
    missing_store = tmp_path / "data" / "private" / "connectors" / "gmail_metadata.db"
    monkeypatch.setattr(settings, "db_path", db_path)
    assert configure_gmail_api_from_env({"PROBATION_GMAIL_OWNER_API_KEY": "test-key-123"})

    response = TestClient(app, client=("127.0.0.1", 50000)).get(
        "/api/queue", headers={"Authorization": "Bearer test-key-123"}
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "digests": [], "total_count": 0}
    assert not missing_store.exists()


def test_non_loopback_bind_host_is_rejected_not_substituted(private_store: Path) -> None:
    """A bind host outside loopback fails the configuration instead of quietly replacing it."""
    from probation.api import gmail_auth
    from probation.api.routes import gmail_connector

    configure_gmail_api(None)
    env = {
        "PROBATION_GMAIL_OWNER_API_KEY": "test-key-123",
        "PROBATION_GMAIL_OWNER_ID": "owner-1",
        "PROBATION_GMAIL_STORE": str(private_store),
        "PROBATION_GMAIL_BIND_HOST": "0.0.0.0",
    }
    with pytest.raises(gmail_auth.ConnectorApiMisconfigured, match="bind_host_not_loopback"):
        configure_gmail_api_from_env(env)
    assert gmail_connector._config is None
