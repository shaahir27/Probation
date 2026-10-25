"""Credential state and process provisioning records for the D4 Gmail connector.

Authority: ``docs/WP12_D4_GMAIL_CONTRACT.md`` section 5 (a process is provisioned exactly one
grant; access tokens stay in process memory; persisted refresh state lives under gitignored
``data/private/`` behind *verified* owner-only ACLs and a failed ACL check denies startup) and
section 7 (`gmail_credential_state`: opaque reference, strictly monotonic generation, scopes and
expiry only).

Re-exported from ``probation.connectors.credentials`` so the released import paths keep working.
The split keeps both modules inside the ~400-line rule and gathers every secret-bearing type, and
the only code that touches durable bytes or a child environment, into one reviewed file.
"""

import hashlib
import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from probation.connectors.acl import apply_owner_only, verify_owner_only
from probation.connectors.types import (
    ConnectorError,
    CredentialRole,
    CredentialUnavailable,
    ProviderUnavailable,
)
from probation.db.gmail_store import ConnectorAccess, StoreAccessError

CREDENTIAL_STATE_TABLE = "gmail_credential_state"
GRANT_ENV_PREFIX = "PROBATION_GMAIL_GRANT_"
_PROBATION_ENV_PREFIX = "PROBATION_GMAIL_"
#: Non-credential variables a worker genuinely needs. Nothing else is ever inherited.
BASE_CHILD_ENV = frozenset({"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP"})

_REF = re.compile(r"^cred-[A-Za-z0-9_-]{1,64}$")
_KIND = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAX_SECRET_BYTES = 8192
_MAX_ID_LEN = 512


def checked_text(value: str, label: str) -> str:
    """A bounded, control-character-free identifier. Anything else is a typed failure."""
    if not value or len(value) > _MAX_ID_LEN:
        raise ConnectorError(f"invalid_{label}")
    if any(ord(char) < 32 for char in value):
        raise ConnectorError(f"unsafe_{label}")
    return value


def normalize_account(value: str) -> str:
    """Accounts bind case-insensitively; the comparison must never depend on how it was typed."""
    return value.strip().lower()


@dataclass(frozen=True, repr=False)
class SecretMaterial:
    """Opaque holder of secret text. Its repr, str and log form carry the kind and length only."""

    value: str
    kind: str

    def __post_init__(self) -> None:
        if not _KIND.match(self.kind):
            raise ConnectorError("invalid_secret_kind")
        if not self.value:
            raise CredentialUnavailable("secret_material_empty")
        if len(self.value.encode("utf-8")) > _MAX_SECRET_BYTES:
            raise ProviderUnavailable("secret_material_oversized")

    def reveal(self) -> str:
        """The only accessor for raw text. Callers must never store, log or embed the result."""
        return self.value

    def __repr__(self) -> str:
        return f"SecretMaterial(kind={self.kind!r}, length={len(self.value)}, redacted=True)"


@dataclass(frozen=True)
class CredentialStateRow:
    """One persisted generation. It has no field that can hold a token: only scopes and time."""

    credential_ref: str
    connection_id: str
    account_id: str
    role: CredentialRole
    generation: int
    granted_scopes: tuple[str, ...]
    access_expires_at: str | None = None
    refresh_updated_at: str | None = None

    def __post_init__(self) -> None:
        if not _REF.match(self.credential_ref):
            raise ConnectorError("invalid_credential_reference")
        checked_text(self.connection_id, "connection_id")
        checked_text(self.account_id, "account_id")
        if self.role not in ("read", "write"):
            raise ConnectorError("invalid_credential_role")
        if self.generation < 1:
            raise ConnectorError("invalid_credential_generation")
        if not self.granted_scopes or not all(
            s.startswith("https://") for s in self.granted_scopes
        ):
            raise ConnectorError("invalid_granted_scopes")
        for column in ("access_expires_at", "refresh_updated_at"):
            value = getattr(self, column)
            if value is not None:
                checked_text(value, column)


@dataclass(frozen=True)
class ProvisionedGrant:
    """The single grant this process was provisioned with. It names no other role's grant."""

    role: CredentialRole
    connection_id: str
    account_id: str
    credential_ref: str

    def __post_init__(self) -> None:
        if self.role not in ("read", "write"):
            raise ConnectorError("invalid_credential_role")
        checked_text(self.connection_id, "connection_id")
        checked_text(normalize_account(self.account_id), "account_id")
        if not _REF.match(self.credential_ref):
            raise ConnectorError("invalid_credential_reference")

    @property
    def env_name(self) -> str:
        return grant_env_name(self.role, self.credential_ref)

    def state_row(
        self, generation: int, scopes: tuple[str, ...], expires_at: str, refreshed_at: str | None
    ) -> CredentialStateRow:
        """State at one generation; the identity columns always come from this grant itself."""
        return CredentialStateRow(
            self.credential_ref,
            self.connection_id,
            self.account_id,
            self.role,
            generation,
            scopes,
            expires_at,
            refreshed_at,
        )


