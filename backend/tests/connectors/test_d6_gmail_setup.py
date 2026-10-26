"""Offline proof for the operator-only read grant setup; no real OAuth or ACL changes."""

import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from probation.connectors import credentials_state
from probation.connectors.acl import PrivatePathRejected
from probation.connectors.credentials import (
    MODIFY_SCOPE,
    READONLY_SCOPE,
    SEND_SCOPE,
    TokenBundle,
)
from probation.connectors.credentials_state import SecretMaterial
from probation.connectors.gmail_read_grant import token_root, write_grant
from probation.connectors.types import ConnectorError, HttpResult, ScopeMismatch
from probation.db.gmail_store import migrate_store, open_store
from probation.packs.mail.connectors.gmail_auth import AuthorizationFlowError

_SCRIPT = Path(__file__).parents[3] / "scripts/d6_gmail_setup.py"
_SPEC = importlib.util.spec_from_file_location("d6_gmail_setup", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
setup = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = setup
_SPEC.loader.exec_module(setup)

ACCOUNT = "synthetic-owner@example.test"
CLIENT_SECRET = "SYNTHETIC-client-secret-canary"
REFRESH = "SYNTHETIC-fresh-readonly-refresh-canary"
WRITE_REFRESH = "SYNTHETIC-fresh-write-refresh-canary"
ACCESS = "SYNTHETIC-access-canary"
CODE = "SYNTHETIC-callback-code-canary"


def config(**overrides):
    values = {
        "PROBATION_GMAIL_CLIENT_ID": "synthetic.apps.googleusercontent.com",
        "PROBATION_GMAIL_CLIENT_SECRET": CLIENT_SECRET,
        "PROBATION_GMAIL_ACCOUNT": ACCOUNT,
        "PROBATION_GMAIL_OWNER_ID": "synthetic-owner",
        "PROBATION_GMAIL_LABEL": "Label_1",
    }
    values.update(overrides)
    return setup.SetupSettings(_env_file=None, **values)


def bundle(
    *,
    scopes=(READONLY_SCOPE,),
    account=ACCOUNT,
    refresh=True,
    refresh_value=REFRESH,
):
    return TokenBundle(
        account_id=account,
        granted_scopes=scopes,
        expires_in_seconds=3600,
        access=SecretMaterial(ACCESS, "access"),
        refresh=SecretMaterial(refresh_value, "refresh") if refresh else None,
    )


@pytest.fixture
def fake_acl(monkeypatch):
    def initialize(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = open_store(path)
        migrate_store(conn)
        conn.close()

    monkeypatch.setattr(setup, "verify_and_migrate_store", initialize)
    monkeypatch.setattr(setup, "verify_owner_only", lambda path: None)
    monkeypatch.setattr(setup, "apply_owner_only", lambda path, *, is_dir: None)
    monkeypatch.setattr(credentials_state, "apply_owner_only", lambda path, *, is_dir: None)
    monkeypatch.setattr(credentials_state, "verify_owner_only", lambda path: None)


def test_check_is_local_and_creates_nothing(tmp_path):
    settings = config()
    status = setup.local_status(settings, root=tmp_path)
    assert status["oauth_client_configured"] is True
    assert status["private_store_exists"] is False
    assert status["readonly_refresh_exists"] is False
    assert list(tmp_path.iterdir()) == []


def test_help_does_not_load_credentials(monkeypatch, capsys):
    monkeypatch.setattr(setup, "SetupSettings", lambda **kwargs: pytest.fail("loaded credentials"))
    with pytest.raises(SystemExit) as exit_info:
        setup.main(["--help"])
    assert exit_info.value.code == 0
    assert "--authorize-read" in capsys.readouterr().out


@pytest.mark.parametrize(
    "value,expected",
    [
        (bundle(scopes=(READONLY_SCOPE, MODIFY_SCOPE)), ScopeMismatch),
        (bundle(account="another@example.test"), ConnectorError),
        (bundle(refresh=False), ConnectorError),
    ],
)
def test_invalid_grant_is_rejected_before_any_persistence(tmp_path, monkeypatch, value, expected):
    monkeypatch.setattr(setup, "verify_and_migrate_store", lambda path: pytest.fail("opened store"))
    with pytest.raises(expected):
        setup.persist_read_authorization(config(), value, root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_private_path_escape_is_refused_without_writes(tmp_path):
    with pytest.raises(ConnectorError, match="private_store_path_required"):
        setup.local_status(config(PROBATION_GMAIL_STORE="outside.db"), root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_fresh_readonly_grant_has_shadow_registration_and_private_refresh(tmp_path, fake_acl):
    settings = config()
    grant = setup.persist_read_authorization(settings, bundle(), root=tmp_path)
    store, tokens = setup.private_paths(settings, tmp_path)
    assert (tokens / f"{grant.credential_ref}.refresh").read_text() == REFRESH
    conn = open_store(store)
    row = conn.execute("SELECT * FROM gmail_connections").fetchone()
    assert row["connection_id"] == grant.connection_id
    assert row["state"] == "SHADOW"
    assert row["owner_id"] == "synthetic-owner"
    assert row["account_id"] == ACCOUNT
    assert json.loads(row["label_ids"]) == ["Label_1"]
    assert json.loads(row["granted_scopes"]) == [READONLY_SCOPE]
    assert row["created_at"] == row["updated_at"]
    assert conn.execute("SELECT count(*) FROM gmail_sync_cursors").fetchone()[0] == 0
    conn.close()
    # Repeating the same setup never changes the registered observation start time.
    setup.persist_read_authorization(settings, bundle(), root=tmp_path)
    conn = open_store(store)
    assert (
        conn.execute("SELECT created_at FROM gmail_connections").fetchone()[0] == row["created_at"]
    )
    conn.close()


def test_fresh_write_grant_has_separate_owner_only_token(tmp_path, fake_acl):
    settings = config()
    read = setup.persist_read_authorization(settings, bundle(), root=tmp_path)
    write = setup.persist_write_authorization(
        settings,
        bundle(scopes=(MODIFY_SCOPE, SEND_SCOPE), refresh_value=WRITE_REFRESH),
        root=tmp_path,
    )
    store, _ = setup.private_paths(settings, tmp_path)
    read_path = token_root(store) / f"{read.credential_ref}.refresh"
    write_path = token_root(store, role="write") / f"{write.credential_ref}.refresh"
    assert read_path.read_text(encoding="utf-8") == REFRESH
    assert write_path.read_text(encoding="utf-8") == WRITE_REFRESH
    assert read_path != write_path
    assert write.role == "write"
    assert write.connection_id == read.connection_id
    assert write.credential_ref == write_grant("synthetic-owner", ACCOUNT, "Label_1").credential_ref
    conn = open_store(store)
    try:
        row = conn.execute("SELECT credential_ref,state FROM gmail_connections").fetchone()
        assert row["credential_ref"] == read.credential_ref
        assert row["state"] == "ACTIVE"
        assert conn.execute("SELECT count(*) FROM gmail_connections").fetchone()[0] == 1
    finally:
        conn.close()
    status = setup.local_status(settings, root=tmp_path)
    assert status["readonly_refresh_exists"] is True
    assert status["write_refresh_exists"] is True
    assert status["readonly_refresh_acl_verified"] is True
    assert status["write_refresh_acl_verified"] is True


@pytest.mark.parametrize(
    "value",
    [
        bundle(scopes=(READONLY_SCOPE,)),
        bundle(scopes=(SEND_SCOPE,)),
        bundle(scopes=(MODIFY_SCOPE,)),
        bundle(scopes=(MODIFY_SCOPE, SEND_SCOPE), refresh=False),
        bundle(scopes=(MODIFY_SCOPE, SEND_SCOPE), account="another@example.test"),
    ],
)
def test_invalid_write_grant_is_rejected_before_persistence(tmp_path, monkeypatch, value):
    monkeypatch.setattr(setup, "verify_and_migrate_store", lambda path: pytest.fail("opened store"))
    with pytest.raises(ConnectorError):
        setup.persist_write_authorization(config(), value, root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_write_grant_requires_an_existing_read_connection(tmp_path, fake_acl):
    with pytest.raises(ConnectorError, match="read_connection_required"):
        setup.persist_write_authorization(
            config(),
            bundle(scopes=(MODIFY_SCOPE, SEND_SCOPE), refresh_value=WRITE_REFRESH),
            root=tmp_path,
        )


def test_acl_failure_never_installs_registration(tmp_path, fake_acl, monkeypatch):
    def reject(*args, **kwargs):
        raise PrivatePathRejected("synthetic_acl_denial")

    monkeypatch.setattr(credentials_state, "apply_owner_only", reject)
    with pytest.raises(PrivatePathRejected):
        setup.persist_read_authorization(config(), bundle(), root=tmp_path)
    store, _ = setup.private_paths(config(), tmp_path)
    conn = open_store(store)
    assert conn.execute("SELECT count(*) FROM gmail_connections").fetchone()[0] == 0
    conn.close()


def test_initial_file_acl_denial_happens_before_any_refresh_bytes(tmp_path, fake_acl, monkeypatch):
    def reject_file(path, *, is_dir):
        if not is_dir and path.suffix == ".refresh":
            raise PrivatePathRejected("synthetic_file_acl_denial")

    monkeypatch.setattr(setup, "apply_owner_only", reject_file)
    settings = config()
    with pytest.raises(PrivatePathRejected):
        setup.persist_read_authorization(settings, bundle(), root=tmp_path)
    _, token_root = setup.private_paths(settings, tmp_path)
    assert all(path.read_bytes() == b"" for path in token_root.iterdir())


def test_revoked_registration_is_not_resurrected(tmp_path, fake_acl, monkeypatch):
    settings = config()
    grant = setup.persist_read_authorization(settings, bundle(), root=tmp_path)
    store, _ = setup.private_paths(settings, tmp_path)
    conn = open_store(store)
    conn.execute("UPDATE gmail_connections SET state='DISCONNECTED'")
    conn.close()
    monkeypatch.setattr(
        setup.RefreshTokenStore, "write", lambda *args: pytest.fail("changed token")
    )
    with pytest.raises(ConnectorError, match="existing_connection_requires_owner_control"):
        setup.persist_read_authorization(settings, bundle(), root=tmp_path)
    assert grant.role == "read"


def test_oauth_requests_only_read_access_and_never_prints_credentials(
    tmp_path, fake_acl, monkeypatch, capsys
):
    seen = {}

    class Listener:
        redirect_uri = "http://127.0.0.1:4444/"

        def __init__(self, *, port: int = 0):
            self.port = port

        def expect(self, value):
            seen["state"] = value

        def wait(self, timeout_seconds):
            return SecretMaterial(CODE, "code")

    class Exchange:
        def __init__(self, **kwargs):
            seen["exchange"] = kwargs

        def complete(self, **kwargs):
            seen["completion"] = kwargs
            return bundle()

    class Api:
        def get(self, url, *, params, access_token):
            assert url.endswith("/labels/Label_1")
            assert access_token == ACCESS
            return HttpResult(200, json.dumps({"id": "Label_1", "name": "PROBATION"}).encode())

        def close(self):
            pass

    monkeypatch.setattr(setup, "LoopbackCallback", Listener)
    monkeypatch.setattr(setup, "OAuthTokenExchange", Exchange)
    monkeypatch.setattr(setup, "GmailHttpTransport", Api)
    monkeypatch.setattr(setup.webbrowser, "open", lambda url, new: seen.setdefault("url", url))
    monkeypatch.setattr(setup, "persist_read_authorization", lambda c, b, **kw: setup.identity(c))
    grant = setup.authorize_read(config(), root=tmp_path)
    query = parse_qs(urlsplit(seen["url"]).query)
    assert query["scope"] == [READONLY_SCOPE]
    assert query["state"] == [seen["state"]]
    assert query["code_challenge_method"] == ["S256"]
    assert seen["completion"]["role"] == "read"
    assert grant.role == "read"
    output = capsys.readouterr().out
    for secret in (CLIENT_SECRET, REFRESH, ACCESS, CODE, seen["url"]):
        assert secret not in output


def test_parallel_setup_is_refused_before_another_consent_prompt(tmp_path, fake_acl, monkeypatch):
    settings = config()
    store, _ = setup.private_paths(settings, tmp_path)
    setup.verify_and_migrate_store(store)
    lock = setup.ReplayLock(store.parent / "readonly_setup.lock")
    assert lock.acquire()
    monkeypatch.setattr(setup, "_consent", lambda *args, **kwargs: pytest.fail("second prompt"))
    try:
        with pytest.raises(
            ConnectorError, match=r"readonly_setup_(already_running|lock_unavailable)"
        ):
            setup.authorize_read(settings, root=tmp_path)
    finally:
        lock.release()


def test_callback_timeout_returns_safe_failure_without_persisting_a_grant(
    tmp_path, fake_acl, monkeypatch, capsys
):
    settings = config()

    class Listener:
        redirect_uri = "http://127.0.0.1:4444/"

        def __init__(self, *, port: int = 0):
            self.port = port

        def expect(self, value):
            pass

        def wait(self, timeout_seconds):
            raise AuthorizationFlowError("callback_timeout")

    original_authorize = setup.authorize_read
    monkeypatch.setattr(setup, "SetupSettings", lambda **kwargs: settings)
    monkeypatch.setattr(setup, "authorize_read", lambda c: original_authorize(c, root=tmp_path))
    monkeypatch.setattr(setup, "LoopbackCallback", Listener)
    monkeypatch.setattr(setup.webbrowser, "open", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        setup, "persist_read_authorization", lambda *args, **kwargs: pytest.fail("persisted grant")
    )
    assert setup.main(["--authorize-read"]) == 1
    output = capsys.readouterr().out
    assert "callback_timeout" in output
    for secret in (CLIENT_SECRET, REFRESH, ACCESS, CODE):
        assert secret not in output
