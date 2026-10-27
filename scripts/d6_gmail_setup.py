"""Authorize a separate read-only Gmail grant for the approved synthetic demo.

Run from the project root: python scripts/d6_gmail_setup.py --check
After owner approval: python scripts/d6_gmail_setup.py --authorize-read
No secret arguments, dotenv edits, paid calls or Gmail mutations are supported.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import webbrowser
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

from probation.connectors.acl import apply_owner_only, verify_owner_only
from probation.connectors.credentials import (
    MODIFY_SCOPE,
    READONLY_SCOPE,
    SEND_SCOPE,
    RoleCredentialProvider,
    TokenBundle,
)
from probation.connectors.credentials_state import (
    EnvCredentialSource,
    ProvisionedGrant,
    RefreshTokenStore,
)
from probation.connectors.gmail_read_grant import (
    read_grant,
    token_path as grant_token_path,
    token_root,
    write_grant,
)
from probation.connectors.types import ConnectorError
from probation.core.clock import Clock
from probation.db.gmail_store import ConnectorAccess, open_store
from probation.packs.mail.connectors.gmail_auth import (
    LoopbackCallback,
    OAuthTokenExchange,
    StateVault,
    build_authorization_url,
    new_pkce,
    plan_scopes,
)
from probation.packs.mail.connectors.gmail_transport import (
    GMAIL_BASE_URL,
    GmailHttpTransport,
    GmailProfileGateway,
    GoogleTokenTransport,
)
from probation.workers.gmail_runtime_provisioning import verify_and_migrate_store
from probation.workers.replay_lock import ReplayLock
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SetupSettings(BaseSettings):
    """Only the OAuth client and approved identity; never consume the old refresh token."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)
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
    account: str = Field(
        default="", validation_alias="PROBATION_GMAIL_ACCOUNT", repr=False
    )
    owner_id: str = Field(
        default="local-owner", validation_alias="PROBATION_GMAIL_OWNER_ID"
    )
    label_id: str = Field(default="", validation_alias="PROBATION_GMAIL_LABEL")
    store: Path = Field(
        default=Path("data/private/connectors/gmail_metadata.db"),
        validation_alias="PROBATION_GMAIL_STORE",
    )
    redirect_port: int = Field(
        default=8765,
        ge=1024,
        le=65535,
        validation_alias="PROBATION_GMAIL_REDIRECT_PORT",
    )


def identity(config: SetupSettings) -> ProvisionedGrant:
    return read_grant(config.owner_id, config.account, config.label_id)


def write_identity(config: SetupSettings) -> ProvisionedGrant:
    return write_grant(config.owner_id, config.account, config.label_id)


def private_paths(config: SetupSettings, root: Path) -> tuple[Path, Path]:
    store = (root / config.store).resolve()
    if not store.is_relative_to((root / "data/private").resolve()):
        raise ConnectorError("private_store_path_required")
    return store, store.parent / "readonly_tokens"


def local_status(config: SetupSettings, *, root: Path = ROOT) -> dict[str, bool]:
    """Inspect local presence/ACLs only; do not create stores or refresh credentials."""
    store, read_root = private_paths(config, root)
    read_path = (
        read_root / f"{identity(config).credential_ref}.refresh"
        if config.account.strip()
        else None
    )
    write_root = token_root(store, role="write")
    write_path = (
        write_root / f"{write_identity(config).credential_ref}.refresh"
        if config.account.strip()
        else None
    )

    def acl_verified(root: Path, path: Path | None) -> bool:
        if path is None or not path.is_file():
            return False
        try:
            verify_owner_only(root)
            verify_owner_only(path)
            return True
        except (ConnectorError, OSError):
            return False

    return {
        "oauth_client_configured": bool(config.client_id.get_secret_value())
        and bool(config.client_secret.get_secret_value()),
        "test_account_configured": bool(config.account.strip()),
        "owner_configured": bool(config.owner_id.strip()),
        "approved_label_configured": config.label_id == "Label_1",
        "private_store_exists": store.is_file(),
        "readonly_refresh_exists": bool(read_path is not None and read_path.is_file()),
        "readonly_refresh_acl_verified": acl_verified(read_root, read_path),
        "write_refresh_exists": bool(write_path is not None and write_path.is_file()),
        "write_refresh_acl_verified": acl_verified(write_root, write_path),
    }