def grant_env_name(role: str, credential_ref: str) -> str:
    """Deterministic, injective environment name for one grant. Carries no secret."""
    if role not in ("read", "write"):
        raise ConnectorError("invalid_credential_role")
    if not _REF.match(credential_ref):
        raise ConnectorError("invalid_credential_reference")
    safe = re.sub(r"[^A-Z0-9]", "_", credential_ref.upper())
    digest = hashlib.sha256(credential_ref.encode("utf-8")).hexdigest()[:10].upper()
    return f"{GRANT_ENV_PREFIX}{role.upper()}_{safe}_{digest}"


def build_child_env(
    parent: dict[str, str], grant: ProvisionedGrant, *, extra_allow: tuple[str, ...] = ()
) -> dict[str, str]:
    """An allowlist-built child environment holding exactly one grant, never an inherited pair."""
    own = grant.env_name
    extras: set[str] = set()
    for name in extra_allow:
        if name == own:
            continue
        # Any Probation credential variable that is not this grant's own is foreign material: a
        # caller cannot smuggle the sibling grant into the child by naming it here.
        if name.startswith(_PROBATION_ENV_PREFIX):
            raise ConnectorError("foreign_grant_not_allowed_in_child")
        extras.add(name.upper())
    child: dict[str, str] = {}
    for key, value in parent.items():
        if key.startswith(GRANT_ENV_PREFIX):
            # The parent legitimately holds both grants; only this grant's own ever travels.
            if key == own:
                child[key] = value
        elif key.upper() in BASE_CHILD_ENV or key.upper() in extras:
            child[key] = value
    return child


class CredentialSource(Protocol):
    """Supplies durable secret material for exactly one provisioned grant."""

    def fetch(self, role: str, credential_ref: str) -> SecretMaterial: ...


class EnvCredentialSource:
    """Answers only for the one grant provisioned to this process. Everything else is denied."""

    def __init__(self, env: dict[str, str], grant: ProvisionedGrant) -> None:
        self._grant = grant
        self._env = dict(env)

    def fetch(self, role: str, credential_ref: str) -> SecretMaterial:
        # Wrong role and wrong reference give the identical code, so nothing is enumerable: a
        # caller cannot probe which grants exist by watching which denial comes back.
        if role != self._grant.role or credential_ref != self._grant.credential_ref:
            raise CredentialUnavailable("grant_not_provisioned_to_process")
        value = self._env.get(self._grant.env_name, "")
        if not value:
            raise CredentialUnavailable("refresh_material_absent")
        return SecretMaterial(value, "refresh")


class CredentialStateRepository(Protocol):
    """Generation-guarded store of one role's public credential state."""

    def load(self, credential_ref: str) -> CredentialStateRow | None: ...

    def commit(self, row: CredentialStateRow) -> bool: ...


class InMemoryCredentialStateRepository:
    """Process-local state for a role whose authority cannot write the store at all."""

    def __init__(self) -> None:
        self._rows: dict[str, CredentialStateRow] = {}
        self._lock = threading.Lock()

    def load(self, credential_ref: str) -> CredentialStateRow | None:
        with self._lock:
            return self._rows.get(credential_ref)

    def commit(self, row: CredentialStateRow) -> bool:
        with self._lock:
            current = self._rows.get(row.credential_ref)
            if current is not None and current.generation >= row.generation:
                return False
            self._rows[row.credential_ref] = row
            return True


_SELECT_STATE = (
    "SELECT credential_ref,connection_id,account_id,role,generation,granted_scopes,"
    "access_expires_at,refresh_updated_at FROM gmail_credential_state WHERE credential_ref=?"
)

_INSERT_STATE = (
    "INSERT INTO gmail_credential_state (credential_ref,connection_id,account_id,role,generation,"
    "granted_scopes,access_expires_at,refresh_updated_at) VALUES (?,?,?,?,?,?,?,?)"
)

_UPDATE_STATE = (
    "UPDATE gmail_credential_state SET generation=?,granted_scopes=?,access_expires_at=?,"
    "refresh_updated_at=? WHERE credential_ref=? AND generation<?"
)


