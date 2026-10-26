"""Canonical identity and token checks for the local read-only Gmail setup grant.

The setup child writes one SHADOW connection row and one owner-only refresh file. The API,
the setup script and the runtime supervisor must agree on that identity without sharing the
Google credential itself. This module owns the derivation and the registration checks only;
it never reads a token unless the caller explicitly asks for it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from probation.connectors.acl import verify_owner_only
from probation.connectors.credentials import READONLY_SCOPE
from probation.connectors.credentials_state import (
    ProvisionedGrant,
    RefreshTokenStore,
    SecretMaterial,
)
from probation.connectors.types import ConnectorError
from probation.db.gmail_store import ConnectorAccess

APPROVED_READ_LABEL = "Label_1"
READONLY_TOKEN_DIR = "readonly_tokens"
WRITE_TOKEN_DIR = "write_tokens"
_CONNECTED_STATES = frozenset({"SHADOW", "ACTIVE", "PAUSED"})


def _identity(owner_id: str, account_id: str, label_id: str) -> tuple[str, str, str]:
    owner = owner_id.strip()
    account = account_id.strip().lower()
    label = label_id.strip()
    if not owner or not account or not label:
        raise ConnectorError("read_grant_identity_incomplete")
    digest = hashlib.sha256(f"{owner}\0{account}\0{label}".encode()).hexdigest()[:24]
    return owner, account, digest


def read_grant(owner_id: str, account_id: str, label_id: str) -> ProvisionedGrant:
    """Derive the stable read grant for one owner/account/label identity."""
    _, account, digest = _identity(owner_id, account_id, label_id)
    return ProvisionedGrant("read", f"d6-read-{digest}", account, f"cred-d6-read-{digest}")


def write_grant(owner_id: str, account_id: str, label_id: str) -> ProvisionedGrant:
    """Derive the Executor-only write grant for the same registered connection."""
    _, account, digest = _identity(owner_id, account_id, label_id)
    return ProvisionedGrant("write", f"d6-read-{digest}", account, f"cred-d6-write-{digest}")


def _registered_connection(
    access: ConnectorAccess, owner_id: str
) -> ProvisionedGrant | None:
    rows = access.query(
        "SELECT connection_id,account_id,credential_ref,label_ids,granted_scopes,state "
        "FROM gmail_connections WHERE owner_id=?",
        (owner_id,),
    )
    for row in rows:
        if row["state"] not in _CONNECTED_STATES:
            continue
        try:
            label_ids = json.loads(row["label_ids"])
            scopes = json.loads(row["granted_scopes"])
        except (TypeError, ValueError):
            continue
        if label_ids != [APPROVED_READ_LABEL] or scopes != [READONLY_SCOPE]:
            continue
        try:
            expected = read_grant(owner_id, str(row["account_id"]), APPROVED_READ_LABEL)
        except ConnectorError:
            continue
        if (
            row["connection_id"] != expected.connection_id
            or row["credential_ref"] != expected.credential_ref
        ):
            continue
        return expected
    return None


def registered_read_grant(access: ConnectorAccess, owner_id: str) -> ProvisionedGrant | None:
    """The one approved registered read connection for this owner, or None."""
    return _registered_connection(access, owner_id)


def registered_write_grant(access: ConnectorAccess, owner_id: str) -> ProvisionedGrant | None:
    """The write grant bound to the same registered connection, or None."""
    registered = _registered_connection(access, owner_id)
    if registered is None:
        return None
    return write_grant(owner_id, registered.account_id, APPROVED_READ_LABEL)


def token_root(store_path: Path, *, role: str = "read") -> Path:
    return store_path.parent / (WRITE_TOKEN_DIR if role == "write" else READONLY_TOKEN_DIR)


def token_path(store_path: Path, grant: ProvisionedGrant) -> Path:
    return token_root(store_path, role=grant.role) / f"{grant.credential_ref}.refresh"


def token_exists(store_path: Path, grant: ProvisionedGrant) -> bool:
    """Registration is connected only while the ACL-protected refresh file exists."""
    root, path = token_root(store_path, role=grant.role), token_path(store_path, grant)
    if not path.is_file():
        return False
    try:
        verify_owner_only(root)
        verify_owner_only(path)
    except (ConnectorError, OSError):
        return False
    return True


def read_token(store_path: Path, grant: ProvisionedGrant) -> SecretMaterial | None:
    """Read the setup refresh material in the trusted supervisor/setup process only."""
    root, path = token_root(store_path, role=grant.role), token_path(store_path, grant)
    if not path.is_file():
        return None
    verify_owner_only(root)
    verify_owner_only(path)
    return RefreshTokenStore(root).read(grant.credential_ref)