def validate_bundle(
    config: SetupSettings, grant: ProvisionedGrant, bundle: TokenBundle
) -> None:
    """Use the existing role gate; a broader token cannot be relabelled as read-only."""
    if bundle.refresh is None:
        raise ConnectorError("fresh_readonly_refresh_required")
    provider = RoleCredentialProvider(
        grant=grant, source=EnvCredentialSource({}, grant), clock=Clock.live()
    )
    provider.install_bundle(bundle)
    if provider.granted_scopes() != (READONLY_SCOPE,):
        raise ConnectorError("exact_readonly_scope_required")
    if bundle.account_id != config.account.strip().lower():
        raise ConnectorError("account_binding_mismatch")


def validate_write_bundle(
    config: SetupSettings, grant: ProvisionedGrant, bundle: TokenBundle
) -> None:
    """Require the Executor's send/modify capability; a read-only bundle cannot be relabelled."""
    if bundle.refresh is None:
        raise ConnectorError("fresh_write_refresh_required")
    provider = RoleCredentialProvider(
        grant=grant, source=EnvCredentialSource({}, grant), clock=Clock.live()
    )
    provider.install_bundle(bundle)
    granted = set(provider.granted_scopes())
    if not {MODIFY_SCOPE, SEND_SCOPE} <= granted:
        raise ConnectorError("exact_write_scope_required")
    if not granted <= {MODIFY_SCOPE, SEND_SCOPE, READONLY_SCOPE}:
        raise ConnectorError("unapproved_write_scope")
    if bundle.account_id != config.account.strip().lower():
        raise ConnectorError("account_binding_mismatch")


def persist_read_authorization(
    config: SetupSettings,
    bundle: TokenBundle,
    *,
    root: Path = ROOT,
    clock: Clock | None = None,
) -> ProvisionedGrant:
    if config.label_id != "Label_1" or not config.owner_id.strip():
        raise ConnectorError("approved_owner_and_label_required")
    grant = identity(config)
    validate_bundle(config, grant, bundle)
    store, token_dir = private_paths(config, root)
    verify_and_migrate_store(store)
    apply_owner_only(store, is_dir=False)
    verify_owner_only(store)
    admin = ConnectorAccess(open_store(store), "administration")
    expected = (
        grant.account_id,
        config.owner_id,
        json.dumps([config.label_id]),
        grant.credential_ref,
        json.dumps([READONLY_SCOPE]),
    )
    try:
        existing = admin.one(
            "SELECT account_id,owner_id,label_ids,credential_ref,granted_scopes,state "
            "FROM gmail_connections WHERE connection_id=?",
            (grant.connection_id,),
        )
        if existing is not None and (
            tuple(existing)[:5] != expected
            or existing["state"]
            not in {"SHADOW", "ACTIVE", "PAUSED", "DISCONNECTED", "AUTH_REQUIRED"}
        ):
            raise ConnectorError("existing_connection_requires_owner_control")
        reconnecting = existing is not None and existing["state"] in {
            "DISCONNECTED",
            "AUTH_REQUIRED",
        }
        if reconnecting:
            # A read-only reconnect must not revive the previous action credential. Only a
            # fresh action consent may create it again.
            write_token = grant_token_path(
                store, write_grant(config.owner_id, grant.account_id, config.label_id)
            )
            write_root = token_root(store, role="write")
            if write_root.exists():
                verify_owner_only(write_root)
                if write_token.exists():
                    write_token.unlink()
        token_store = RefreshTokenStore(token_dir)
        if not token_dir.exists():
            token_dir.mkdir(parents=True)
            apply_owner_only(token_dir, is_dir=True)
        verify_owner_only(token_dir)
        token_path = token_dir / f"{grant.credential_ref}.refresh"
        if not token_path.exists():
            # Establish the file ACL while it is empty, before any refresh bytes are written.
            token_path.touch(exist_ok=False)
            apply_owner_only(token_path, is_dir=False)
        verify_owner_only(token_path)
        assert bundle.refresh is not None  # validated before any persistent operation
        token_store.write(grant.credential_ref, bundle.refresh)
        if token_store.read(grant.credential_ref).reveal() != bundle.refresh.reveal():
            raise ConnectorError("readonly_refresh_persistence_failed")
        now = (clock or Clock.live()).now_iso()
        with admin.transaction() as tx:
            tx.write(
                "gmail_connections",
                "INSERT INTO gmail_connections "
                "(connection_id,account_id,owner_id,state,selection_revision,label_ids,"
                "credential_ref,granted_scopes,created_at,updated_at,authorized_at) "
                "VALUES(?,?,?,'SHADOW',1,?,?,?,?,?,?) ON CONFLICT(connection_id) DO NOTHING",
                (grant.connection_id, *expected[:2], *expected[2:], now, now, now),
            )
            if reconnecting:
                tx.write(
                    "gmail_connections",
                    "UPDATE gmail_connections SET state='SHADOW',updated_at=?,authorized_at=? "
                    "WHERE connection_id=? AND owner_id=? AND state IN ('DISCONNECTED','AUTH_REQUIRED')",
                    (now, now, grant.connection_id, config.owner_id),
                )
        return grant
    finally:
        admin.conn.close()


