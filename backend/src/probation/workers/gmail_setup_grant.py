"""Load the setup-created read grant for the local Gmail runtime supervisor.

The API never imports this module. Only the `serve --gmail-runtime` supervisor reads the
owner-only refresh file and the OAuth client identity, then injects exactly one non-write
grant into the observation child's environment.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from probation.connectors.acl import verify_owner_only
from probation.connectors.credentials_state import (
    ProvisionedGrant,
    RefreshTokenStore,
    SecretMaterial,
)
from probation.connectors.gmail_read_grant import (
    read_token,
    registered_read_grant,
    registered_write_grant,
    token_root,
)
from probation.connectors.types import ConnectorError
from probation.core.clock import configure_clock_collation
from probation.db.connection import ManagedConnection
from probation.db.gmail_store import ConnectorAccess, store_is_current

_ENV_FILE = os.environ.get("PROBATION_ENV_FILE", ".env")


class ReadOAuthSettings(BaseSettings):
    """Only the OAuth client identity needed to refresh the setup grant."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
    client_id: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "PROBATION_GMAIL_READ_CLIENT_ID", "PROBATION_GMAIL_CLIENT_ID"
        ),
    )
    client_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "PROBATION_GMAIL_READ_CLIENT_SECRET", "PROBATION_GMAIL_CLIENT_SECRET"
        ),
    )


@dataclass(frozen=True)
class LoadedGrant:
    grant: ProvisionedGrant
    token_store: RefreshTokenStore
    bundle_json: str = field(repr=False)


def load_setup_grant(
    store_path: Path | str,
    owner_id: str,
    *,
    role: str = "read",
    oauth_settings: ReadOAuthSettings | None = None,
) -> LoadedGrant | None:
    """Return the one verified setup grant, or None when none has been registered.

    An existing private store with an unverifiable ACL, a stale schema or a malformed row
    raises a typed failure instead of being silently treated as absent.
    """
    path = Path(store_path)
    if not path.is_file():
        return None
    verify_owner_only(path.parent)
    verify_owner_only(path)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, factory=ManagedConnection
        )
        conn.row_factory = sqlite3.Row
        configure_clock_collation(conn)
        if not store_is_current(conn):
            raise ConnectorError("connector_store_schema_stale")
        finder = registered_write_grant if role == "write" else registered_read_grant
        grant = finder(ConnectorAccess(conn, "api"), owner_id)
    finally:
        if conn is not None:
            conn.close()
    if grant is None:
        return None
    token: SecretMaterial | None = read_token(path, grant)
    if token is None:
        return None
    settings = oauth_settings or ReadOAuthSettings()
    client_id = settings.client_id.get_secret_value()
    client_secret = settings.client_secret.get_secret_value()
    if not client_id or not client_secret:
        raise ConnectorError("readonly_oauth_client_absent")
    bundle = json.dumps(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token.reveal(),
        },
        separators=(",", ":"),
    )
    return LoadedGrant(
        grant=grant,
        token_store=RefreshTokenStore(token_root(path, role=role)),
        bundle_json=bundle,
    )


def load_setup_read_grant(
    store_path: Path | str,
    owner_id: str,
    *,
    oauth_settings: ReadOAuthSettings | None = None,
) -> LoadedGrant | None:
    return load_setup_grant(
        store_path, owner_id, role="read", oauth_settings=oauth_settings
    )


def load_setup_write_grant(
    store_path: Path | str,
    owner_id: str,
    *,
    oauth_settings: ReadOAuthSettings | None = None,
) -> LoadedGrant | None:
    return load_setup_grant(
        store_path, owner_id, role="write", oauth_settings=oauth_settings
    )
