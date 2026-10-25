"""Gmail write capability truth and the pre-dispatch gate.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 2, 6 and 7. The write manifest inherits every
read-side verdict verbatim and can only ever add write-owned rows: Gmail's ``messages.modify`` has
no precondition (C1), its history carries no actor identity (C9) and ``messages.send`` has no
idempotency key (C8). A gate therefore blocks a dependent effect *before* it is dispatched, and
reports a safe reason, instead of letting a local lock masquerade as provider atomicity.
CAS-dependent effects are blocked by default; only an explicit ``allow_degraded_cas=True`` from
the caller permits the check-then-act path, and that verdict still reports the missing guarantee.

Row ownership follows the released matrix: the Executor writes only ``owner_role='write'`` rows in
the private store, and only the four names the DDL admits per role. A supported row stores no
reason, so no reader can mistake a note for a guarantee.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from probation.connectors.types import (
    CapabilityManifest,
    CapabilityName,
    CapabilityState,
    ConnectorError,
)
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.gmail_auth import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
)
from probation.packs.mail.connectors.gmail_read import GmailReadConnector

WRITE_OWNED: Final[frozenset[str]] = frozenset(
    {
        "archive",
        "trash",
        "send",
        "forward",
        "reconciliation",
        "undo_history_proof",
        "conditional_write",
    }
)

#: Each operation lists the provider capabilities it depends on. An operation whose dependency is
#: unsupported must be refused before dispatch, never attempted and explained afterwards.
GATE_REQUIREMENTS: Final[Mapping[str, tuple[CapabilityName, ...]]] = {
    "archive": ("archive", "undo_history_proof"),
    "trash": ("trash", "undo_history_proof"),
    "undo": ("archive", "undo_history_proof"),
    "send": ("send",),
    "forward": ("forward", "send"),
    "reconcile": ("reconciliation",),
    "atomic_reconcile": ("reconciliation", "conditional_write"),
    "attribution": ("attribution",),
}

#: Operations that only make sense if the provider can compare-and-set. Gmail cannot (C1), so they
#: are refused unless the caller states, in code, that it accepts check-then-act degradation.
CAS_REQUIRED: Final[Mapping[str, tuple[CapabilityName, ...]]] = {
    "archive": ("conditional_write",),
    "trash": ("conditional_write",),
    "undo": ("conditional_write",),
    "atomic_reconcile": ("conditional_write",),
}

#: The reason every default-gate refusal and every degraded verdict carries. It names the missing
#: provider guarantee, never a local lock that only looks like one.
DEGRADED_CAS_REASON: Final = "conditional_write_unsupported"

OPERATION_SCOPES: Final[Mapping[str, tuple[str, ...]]] = {
    "send": (GMAIL_SEND_SCOPE,),
    "forward": (GMAIL_SEND_SCOPE,),
    "archive": (GMAIL_MODIFY_SCOPE,),
    "trash": (GMAIL_MODIFY_SCOPE,),
    "undo": (GMAIL_MODIFY_SCOPE,),
    "reconcile": (GMAIL_MODIFY_SCOPE,),
    "atomic_reconcile": (GMAIL_MODIFY_SCOPE,),
    "attribution": (GMAIL_READONLY_SCOPE,),
}

_NO_PRECONDITION: Final = "modify_has_no_precondition_c1"
_NO_ACTOR: Final = "history_has_no_actor_identity_c9"

_UPSERT_CAPABILITY = """INSERT INTO gmail_capabilities
 (connection_id,account_id,name,owner_role,supported,evidence,reason,manifest_version,verified_at)
 VALUES(?,?,?,'write',?,?,?,?,?)
 ON CONFLICT(connection_id,name,owner_role) DO UPDATE SET
  supported=excluded.supported,evidence=excluded.evidence,reason=excluded.reason,
  manifest_version=excluded.manifest_version,verified_at=excluded.verified_at
 WHERE excluded.manifest_version>=gmail_capabilities.manifest_version
  AND excluded.account_id=gmail_capabilities.account_id"""


class CapabilityBlocked(ConnectorError):
    """A dependent effect is refused before dispatch because the provider cannot carry it."""


@dataclass(frozen=True)
class GateVerdict:
    """One operation's readiness: allowed or refused, with exactly one safe reason.

    ``degraded`` marks an allowed operation that runs without the provider guarantee it names:
    it is dispatched check-then-act, and the verdict still reports the missing capability.
    """

    operation: str
    allowed: bool
    safe_reason: str | None = None
    missing: tuple[str, ...] = ()
    degraded: bool = False


def build_write_manifest(
    read: GmailReadConnector, *, granted_scopes: Sequence[str] = ()
) -> CapabilityManifest:
    """Extend the read worker's truthful manifest; never upgrade an inherited verdict."""
    inherited = read.capabilities()
    if not inherited.states:
        raise ConnectorError("empty_read_manifest")
    verified_at = inherited.states[0].verified_at
    by_name: dict[str, CapabilityState] = {state.name: state for state in inherited.states}
    by_name.update(
        {
            "archive": _state("archive", True, verified_at),
            "trash": _state("trash", True, verified_at),
            "send": _state("send", True, verified_at),
            "forward": _state("forward", True, verified_at),
            "attribution": _state("attribution", False, verified_at, reason=_NO_ACTOR),
        }
    )
    order: tuple[CapabilityName, ...] = (
        "read",
        "archive",
        "trash",
        "send",
        "forward",
        "reconciliation",
        "undo_history_proof",
        "conditional_write",
        "attribution",
    )
    return CapabilityManifest(
        provider=inherited.provider,
        provider_version=inherited.provider_version,
        states=tuple(by_name[name] for name in order if name in by_name),
        granted_scopes=tuple(granted_scopes),
        idempotency="none",
        reconciliation=inherited.reconciliation,
    )