def persist_write_authorization(
    config: SetupSettings,
    bundle: TokenBundle,
    *,
    root: Path = ROOT,
    clock: Clock | None = None,
) -> ProvisionedGrant:
    """Persist the Executor-only write refresh beside the existing read registration."""
    if config.label_id != "Label_1" or not config.owner_id.strip():
        raise ConnectorError("approved_owner_and_label_required")
    grant = write_identity(config)
    validate_write_bundle(config, grant, bundle)
    store, _ = private_paths(config, root)
    verify_and_migrate_store(store)
    apply_owner_only(store, is_dir=False)
    verify_owner_only(store)
    admin = ConnectorAccess(open_store(store), "administration")
    try:
        row = admin.one(
            "SELECT connection_id,account_id,owner_id,state FROM gmail_connections "
            "WHERE connection_id=?",
            (grant.connection_id,),
        )
        if (
            row is None
            or str(row["owner_id"]) != config.owner_id
            or str(row["account_id"]) != grant.account_id
            or str(row["state"]) not in {"SHADOW", "ACTIVE", "PAUSED"}
        ):
            raise ConnectorError("read_connection_required")
        write_root = token_root(store, role="write")
        if not write_root.exists():
            write_root.mkdir(parents=True)
            apply_owner_only(write_root, is_dir=True)
        verify_owner_only(write_root)
        token_path = write_root / f"{grant.credential_ref}.refresh"
        if not token_path.exists():
            token_path.touch(exist_ok=False)
            apply_owner_only(token_path, is_dir=False)
        verify_owner_only(token_path)
        assert bundle.refresh is not None
        token_store = RefreshTokenStore(write_root)
        token_store.write(grant.credential_ref, bundle.refresh)
        if token_store.read(grant.credential_ref).reveal() != bundle.refresh.reveal():
            raise ConnectorError("write_refresh_persistence_failed")
        now = (clock or Clock.live()).now_iso()
        with admin.transaction() as tx:
            # The explicit write grant activates the connection; read-only setup alone stays SHADOW.
            tx.write(
                "gmail_connections",
                "UPDATE gmail_connections SET state='ACTIVE',updated_at=?,authorized_at=? "
                "WHERE connection_id=? AND owner_id=? AND state='SHADOW'",
                (now, now, grant.connection_id, config.owner_id),
            )
        return grant
    finally:
        admin.conn.close()


def authorize_read(config: SetupSettings, *, root: Path = ROOT) -> ProvisionedGrant:
    status = local_status(config, root=root)
    if not all(
        status[key]
        for key in (
            "oauth_client_configured",
            "test_account_configured",
            "owner_configured",
            "approved_label_configured",
        )
    ):
        raise ConnectorError("client_account_or_approved_label_missing")
    store, _ = private_paths(config, root)
    verify_and_migrate_store(store)
    apply_owner_only(store, is_dir=False)
    verify_owner_only(store)
    lock = ReplayLock(store.parent / "readonly_setup.lock")
    try:
        try:
            acquired = lock.acquire()
        except OSError as exc:
            raise ConnectorError("readonly_setup_lock_unavailable") from exc
        if not acquired:
            raise ConnectorError("readonly_setup_already_running")
        return _consent(config, root=root, role="read")
    finally:
        lock.release()


def authorize_write(config: SetupSettings, *, root: Path = ROOT) -> ProvisionedGrant:
    """Obtain a fresh send+modify grant for the Executor only."""
    status = local_status(config, root=root)
    if not all(
        status[key]
        for key in (
            "oauth_client_configured",
            "test_account_configured",
            "owner_configured",
            "approved_label_configured",
            "readonly_refresh_exists",
            "readonly_refresh_acl_verified",
        )
    ):
        raise ConnectorError("read_connection_required")
    store, _ = private_paths(config, root)
    verify_and_migrate_store(store)
    apply_owner_only(store, is_dir=False)
    verify_owner_only(store)
    lock = ReplayLock(store.parent / "write_setup.lock")
    try:
        try:
            acquired = lock.acquire()
        except OSError as exc:
            raise ConnectorError("write_setup_lock_unavailable") from exc
        if not acquired:
            raise ConnectorError("write_setup_already_running")
        return _consent(config, root=root, role="write")
    finally:
        lock.release()


