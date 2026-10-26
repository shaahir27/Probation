"""Synthetic proof for the canonical read-only setup grant identity and token checks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from probation.connectors.acl import apply_owner_only
from probation.connectors.credentials import MODIFY_SCOPE, READONLY_SCOPE
from probation.connectors.credentials_state import ProvisionedGrant
from probation.connectors.gmail_read_grant import (
    APPROVED_READ_LABEL,
    read_grant,
    read_token,
    registered_read_grant,
    token_exists,
    token_path,
)
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store

requires_windows = pytest.mark.skipif(os.name != "nt", reason="Windows ACL target")


def _private_store(tmp_path: Path) -> Path:
    private = tmp_path / "private"
    private.mkdir()
    apply_owner_only(private, is_dir=True)
    store = private / "gmail_metadata.db"
    conn = open_store(store)
    migrate_store(conn)
    conn.close()
    return store


def _insert(
    store: Path,
    grant: ProvisionedGrant,
    *,
    state: str = "SHADOW",
    label_ids: list[str] | None = None,
    scopes: list[str] | None = None,
    owner_id: str = "owner",
) -> None:
    conn = open_store(store)
    conn.execute(
        "INSERT INTO gmail_connections "
        "(connection_id,account_id,owner_id,state,selection_revision,label_ids,"
        "credential_ref,granted_scopes,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            grant.connection_id,
            grant.account_id,
            owner_id,
            state,
            1,
            json.dumps(label_ids or [APPROVED_READ_LABEL]),
            grant.credential_ref,
            json.dumps(scopes or [READONLY_SCOPE]),
            "2026-10-26T10:00:00Z",
            "2026-10-26T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()


def test_read_grant_identity_is_stable_and_normalized() -> None:
    grant = read_grant("owner", "Synthetic@Example.test", APPROVED_READ_LABEL)
    digest = hashlib.sha256(b"owner\0synthetic@example.test\0Label_1").hexdigest()[:24]
    assert grant == ProvisionedGrant(
        "read", f"d6-read-{digest}", "synthetic@example.test", f"cred-d6-read-{digest}"
    )
    assert grant == read_grant(" owner ", " synthetic@example.TEST ", " Label_1 ")


@requires_windows
def test_registered_grant_requires_exact_shadow_label_scope_and_ref(tmp_path: Path) -> None:
    grant = read_grant("owner", "synthetic@example.test", APPROVED_READ_LABEL)
    store = _private_store(tmp_path)
    _insert(store, grant)
    conn = open_store(store)
    try:
        access = ConnectorAccess(conn, "api")
        assert registered_read_grant(access, "owner") == grant
        assert registered_read_grant(access, "other-owner") is None
    finally:
        conn.close()


@requires_windows
@pytest.mark.parametrize(
    "state,label_ids,scopes",
    [
        ("DISCONNECTED", [APPROVED_READ_LABEL], [READONLY_SCOPE]),
        ("SHADOW", ["PROBATION"], [READONLY_SCOPE]),
        ("SHADOW", [APPROVED_READ_LABEL], [MODIFY_SCOPE]),
        ("SHADOW", [APPROVED_READ_LABEL, APPROVED_READ_LABEL], [READONLY_SCOPE]),
    ],
)
def test_registered_grant_rejects_any_unapproved_row(
    tmp_path: Path, state: str, label_ids: list[str], scopes: list[str]
) -> None:
    grant = read_grant("owner", "synthetic@example.test", APPROVED_READ_LABEL)
    store = _private_store(tmp_path)
    _insert(store, grant, state=state, label_ids=label_ids, scopes=scopes)
    conn = open_store(store)
    try:
        assert registered_read_grant(ConnectorAccess(conn, "api"), "owner") is None
    finally:
        conn.close()


@requires_windows
def test_token_exists_and_read_require_the_owner_only_refresh_file(tmp_path: Path) -> None:
    grant = read_grant("owner", "synthetic@example.test", APPROVED_READ_LABEL)
    store = _private_store(tmp_path)
    _insert(store, grant)
    token_root = store.parent / "readonly_tokens"
    token_root.mkdir()
    apply_owner_only(token_root, is_dir=True)
    path = token_path(store, grant)
    path.write_text("synthetic-read-refresh", encoding="utf-8")
    apply_owner_only(path, is_dir=False)
    assert token_exists(store, grant) is True
    assert read_token(store, grant) is not None
    assert read_token(store, grant).reveal() == "synthetic-read-refresh"  # type: ignore[union-attr]
    path.unlink()
    assert token_exists(store, grant) is False
    assert read_token(store, grant) is None
