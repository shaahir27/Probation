"""Role-bound Gmail credentials: one grant per process, memory-only access tokens.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 5, CONTRACT.md I-2 and section 15, FP-D4/FP-D6.
A process resolves only the role provisioned to it. The write grant is not merely refused to a
reader, it is unnameable and unenumerable there: the child environment carries exactly one grant and
the source answers only for that grant (both in ``credentials_state``, re-exported below). Access
tokens stay in process memory, persisted state is scopes plus expiry, the durable refresh token
lives only in an owner-only private file, and no secret reaches a log, argument, URL, DB row or
repr.
"""

import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Protocol

from probation.connectors.credentials_state import (
    BASE_CHILD_ENV,
    CREDENTIAL_STATE_TABLE,
    GRANT_ENV_PREFIX,
    CredentialSource,
    CredentialStateRepository,
    CredentialStateRow,
    EnvCredentialSource,
    InMemoryCredentialStateRepository,
    ProvisionedGrant,
    RefreshTokenStore,
    SecretMaterial,
    StoreCredentialStateRepository,
    build_child_env,
    checked_text,
    default_state_repository,
    grant_env_name,
    normalize_account,
)
from probation.connectors.types import (
    ConnectorError,
    CredentialRole,
    CredentialUnavailable,
    ProviderUnavailable,
    ScopeMismatch,
)
from probation.core.clock import Clock, format_timestamp, get_clock

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
FULL_ACCESS_SCOPE = "https://mail.google.com/"
_APPROVED_SCOPES = frozenset({READONLY_SCOPE, SEND_SCOPE, MODIFY_SCOPE})
_READ_SCOPES = frozenset({READONLY_SCOPE})

#: Capability to the narrowest scopes it genuinely needs, aligned with ``gmail_auth.plan_scopes``.
#: A capability absent here imposes no credential requirement, so credentials never disables it:
#: ``undo_history_proof`` is a proof over history already observed (its caller names the scope it
#: fetches with) and ``attribution`` is provider-unknown (contract C1/C9).
CREDENTIAL_SCOPES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "read": (READONLY_SCOPE,),
        "send": (SEND_SCOPE,),
        "forward": (SEND_SCOPE,),
        "archive": (MODIFY_SCOPE,),
        "trash": (MODIFY_SCOPE,),
        "conditional_write": (MODIFY_SCOPE,),
        "reconciliation": (MODIFY_SCOPE,),
    }
)

#: A grant is refreshed while this much life remains, so an in-flight call cannot outlive it.
REFRESH_MARGIN_SECONDS = 60
_MAX_TOKEN_LIFETIME_SECONDS = 3600

_LOG = logging.getLogger("probation.connectors.credentials")


class StaleRefreshRejected(ProviderUnavailable):
    """A newer writer won the generation race; this bundle is stale and must not be served."""


class TokenRefresher(Protocol):
    """Exchanges refresh material for a fresh bundle. Serialized by the provider."""

    def refresh(self, credential_ref: str, refresh_material: SecretMaterial) -> "TokenBundle": ...


def _scope_short(scope: str) -> str:
    tail = scope.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail else "unnamed_scope"


def _owner_role_of(scopes: Sequence[str]) -> CredentialRole | None:
    """Which role may hold these scopes. An empty or unapproved set has no owner."""
    if not scopes or any(scope not in _APPROVED_SCOPES for scope in scopes):
        return None
    return "read" if all(scope in _READ_SCOPES for scope in scopes) else "write"


@dataclass(frozen=True, repr=False)
class TokenBundle:
    """One provider result: the verified account, its granted scopes and the live material."""

    account_id: str
    granted_scopes: tuple[str, ...]
    expires_in_seconds: int
    access: SecretMaterial
    refresh: SecretMaterial | None = None

    def __post_init__(self) -> None:
        if self.access.kind != "access":
            raise ConnectorError("access_material_kind_mismatch")
        if self.refresh is not None and self.refresh.kind != "refresh":
            raise ConnectorError("refresh_material_kind_mismatch")
        if not 0 < self.expires_in_seconds <= _MAX_TOKEN_LIFETIME_SECONDS:
            raise ConnectorError("invalid_token_lifetime")
        checked_text(normalize_account(self.account_id), "account_id")
        if not self.granted_scopes:
            raise ScopeMismatch("empty_granted_scope_set")

    def __repr__(self) -> str:
        return (
            f"TokenBundle(account_id={self.account_id!r}, scope_count={len(self.granted_scopes)}, "
            f"access={self.access!r}, refresh_present={self.refresh is not None})"
        )