def _consent(
    config: SetupSettings, *, root: Path, role: Literal["read", "write"]
) -> ProvisionedGrant:
    grant = identity(config) if role == "read" else write_identity(config)
    clock = Clock.live()
    listener = LoopbackCallback(port=config.redirect_port)
    waited = False
    api, token_http = GmailHttpTransport(), GoogleTokenTransport()
    try:
        pkce = new_pkce()
        vault = StateVault(clock=clock)
        capabilities = (
            frozenset({"read"})
            if role == "read"
            else frozenset({"send", "forward", "archive", "trash", "conditional_write"})
        )
        required_scopes = plan_scopes(role, capabilities)
        # The action consent shows all three Gmail choices. Read is requested for context;
        # the write validation still requires modify+send and the read grant keeps its own
        # read-only consent, so the observation role never receives a write token.
        requested_scopes = (
            tuple(dict.fromkeys((*required_scopes, READONLY_SCOPE)))
            if role == "write"
            else required_scopes
        )
        state = vault.issue(
            owner_id=config.owner_id,
            role=role,
            account_id=grant.account_id,
            connection_id=grant.connection_id,
            redirect_uri=listener.redirect_uri,
            required_scopes=required_scopes,
            pkce=pkce,
        )
        listener.expect(state.token)
        url = build_authorization_url(
            client_id=config.client_id.get_secret_value(),
            redirect_uri=listener.redirect_uri,
            state_token=state.token,
            pkce=pkce,
            scopes=requested_scopes,
        )
        if not webbrowser.open(url, new=1):
            raise ConnectorError("browser_open_failed")
        print(
            "Complete Google sign-in in the opened browser using the configured test account."
        )
        if role == "read":
            print(
                "Approve read-only Gmail access only. This setup requests no email changes."
            )
        else:
            print(
                "Google shows read, change and send access. Choose the access you want. "
                "Action access needs change and send; each live effect still needs an explicit "
                "owner approval, and the observer keeps its separate read-only consent."
            )
        waited = True
        code = listener.wait(timeout_seconds=180)
        exchange = OAuthTokenExchange(
            client_id=config.client_id.get_secret_value(),
            client_secret=config.client_secret.get_secret_value(),
            vault=vault,
            transport=token_http,
            userinfo=GmailProfileGateway(api),
            clock=clock,
        )
        bundle = exchange.complete(
            state_token=state.token,
            code=code,
            owner_id=config.owner_id,
            role=role,
            account_id=grant.account_id,
            redirect_uri=listener.redirect_uri,
        )
        if role == "read":
            validate_bundle(config, grant, bundle)
        else:
            validate_write_bundle(config, grant, bundle)
        result = api.get(
            f"{GMAIL_BASE_URL}/labels/{config.label_id}",
            params={"fields": "id,name"},
            access_token=bundle.access.reveal(),
        )
        payload: Any = json.loads(result.body) if result.ok else None
        if not isinstance(payload, dict) or payload != {
            "id": config.label_id,
            "name": "PROBATION",
        }:
            raise ConnectorError("approved_label_identity_mismatch")
        if role == "read":
            return persist_read_authorization(config, bundle, root=root, clock=clock)
        return persist_write_authorization(config, bundle, root=root, clock=clock)
    finally:
        api.close()
        token_http.close()
        if not waited:
            try:
                listener.wait(timeout_seconds=0)
            except ConnectorError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--check",
        action="store_true",
        help="Local presence/ACL check; no network or writes",
    )
    action.add_argument(
        "--authorize-read",
        action="store_true",
        help="Open Google consent for a new readonly grant",
    )
    action.add_argument(
        "--authorize-write",
        action="store_true",
        help="Open Google consent for the Executor-only send+modify grant",
    )
    args = parser.parse_args(argv)
    try:
        config = SetupSettings(_env_file=ROOT / ".env")
        if args.check:
            for key, value in local_status(config).items():
                print(f"{key}: {str(value).lower()}")
            print(f"redirect_uri: http://127.0.0.1:{config.redirect_port}/")
            print("Next: --authorize-read or --authorize-write requires owner consent.")
        elif args.authorize_read:
            grant = authorize_read(config)
            print("Read-only setup complete. Connection:", grant.connection_id)
            print(
                "Registration is SHADOW; mail predating observation remains backfill."
            )
        else:
            grant = authorize_write(config)
            print("Executor-only write setup complete. Connection:", grant.connection_id)
            print(
                "The observation role still uses the separate read-only grant; "
                "every effect needs explicit owner approval."
            )
        return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        code = getattr(exc, "safe_code", type(exc).__name__)
        print(
            "Setup did not complete:",
            code if re.fullmatch(r"[a-z_0-9]{1,90}", code) else type(exc).__name__,
        )
        print(
            "Use a Desktop OAuth client and approve only the requested Gmail read/write access; "
            "ACL failures deny setup."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