def persist_write_capabilities(
    access: ConnectorAccess,
    *,
    connection_id: str,
    account_id: str,
    manifest: CapabilityManifest,
    manifest_version: int = 1,
) -> int:
    """Store the Executor-owned rows. A second reader of the file cannot rewrite them."""
    if manifest_version < 1:
        raise ConnectorError("invalid_manifest_version")
    if access.authority != "executor":
        # The private store enforces authority per table, and both roles own
        # ``gmail_capabilities``; the row split by ``owner_role`` is therefore enforced here.
        raise ConnectorError("capability_rows_need_executor_authority")
    written = 0
    for state in manifest.states:
        if state.name not in WRITE_OWNED:
            continue
        written += access.write(
            "gmail_capabilities",
            _UPSERT_CAPABILITY,
            (
                connection_id,
                account_id,
                state.name,
                1 if state.supported else 0,
                state.evidence,
                None if state.supported else state.reason,
                manifest_version,
                state.verified_at,
            ),
        )
    return written


def load_write_manifest(
    access: ConnectorAccess, *, connection_id: str, account_id: str
) -> CapabilityManifest:
    """Re-read the stored verdicts. Absent rows stay absent, never inferred as supported."""
    rows = access.query(
        "SELECT name,supported,evidence,reason,verified_at FROM gmail_capabilities"
        " WHERE connection_id=? AND account_id=? AND owner_role='write'",
        (connection_id, account_id),
    )
    states = tuple(
        CapabilityState(
            name=str(row["name"]),  # type: ignore[arg-type]
            supported=bool(row["supported"]),
            verified_at=str(row["verified_at"]),
            evidence=str(row["evidence"]),
            reason=None if row["reason"] is None else str(row["reason"]),
        )
        for row in rows
    )
    return CapabilityManifest(
        provider="gmail",
        provider_version="v1",
        states=states,
        granted_scopes=_granted_scopes(access, connection_id, account_id),
    )


