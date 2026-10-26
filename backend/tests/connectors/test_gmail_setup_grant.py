"""Supervisor-side loading of the private read-only Gmail setup grant."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from probation.connectors.acl import apply_owner_only
from probation.connectors.credentials import READONLY_SCOPE
from probation.connectors.credentials_state import (
    ProvisionedGrant,
    RefreshTokenStore,
    SecretMaterial,
)
from probation.connectors.gmail_read_grant import (
    APPROVED_READ_LABEL,
    read_grant,
    token_root,
    write_grant,
)
from probation.connectors.types import ConnectorError
from probation.db.gmail_store import migrate_store, open_store
from probation.workers.gmail_setup_grant import (
    ReadOAuthSettings,
    load_setup_read_grant,
    load_setup_write_grant,
)

requires_windows = pytest.mark.skipif(os.name != "nt", reason="Windows ACL target")


def _registered_store(tmp_path: Path) -> tuple[Path, ProvisionedGrant]:
    private = tmp_path / "private"
    private.mkdir(parents=True)
    apply_owner_only(private, is_dir=True)
    store = private / "gmail_metadata.db"
    grant = read_grant("owner", "synthetic@example.test", APPROVED_READ_LABEL)
    conn = open_store(store)
    migrate_store(conn)
    conn.execute(
        "INSERT INTO gmail_connections "
        "(connection_id,account_id,owner_id,state,selection_revision,label_ids,"
        "credential_ref,granted_scopes,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            grant.connection_id,
            grant.account_id,
            "owner",
            "SHADOW",
            1,
            json.dumps([APPROVED_READ_LABEL]),
            grant.credential_ref,
            json.dumps([READONLY_SCOPE]),
            "2026-10-26T10:00:00Z",
            "2026-10-26T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()
    apply_owner_only(store, is_dir=False)
    return store, grant


def _write_token(store: Path, grant: ProvisionedGrant) -> Path:
    root = token_root(store)
    root.mkdir()
    apply_owner_only(root, is_dir=True)
    RefreshTokenStore(root).write(
        grant.credential_ref, SecretMaterial("synthetic-refresh", "refresh")
    )
    return root


def _write_executor_token(
    store: Path, read: ProvisionedGrant
) -> tuple[ProvisionedGrant, Path]:
    grant = write_grant("owner", read.account_id, APPROVED_READ_LABEL)
    root = token_root(store, role="write")
    root.mkdir()
    apply_owner_only(root, is_dir=True)
    RefreshTokenStore(root).write(
        grant.credential_ref, SecretMaterial("synthetic-write-refresh", "refresh")
    )
    return grant, root


def _oauth(monkeypatch: pytest.MonkeyPatch, *, configured: bool = True) -> ReadOAuthSettings:
    names = (
        "PROBATION_GMAIL_READ_CLIENT_ID",
        "PROBATION_GMAIL_CLIENT_ID",
        "PROBATION_GMAIL_READ_CLIENT_SECRET",
        "PROBATION_GMAIL_CLIENT_SECRET",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    if configured:
        monkeypatch.setenv("PROBATION_GMAIL_CLIENT_ID", "synthetic-client-id")
        monkeypatch.setenv("PROBATION_GMAIL_CLIENT_SECRET", "synthetic-client-secret")
    return ReadOAuthSettings(_env_file=None)


@requires_windows
def test_loader_builds_one_readonly_bundle_and_hides_it_from_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, grant = _registered_store(tmp_path)
    _write_token(store, grant)
    loaded = load_setup_read_grant(store, "owner", oauth_settings=_oauth(monkeypatch))
    assert loaded is not None
    assert loaded.grant == grant
    assert loaded.grant.role == "read"
    bundle = json.loads(loaded.bundle_json)
    assert bundle == {
        "client_id": "synthetic-client-id",
        "client_secret": "synthetic-client-secret",
        "refresh_token": "synthetic-refresh",
    }
    assert "synthetic-client-secret" not in repr(loaded)
    assert "synthetic-refresh" not in repr(loaded)


@requires_windows
def test_loader_builds_executor_write_grant_from_separate_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, read = _registered_store(tmp_path)
    write, write_root = _write_executor_token(store, read)
    loaded = load_setup_write_grant(store, "owner", oauth_settings=_oauth(monkeypatch))
    assert loaded is not None
    assert loaded.grant == write
    assert loaded.grant.role == "write"
    assert loaded.grant.connection_id == read.connection_id
    assert (write_root / f"{write.credential_ref}.refresh").is_file()
    assert json.loads(loaded.bundle_json)["refresh_token"] == "synthetic-write-refresh"
    assert "synthetic-write-refresh" not in repr(loaded)
    assert load_setup_read_grant(store, "owner", oauth_settings=_oauth(monkeypatch)) is None


@requires_windows
def test_loader_is_absent_without_store_or_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oauth = _oauth(monkeypatch)
    assert load_setup_read_grant(tmp_path / "missing.db", "owner", oauth_settings=oauth) is None
    store, grant = _registered_store(tmp_path)
    assert load_setup_read_grant(store, "owner", oauth_settings=oauth) is None
    _write_token(store, grant)
    assert load_setup_read_grant(store, "other-owner", oauth_settings=oauth) is None


@requires_windows
def test_loader_refuses_stale_schema_and_missing_oauth_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "private" / "empty.db"
    store.parent.mkdir(parents=True)
    apply_owner_only(store.parent, is_dir=True)
    sqlite3.connect(store).close()
    apply_owner_only(store, is_dir=False)
    with pytest.raises(ConnectorError) as stale:
        load_setup_read_grant(store, "owner", oauth_settings=_oauth(monkeypatch))
    assert stale.value.safe_code == "connector_store_schema_stale"

    store, grant = _registered_store(tmp_path / "second")
    _write_token(store, grant)
    with pytest.raises(ConnectorError) as missing:
        load_setup_read_grant(store, "owner", oauth_settings=_oauth(monkeypatch, configured=False))
    assert missing.value.safe_code == "readonly_oauth_client_absent"