class StoreCredentialStateRepository:
    """The durable state of one credential reference: reference, generation, scopes, expiry."""

    def __init__(self, access: ConnectorAccess) -> None:
        try:
            access.verify_write(CREDENTIAL_STATE_TABLE)
        except StoreAccessError as exc:
            # A denied authority is a configuration failure, never a reason to hold a token.
            raise ProviderUnavailable("credential_state_write_denied") from exc
        self._access = access

    def load(self, credential_ref: str) -> CredentialStateRow | None:
        row = self._access.one(_SELECT_STATE, (credential_ref,))
        return None if row is None else _row_from_sql(row)

    def commit(self, row: CredentialStateRow) -> bool:
        """Strictly monotonic on generation: an equal or older generation cannot clobber."""
        scopes = json.dumps(list(row.granted_scopes))
        try:
            with self._access.transaction() as tx:
                current = tx.one(_SELECT_STATE, (row.credential_ref,))
                if current is not None and int(current["generation"]) >= row.generation:
                    return False
                if current is None:
                    return self._insert(tx, row, scopes)
                changed = tx.write(
                    CREDENTIAL_STATE_TABLE,
                    _UPDATE_STATE,
                    (
                        row.generation,
                        scopes,
                        row.access_expires_at,
                        row.refresh_updated_at,
                        row.credential_ref,
                        row.generation,
                    ),
                )
                return changed == 1
        except (sqlite3.Error, OSError) as exc:
            raise ProviderUnavailable("credential_state_commit_failed") from exc

    @staticmethod
    def _insert(tx: ConnectorAccess, row: CredentialStateRow, scopes: str) -> bool:
        try:
            tx.write(
                CREDENTIAL_STATE_TABLE,
                _INSERT_STATE,
                (
                    row.credential_ref,
                    row.connection_id,
                    row.account_id,
                    row.role,
                    row.generation,
                    scopes,
                    row.access_expires_at,
                    row.refresh_updated_at,
                ),
            )
        except StoreAccessError:
            return False  # a newer row landed first: the caller must fail closed
        return True


def _row_from_sql(row: sqlite3.Row) -> CredentialStateRow:
    cells = dict(row)
    try:
        scopes = json.loads(str(cells["granted_scopes"]))
    except (TypeError, ValueError) as exc:
        raise ConnectorError("stored_granted_scopes_invalid") from exc
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        raise ConnectorError("stored_granted_scopes_invalid")
    role = str(cells["role"])
    if role not in ("read", "write"):
        raise ConnectorError("invalid_credential_role")
    expiry, rotated = cells["access_expires_at"], cells["refresh_updated_at"]
    return CredentialStateRow(
        credential_ref=str(cells["credential_ref"]),
        connection_id=str(cells["connection_id"]),
        account_id=str(cells["account_id"]),
        role=cast("CredentialRole", role),
        generation=int(str(cells["generation"])),
        granted_scopes=tuple(scopes),
        access_expires_at=None if expiry is None else str(expiry),
        refresh_updated_at=None if rotated is None else str(rotated),
    )


def default_state_repository(access: ConnectorAccess | None = None) -> CredentialStateRepository:
    """Store-backed only when this process's authority genuinely owns the state table."""
    if access is None or CREDENTIAL_STATE_TABLE not in access.allowed_tables:
        # Denied by the authority matrix: state stays in this process, never in a shared row.
        return InMemoryCredentialStateRepository()
    return StoreCredentialStateRepository(access)


class RefreshTokenStore:
    """Owner-only private file per opaque credential reference.

    Persisting applies the ACL *before* verifying it, then verifies again after the bytes land.
    Verification alone would only detect a newly created file inheriting the parent DACL — which
    on this host includes Administrators — and would then refuse the very state it just wrote.
    ``PrivatePathRejected`` and ``AclUnsupported`` escape to the caller, which must treat them as
    a startup denial: this class never swallows, downgrades or retries them.
    """

    def __init__(self, root: Path, *, enforce_acl: bool = True) -> None:
        self._root = root
        self._enforce = enforce_acl

    def _path(self, credential_ref: str) -> Path:
        if not _REF.match(credential_ref):
            raise ConnectorError("invalid_credential_reference")
        root = self._root.resolve()
        candidate = (root / f"{credential_ref}.refresh").resolve()
        if candidate.parent != root:
            raise ConnectorError("credential_reference_escapes_root")
        return candidate

    def write(self, credential_ref: str, refresh: SecretMaterial) -> None:
        if refresh.kind != "refresh":
            raise ConnectorError("refresh_material_kind_mismatch")
        text = refresh.reveal()
        if len(text.encode("utf-8")) > _MAX_SECRET_BYTES:
            raise ProviderUnavailable("invalid_refresh_token_size")
        path = self._path(credential_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._enforce:
            apply_owner_only(path.parent, is_dir=True)
            verify_owner_only(path.parent)
        path.write_text(text, encoding="utf-8")
        if self._enforce:
            apply_owner_only(path, is_dir=False)
            verify_owner_only(path)

    def read(self, credential_ref: str) -> SecretMaterial:
        path = self._path(credential_ref)
        if self._enforce:
            verify_owner_only(path)
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise CredentialUnavailable("refresh_state_unreadable")
        return SecretMaterial(text, "refresh")

    def exists(self, credential_ref: str) -> bool:
        return self._path(credential_ref).is_file()
