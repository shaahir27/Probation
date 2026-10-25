"""Live credential provisioning for one Gmail role. No token is written, returned or logged."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from probation.connectors.credentials import RoleCredentialProvider
from probation.connectors.credentials_state import (
    CredentialSource,
    ProvisionedGrant,
    SecretMaterial,
)
from probation.connectors.types import ConnectorError, CredentialUnavailable, HttpTransport
from probation.core.clock import Clock
from probation.packs.mail.connectors.gmail_auth import (
    OAuthTokenExchange,
    StateVault,
    TokenTransport,
)
from probation.packs.mail.connectors.gmail_transport import (
    GmailProfileGateway,
    GoogleTokenTransport,
)

_FIELDS: Final = frozenset({"refresh_token", "client_id", "client_secret"})
_MAX_FIELD_BYTES: Final = 4096


@dataclass(frozen=True, slots=True, repr=False)
class LiveOAuthClient:
    client_id: str
    client_secret: str
    refresh_token: str

    def __repr__(self) -> str:
        return f"LiveOAuthClient(client_id={self.client_id!r}, refresh_present=True)"


def parse_live_client(raw: str) -> LiveOAuthClient:
    """Parse the single grant env JSON. Unknown/missing fields fail closed."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConnectorError("live_grant_malformed") from exc
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise ConnectorError("live_grant_malformed")
    values: dict[str, str] = {}
    for name in _FIELDS:
        value = data[name]
        if not isinstance(value, str) or not value or len(value.encode()) > _MAX_FIELD_BYTES:
            raise ConnectorError("live_grant_malformed")
        values[name] = value
    return LiveOAuthClient(**values)


class LiveCredentialSource(CredentialSource):
    """Answers only for the one grant bound to this process."""

    def __init__(self, grant: ProvisionedGrant, client: LiveOAuthClient) -> None:
        self._grant, self._client = grant, client

    def fetch(self, role: str, credential_ref: str) -> SecretMaterial:
        if role != self._grant.role or credential_ref != self._grant.credential_ref:
            raise CredentialUnavailable("grant_not_provisioned_to_process")
        return SecretMaterial(self._client.refresh_token, "refresh")


def build_live_provider(
    *,
    grant: ProvisionedGrant,
    env: Mapping[str, str],
    clock: Clock,
    api_transport: HttpTransport,
    token_transport: TokenTransport | None = None,
) -> RoleCredentialProvider:
    """Install one verified bundle and hand back a provider that refreshes lazily."""
    raw = env.get(grant.env_name, "")
    if not raw:
        raise CredentialUnavailable("refresh_material_absent")
    client = parse_live_client(raw)
    exchange = OAuthTokenExchange(
        client_id=client.client_id,
        client_secret=client.client_secret,
        vault=StateVault(clock=clock),
        transport=token_transport or GoogleTokenTransport(),
        userinfo=GmailProfileGateway(api_transport),
        clock=clock,
    )
    provider = RoleCredentialProvider(
        grant=grant,
        source=LiveCredentialSource(grant, client),
        refresher=exchange,
        clock=clock,
    )
    bundle = exchange.refresh(grant.credential_ref, SecretMaterial(client.refresh_token, "refresh"))
    if bundle.account_id != grant.account_id.strip().lower():
        raise CredentialUnavailable("account_binding_mismatch")
    provider.install_bundle(bundle)
    return provider