class RoleCredentialProvider:
    """Resolves one role's access token from memory, refreshing it serialized under a guard.

    Every failure is structural and typed — a role never provisioned here, a grant never installed,
    an expiry with nothing to refresh it, a narrowed scope, a revoked grant, a bundle bound to
    another account, a lost generation race — and none falls back to another account, another role
    or an app password.
    """

    def __init__(
        self,
        *,
        grant: ProvisionedGrant,
        source: CredentialSource,
        refresher: TokenRefresher | None = None,
        state: CredentialStateRepository | None = None,
        token_store: RefreshTokenStore | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._grant = grant
        self._source = source
        self._refresher = refresher
        self._state: CredentialStateRepository = (
            state if state is not None else InMemoryCredentialStateRepository()
        )
        self._token_store = token_store
        self._clock = clock if clock is not None else get_clock()
        self._lock = threading.Lock()
        self._access: SecretMaterial | None = None
        self._refresh: SecretMaterial | None = None
        self._scopes: tuple[str, ...] = ()
        self._expires_at: datetime | None = None
        self._revoked = False

    @property
    def role(self) -> CredentialRole:
        return self._grant.role

    def __repr__(self) -> str:
        return (
            f"RoleCredentialProvider(role={self._grant.role!r}, "
            f"granted_scope_count={len(self._scopes)}, revoked={self._revoked})"
        )

    def granted_scopes(self) -> tuple[str, ...]:
        with self._lock:
            return () if self._revoked or self._access is None else self._scopes

    def install_bundle(self, bundle: TokenBundle) -> int:
        """Bind a verified bundle to this role. The generation guard runs before anything serves."""
        with self._lock:
            return self._apply_locked(bundle, refreshed=False)

    def resolve_access(
        self, capability: str, required_scopes: Sequence[str] = ()
    ) -> SecretMaterial:
        """The token for one capability, or a typed denial naming exactly what is missing."""
        del capability  # the credential facts are scope- and role-bound; callers log the name.
        return self._resolve(tuple(required_scopes))

    def resolve_for_role(
        self, role: str, capability: str, required_scopes: Sequence[str] = ()
    ) -> SecretMaterial:
        """Resolve under an explicit role claim. A role not provisioned here is never reached."""
        if role != self._grant.role:
            # Denied before the source is touched: a reader can neither name, inherit, enumerate
            # nor guess the write grant, so no lookup of another role's material ever happens.
            raise CredentialUnavailable("role_not_provisioned_to_process")
        return self._resolve(tuple(required_scopes))

    def is_disabled(self, capability: str) -> str | None:
        """Why one capability cannot run here, or None when credentials do not block it."""
        required = CREDENTIAL_SCOPES.get(capability)
        if required is None:
            return None
        try:
            self.resolve_access(capability, required)
        except ConnectorError as exc:
            _LOG.info(
                "gmail_credential_capability_disabled",
                extra={"capability": capability, "safe_code": exc.safe_code},
            )
            return exc.safe_code
        return None

    def revoke(self) -> None:
        """Drop the live grant for good: a revoked grant never resolves or reinstalls here."""
        with self._lock:
            self._revoked = True
            self._clear_locked()
            self._refresh = None
            _LOG.info("gmail_credential_grant_revoked", extra=self._fields())

    def _resolve(self, required_scopes: tuple[str, ...]) -> SecretMaterial:
        with self._lock:
            if self._revoked:
                raise CredentialUnavailable("grant_revoked")
            if self._access is None:
                raise CredentialUnavailable(self._absence_code(required_scopes))
            if self._expiring():
                self._refresh_locked()
            missing = next((s for s in required_scopes if s not in self._scopes), None)
            if missing is not None:
                raise ScopeMismatch(f"scope_missing_{_scope_short(missing)}")
            return self._access

    def _absence_code(self, required_scopes: tuple[str, ...]) -> str:
        owner = _owner_role_of(required_scopes)
        if owner is not None and owner != self._grant.role:
            return "role_not_provisioned_to_process"
        return "grant_not_installed"

    def _expiring(self) -> bool:
        if self._expires_at is None:
            return True
        return (self._expires_at - self._clock.now(UTC)).total_seconds() <= REFRESH_MARGIN_SECONDS

    def _clear_locked(self) -> None:
        self._access, self._scopes, self._expires_at = None, (), None

    def _fields(self, **detail: object) -> dict[str, object]:
        """Structured log fields: role and opaque reference plus a safe detail of our own."""
        return {"role": self._grant.role, "credential_ref": self._grant.credential_ref, **detail}

    def _refresh_locked(self) -> None:
        """Called while holding the lock: one refresh per reference, waiters reuse its result."""
        if self._refresher is None:
            raise CredentialUnavailable("grant_expired_no_refresher")
        if self._refresh is None:
            self._refresh = self._source.fetch(self._grant.role, self._grant.credential_ref)
        try:
            bundle = self._refresher.refresh(self._grant.credential_ref, self._refresh)
        except ConnectorError:
            raise
        except Exception as exc:  # typed failures only; the cause must never carry a secret
            raise ProviderUnavailable("credential_refresh_failed") from exc
        self._apply_locked(bundle, refreshed=True)

    def _apply_locked(self, bundle: TokenBundle, *, refreshed: bool) -> int:
        if self._revoked:
            raise CredentialUnavailable("grant_revoked")
        if normalize_account(bundle.account_id) != normalize_account(self._grant.account_id):
            raise CredentialUnavailable("account_binding_mismatch")  # never another account
        scopes = self._approved_scopes(bundle.granted_scopes)
        expires_at = self._clock.now(UTC) + timedelta(seconds=bundle.expires_in_seconds)
        current = self._state.load(self._grant.credential_ref)
        generation = 1 if current is None else current.generation + 1
        row = self._grant.state_row(
            generation,
            scopes,
            format_timestamp(expires_at),
            self._clock.now_iso() if bundle.refresh is not None else None,
        )
        if not self._state.commit(row):
            self._clear_locked()  # lost the guard race: a newer generation is authoritative
            raise StaleRefreshRejected("stale_refresh_rejected")
        self._access, self._scopes, self._expires_at = bundle.access, scopes, expires_at
        if bundle.refresh is not None:
            self._refresh = bundle.refresh
            if self._token_store is not None:
                # An ACL denial propagates as a startup failure; unprotected state is never an
                # acceptable fallback for a persisted refresh token.
                self._token_store.write(self._grant.credential_ref, bundle.refresh)
        _LOG.info(
            "gmail_credential_bundle_installed",
            extra=self._fields(generation=generation, scope_count=len(scopes), refreshed=refreshed),
        )
        return generation

    def _approved_scopes(self, granted: Sequence[str]) -> tuple[str, ...]:
        scopes = tuple(dict.fromkeys(granted))
        if not scopes:
            raise ScopeMismatch("empty_granted_scope_set")
        for scope in scopes:
            if scope == FULL_ACCESS_SCOPE:
                raise ScopeMismatch("forbidden_scope_granted")
            if scope not in _APPROVED_SCOPES:
                raise ScopeMismatch(f"unapproved_scope_granted_{_scope_short(scope)}")
        if self._grant.role == "read" and not set(scopes) <= _READ_SCOPES:
            raise ScopeMismatch("read_role_may_not_hold_write_scope")
        return scopes


__all__ = [
    "BASE_CHILD_ENV",
    "CREDENTIAL_SCOPES",
    "CREDENTIAL_STATE_TABLE",
    "FULL_ACCESS_SCOPE",
    "GRANT_ENV_PREFIX",
    "MODIFY_SCOPE",
    "READONLY_SCOPE",
    "REFRESH_MARGIN_SECONDS",
    "SEND_SCOPE",
    "CredentialSource",
    "CredentialStateRepository",
    "CredentialStateRow",
    "EnvCredentialSource",
    "InMemoryCredentialStateRepository",
    "ProvisionedGrant",
    "RefreshTokenStore",
    "RoleCredentialProvider",
    "SecretMaterial",
    "StaleRefreshRejected",
    "StoreCredentialStateRepository",
    "TokenBundle",
    "TokenRefresher",
    "build_child_env",
    "default_state_repository",
    "grant_env_name",
    "normalize_account",
]