class CapabilityGate:
    """Refuses an effect whose provider capability, or grant, is missing.

    The default blocks every CAS-dependent operation: Gmail reports ``conditional_write``
    unsupported (C1), so archive/trash/undo must not quietly degrade to check-then-act. A caller
    that deliberately accepts that degradation passes ``allow_degraded_cas=True``; the returned
    verdict then allows dispatch but still carries :data:`DEGRADED_CAS_REASON` and
    ``degraded=True``. ``require_provider_cas=True`` stays strict and wins over any opt-in.
    """

    def __init__(
        self,
        manifest: CapabilityManifest,
        *,
        require_provider_cas: bool = False,
        allow_degraded_cas: bool = False,
    ) -> None:
        if require_provider_cas and allow_degraded_cas:
            # Two opposite policies in one gate would let call order decide the safety property.
            raise ConnectorError("conflicting_cas_policy")
        self._manifest = manifest
        self._require_cas = require_provider_cas
        self._allow_degraded = allow_degraded_cas

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    def verdict(self, operation: str) -> GateVerdict:
        requirements = GATE_REQUIREMENTS.get(operation)
        if requirements is None:
            return GateVerdict(operation, False, "unregistered_operation", (operation,))
        cas = CAS_REQUIRED.get(operation, ())
        degraded = bool(cas) and not self._manifest.supports("conditional_write")
        if degraded and not self._require_cas and not self._allow_degraded:
            return GateVerdict(operation, False, DEGRADED_CAS_REASON, cas)
        wanted = list(requirements)
        if self._require_cas:
            wanted.extend(cas)
        missing = [name for name in wanted if not self._manifest.supports(name)]
        if missing:
            reasons = [self._manifest.state(name).reason for name in missing]  # type: ignore[union-attr]
            return GateVerdict(
                operation, False, _first(reasons, "capability_row_absent"), tuple(missing)
            )
        scopes = set(self._manifest.granted_scopes)
        denied = [scope for scope in OPERATION_SCOPES.get(operation, ()) if scope not in scopes]
        if denied:
            return GateVerdict(operation, False, _scope_reason(denied[0]), ("scope",))
        if degraded:
            return GateVerdict(operation, True, DEGRADED_CAS_REASON, cas, degraded=True)
        return GateVerdict(operation, True)

    def require(self, operation: str) -> GateVerdict:
        verdict = self.verdict(operation)
        if not verdict.allowed:
            raise CapabilityBlocked(f"capability_blocked_{verdict.safe_reason}")
        return verdict

    def readiness(self) -> tuple[GateVerdict, ...]:
        """Per-operation readiness, safe reason included, for status reporting."""
        return tuple(self.verdict(name) for name in GATE_REQUIREMENTS)


def _state(
    name: str, supported: bool, verified_at: str, *, reason: str | None = None
) -> CapabilityState:
    return CapabilityState(
        name=name,  # type: ignore[arg-type]
        supported=supported,
        verified_at=verified_at,
        evidence="supported" if supported else "unsupported",
        reason=reason,
    )


def _first(reasons: list[object], fallback: str) -> str:
    for reason in reasons:
        if isinstance(reason, str) and reason:
            return reason
    return fallback


def _scope_reason(scope: str) -> str:
    tail = scope.rsplit("/auth/", 1)[-1].replace(".", "_")
    return f"scope_not_granted_{tail}"


def _granted_scopes(
    access: ConnectorAccess, connection_id: str, account_id: str
) -> tuple[str, ...]:
    row = access.one(
        "SELECT granted_scopes FROM gmail_connections WHERE connection_id=? AND account_id=?",
        (connection_id, account_id),
    )
    if row is None or not isinstance(row["granted_scopes"], str):
        return ()
    decoded = json.loads(row["granted_scopes"])
    return tuple(str(item) for item in decoded) if isinstance(decoded, list) else ()
