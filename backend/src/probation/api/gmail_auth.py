"""Loopback owner-credential verification for the private Gmail connector API.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5 and 7; docs/CONTRACT.md sections 3 and 9.
The API process holds no Google credential and makes no provider call. The owner API credential
is injected, is separate from any Google credential, and is verified here in pure code. The
``OwnerContext`` and its source grants are resolved only from verified registration rows in the
private connector store, so a client-supplied account identity can never select a connection.
The OAuth callback listener belongs to the credential boundaries (read worker / Executor), never
to this API: nothing here receives, stores or refreshes a Google token.
"""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Final

from probation.api.authority import OwnerContext
from probation.core.lifecycle import SourceGrant
from probation.db.gmail_store import ConnectorAccess

# The private connector API binds to loopback only. Deployment code must verify its configured
# host against this tuple; a non-loopback bind host is a configuration error, never a fallback.
CONNECTOR_API_BIND_HOSTS: Final[tuple[str, ...]] = ("127.0.0.1", "::1")

_LOOPBACK_CLIENT_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

AUTH_FAILURE_CODE: Final = "owner_credential_required"


class OwnerAuthError(Exception):
    """Typed authentication failure carrying one uniform safe code; never a detail leak."""

    def __init__(self, safe_code: str = AUTH_FAILURE_CODE) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class ConnectorApiMisconfigured(RuntimeError):
    """The private connector API was asked to bind or run outside its loopback boundary."""


@dataclass(frozen=True, slots=True)
class OwnerApiCredential:
    """Injected owner API credential. Holds a token digest only, never the token itself.

    This credential is unrelated to Google credentials: it authenticates the local owner to the
    dashboard-facing connector API. Grants are never derived from it, only the owner identity.
    """

    owner_id: str
    token_sha256: str

    def __post_init__(self) -> None:
        if not self.owner_id or not self.owner_id.strip():
            raise ConnectorApiMisconfigured("owner_credential_needs_owner_id")
        if len(self.token_sha256) != 64:
            raise ConnectorApiMisconfigured("owner_credential_needs_token_digest")


def hash_owner_token(token: str) -> str:
    """One-way digest of the injected owner API token; the token itself is never stored."""
    if not token:
        raise ConnectorApiMisconfigured("owner_token_must_not_be_empty")
    return hashlib.sha256(f"probation-owner-api:{token}".encode()).hexdigest()


def is_loopback_host(host: str | None) -> bool:
    """True only for loopback origins. Absent or unknown hosts fail closed."""
    return host is not None and host in _LOOPBACK_CLIENT_HOSTS


def verify_loopback_binding(host: str) -> str:
    """Assert a configured bind host is loopback. Non-loopback hosts are rejected, not rewritten."""
    if host not in CONNECTOR_API_BIND_HOSTS:
        raise ConnectorApiMisconfigured("bind_host_not_loopback")
    return host


def verify_owner_request(
    *,
    authorization: str | None,
    client_host: str | None,
    credential: OwnerApiCredential | None,
) -> OwnerApiCredential:
    """Pure verification of one request: loopback origin plus a bearer-token digest match.

    Every failure raises the same typed error with the same uniform code so a caller cannot
    distinguish a wrong token from a wrong origin from a missing header.
    """
    if credential is None:
        raise OwnerAuthError()
    if not is_loopback_host(client_host):
        raise OwnerAuthError()
    if authorization is None or not authorization.startswith("Bearer "):
        raise OwnerAuthError()
    token = authorization.removeprefix("Bearer ")
    if not token:
        raise OwnerAuthError()
    try:
        presented = hash_owner_token(token)
    except ConnectorApiMisconfigured as exc:
        raise OwnerAuthError() from exc
    if not hmac.compare_digest(presented, credential.token_sha256):
        raise OwnerAuthError()
    return credential


def resolve_owner_context(owner_id: str, access: ConnectorAccess) -> OwnerContext:
    """Build the owner context from verified registration rows only.

    The ``gmail_connections`` rows were written by the bootstrap administration authority and
    are the sole source of grants. Nothing from the request body, query or headers is consulted,
    so a client cannot name an account or connection that this owner does not have registered.
    """
    rows = access.query(
        "SELECT connection_id, account_id FROM gmail_connections "
        "WHERE owner_id = ? ORDER BY connection_id",
        (owner_id,),
    )
    grants = tuple(
        SourceGrant(
            source_id=f"gmail:{row['connection_id']}",
            connection_id=str(row["connection_id"]),
            account_id=str(row["account_id"]),
            from_addr=str(row["account_id"]),
        )
        for row in rows
    )
    return OwnerContext(owner_id=owner_id, grants=grants)


__all__ = [
    "AUTH_FAILURE_CODE",
    "CONNECTOR_API_BIND_HOSTS",
    "ConnectorApiMisconfigured",
    "OwnerApiCredential",
    "OwnerAuthError",
    "hash_owner_token",
    "is_loopback_host",
    "resolve_owner_context",
    "verify_loopback_binding",
    "verify_owner_request",
]
