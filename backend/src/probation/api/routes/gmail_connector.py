"""Private Gmail connector API surface: loopback, owner-authenticated, credential-free.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5-7; docs/OCT29_DEMO_BUILD_PLAN.md section
12.1 ("Connections" and "Health/readiness" rows); docs/CONTRACT.md sections 3 and 9. Rules this
module enforces by construction:

* The API role holds no Google credential, no transport and no provider call. Readiness is
  composed by the pure evaluator in ``probation.connectors.readiness`` from committed capability
  and cursor rows in the private connector store only.
* Every route is authenticated with the injected owner API credential (``gmail_auth``) and is
  served loopback-only. Owner identity and source grants come from verified registration rows,
  never from client-supplied account identity; an unowned connection id resolves to a uniform 404.
* Responses publish opaque ids, state, capability names, supported/evidence/reason codes, sync
  freshness and hashes only: never an account address, token, label name from an unselected
  resource, message content or a raw receipt.
* Mutations (pause/resume/disconnect) reuse D3's existing command path: an immutable typed
  ``CommandIntent`` recorded through ``CommandStore`` with HTTP 202 and truthful asynchronous
  status. ``gmail_connections`` state moves only via approved commands, consumed by the command
  owner with administration authority — never in memory inside this process.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from probation.api.authority import OwnerContext
from probation.api.gmail_auth import (
    OwnerApiCredential,
    OwnerAuthError,
    resolve_owner_context,
    verify_loopback_binding,
    verify_owner_request,
)
from probation.api.routes.queue import _get_db
from probation.connectors.readiness import (
    ReadinessSignals,
    connection_ref_hash,
    evaluate_readiness,
)
from probation.connectors.types import CapabilityManifest, CapabilityState, ConnectorError
from probation.core.clock import get_clock
from probation.core.lifecycle import CommandIntent, CommandScope, LifecycleError
from probation.db.access import Role, RoleAccess
from probation.db.gmail_store import ConnectorAccess, open_store, store_is_current
from probation.db.lifecycle_commands import CommandStore
from probation.packs.mail.connectors.gmail_sync_state import committed_resync_freshness

router = APIRouter(prefix="/api/gmail", tags=["gmail-connector"])

_COMMAND_TYPES: dict[str, Literal["pause", "resume", "revoke"]] = {
    "pause": "pause",
    "resume": "resume",
    "disconnect": "revoke",
}


@dataclass(frozen=True, slots=True)
class GmailApiConfig:
    """Injected deployment configuration. The bind host must be loopback; there is no fallback."""

    owner_credential: OwnerApiCredential
    store_path: Path
    bind_host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        verify_loopback_binding(self.bind_host)


_config: GmailApiConfig | None = None


def configure_gmail_api(config: GmailApiConfig | None) -> None:
    """Install (or clear) the injected owner credential and store location."""
    global _config
    _config = config


def current_config() -> GmailApiConfig:
    if _config is None:
        # Fail closed: an unconfigured private API serves nothing, not even an error detail.
        raise HTTPException(status_code=503, detail="connector_api_not_configured")
    return _config


def require_gmail_owner(request: Request) -> OwnerContext:
    """Authenticate the injected owner credential and resolve grants from registration rows."""
    config = current_config()
    try:
        credential = verify_owner_request(
            authorization=request.headers.get("Authorization"),
            client_host=request.client.host if request.client is not None else None,
            credential=config.owner_credential,
        )
    except OwnerAuthError as exc:
        # One uniform typed 401 for every failure mode: no origin, header or token detail leaks.
        raise HTTPException(status_code=401, detail=exc.safe_code) from exc
    access = _api_access(config.store_path)
    try:
        return resolve_owner_context(credential.owner_id, access)
    finally:
        access.conn.close()


Owner = Annotated[OwnerContext, Depends(require_gmail_owner)]


class GmailCommandBody(BaseModel):
    """Immutable typed mutation request. Carries no account identity: scope is server-resolved."""

    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["v1"]
    request_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    command: Literal["pause", "resume", "disconnect"]


def _api_access(store_path: Path) -> ConnectorAccess:
    """Open the private store with the read-only ``api`` authority; unavailable fails closed."""
    if not store_path.exists():
        raise HTTPException(status_code=503, detail="connector_store_unavailable")
    conn = open_store(store_path)
    if not store_is_current(conn):
        conn.close()
        raise HTTPException(status_code=503, detail="connector_store_unavailable")
    return ConnectorAccess(conn, "api")


def _owned_connection(access: ConnectorAccess, owner: OwnerContext, ref: str) -> sqlite3.Row:
    """Resolve one connection by opaque id or published ref hash, strictly within the owner's
    verified registrations. Anything else is a uniform 404: existence is not disclosed."""
    rows = access.query(
        "SELECT connection_id, state FROM gmail_connections WHERE owner_id = ? "
        "ORDER BY connection_id",
        (owner.owner_id,),
    )
    for row in rows:
        connection_id = str(row["connection_id"])
        if ref == connection_id or ref == connection_ref_hash(connection_id):
            return row
    raise HTTPException(status_code=404, detail="connection_not_found")


def _capability_rows(access: ConnectorAccess, connection_id: str) -> list[sqlite3.Row]:
    return access.query(
        "SELECT name, owner_role, supported, evidence, reason, manifest_version, verified_at "
        "FROM gmail_capabilities WHERE connection_id = ? ORDER BY owner_role, name",
        (connection_id,),
    )


def _read_cursor(access: ConnectorAccess, connection_id: str) -> sqlite3.Row | None:
    return access.one(
        "SELECT committed_history_id, watermark_at, catchup_complete, protocol_version "
        "FROM gmail_sync_cursors WHERE connection_id = ? AND role = 'read' "
        "ORDER BY filter_revision DESC, committed_history_id DESC LIMIT 1",
        (connection_id,),
    )


def _states(rows: list[sqlite3.Row], owner_role: str) -> tuple[CapabilityState, ...]:
    return tuple(
        CapabilityState(
            name=row["name"],
            supported=bool(row["supported"]),
            verified_at=str(row["verified_at"]),
            evidence=str(row["evidence"]),
            reason=None if row["reason"] is None else str(row["reason"]),
        )
        for row in rows
        if str(row["owner_role"]) == owner_role
    )


def _connection_summary(row: sqlite3.Row) -> dict[str, Any]:
    connection_id = str(row["connection_id"])
    return {
        "connection_id": connection_id,
        "connection_ref": connection_ref_hash(connection_id),
        "state": str(row["state"]),
    }


def _freshness_payload(cursor: sqlite3.Row | None) -> dict[str, Any]:
    """Store truth only: the committed watermark and its observed-at, or an honest absence."""
    if cursor is None:
        return {
            "committed_history_id": None,
            "watermark_at": None,
            "catchup_complete": False,
            "resync_required": True,
        }
    return {
        "committed_history_id": int(cursor["committed_history_id"]),
        "watermark_at": None if cursor["watermark_at"] is None else str(cursor["watermark_at"]),
        "catchup_complete": bool(cursor["catchup_complete"]),
        "resync_required": False,
    }


@router.get("/connections")
def list_connections(owner: Owner) -> dict[str, Any]:
    """The verified owner's registered connections: opaque ids, published hashes and state."""
    access = _api_access(current_config().store_path)
    try:
        rows = access.query(
            "SELECT connection_id, state FROM gmail_connections WHERE owner_id = ? "
            "ORDER BY connection_id",
            (owner.owner_id,),
        )
        return {"connections": [_connection_summary(row) for row in rows]}
    finally:
        access.conn.close()


@router.get("/connections/{connection_ref}")
def get_connection(connection_ref: str, owner: Owner) -> dict[str, Any]:
    """One connection: state, committed capability rows and committed sync freshness."""
    access = _api_access(current_config().store_path)
    try:
        row = _owned_connection(access, owner, connection_ref)
        connection_id = str(row["connection_id"])
        capability_rows = _capability_rows(access, connection_id)
        return {
            **_connection_summary(row),
            "capabilities": [
                {
                    "name": str(item["name"]),
                    "owner_role": str(item["owner_role"]),
                    "supported": bool(item["supported"]),
                    "evidence": str(item["evidence"]),
                    "reason": None if item["reason"] is None else str(item["reason"]),
                    "manifest_version": int(item["manifest_version"]),
                    "verified_at": str(item["verified_at"]),
                }
                for item in capability_rows
            ],
            "freshness": _freshness_payload(_read_cursor(access, connection_id)),
        }
    finally:
        access.conn.close()


@router.get("/connections/{connection_ref}/readiness")
def get_readiness(connection_ref: str, owner: Owner) -> dict[str, Any]:
    """Versioned readiness composed from committed rows only. Never a live provider call."""
    access = _api_access(current_config().store_path)
    try:
        row = _owned_connection(access, owner, connection_ref)
        connection_id = str(row["connection_id"])
        capability_rows = _capability_rows(access, connection_id)
        cursor = _read_cursor(access, connection_id)
        manifest_version = max(
            (int(item["manifest_version"]) for item in capability_rows), default=0
        )
        state = str(row["state"])
        manifest = CapabilityManifest(
            provider="gmail",
            provider_version=str(cursor["protocol_version"]) if cursor is not None else "gmail-v1",
            states=_states(capability_rows, "read"),
        )
        signals = ReadinessSignals(
            connection_state=state,  # type: ignore[arg-type]
            paused=state == "PAUSED",
            revoked=state == "DISCONNECTED",
            authorization_failed=state == "AUTH_REQUIRED",
            # No committed watermark means the observation window is unproven: force re-sync
            # truthfully instead of reporting "no changes". Cursor continuity and effect anchors
            # belong to the ingestor/Executor; the API never fabricates them, so undo proof stays
            # fail-closed here.
            resync_required=cursor is None,
            cursor_gap=False,
            anchor_history_id=None,
            retained_from=None,
            undo_evidence_continuous=False,
        )
        try:
            readiness = evaluate_readiness(
                connection_id=connection_id,
                manifest=manifest,
                write_states=_states(capability_rows, "write"),
                signals=signals,
                now=get_clock().now_iso(),
                watermark_at=None
                if cursor is None or cursor["watermark_at"] is None
                else str(cursor["watermark_at"]),
                committed_history_id=int(cursor["committed_history_id"])
                if cursor is not None
                else 0,
                catchup_complete=bool(cursor["catchup_complete"]) if cursor is not None else False,
                resync=committed_resync_freshness(access, connection_id),
            )
        except ConnectorError as exc:
            # Fail closed on any composition problem; expose the safe code only.
            raise HTTPException(status_code=503, detail="readiness_unavailable") from exc
        return {
            "readiness_version": readiness.version,
            "manifest_version": manifest_version,
            **_connection_summary(row),
            "blocking_reason": readiness.blocking_reason,
            "observation_allowed": readiness.observation_allowed,
            "dependent_autonomy_permitted": readiness.dependent_autonomy_permitted,
            "capabilities": [
                {
                    "name": item.name,
                    "supported": item.supported,
                    "evidence": item.evidence,
                    "reason": item.reason,
                    "verified_at": item.verified_at,
                }
                for item in readiness.states
            ],
            "freshness": {
                "committed_history_id": readiness.freshness.committed_history_id,
                "watermark_at": readiness.freshness.watermark_at,
                "catchup_complete": readiness.freshness.catchup_complete,
                "resync_required": readiness.freshness.resync_required,
                "cursor_gap": readiness.freshness.cursor_gap,
                "age_seconds": readiness.freshness.age_seconds,
                "stale": readiness.freshness.stale,
                "fresh": readiness.freshness.fresh,
            },
        }
    finally:
        access.conn.close()


@router.post("/connections/{connection_ref}/commands", status_code=202)
def submit_connection_command(
    connection_ref: str, body: GmailCommandBody, owner: Owner
) -> dict[str, Any]:
    """Record a pause/resume/disconnect intent on D3's existing command path (HTTP 202).

    The scope's account identity is resolved from the owner's verified grant, never from the
    request. The durable state transition is performed by the command's designated consumer with
    administration authority; this process writes only the validated initial intent.
    """
    access = _api_access(current_config().store_path)
    try:
        row = _owned_connection(access, owner, connection_ref)
    finally:
        access.conn.close()
    connection_id = str(row["connection_id"])
    grant = owner.grant_for(f"gmail:{connection_id}")
    conn = _get_db()
    try:
        if conn.execute("SELECT id FROM admin_commands WHERE id=?", (body.request_id,)).fetchone():
            raise HTTPException(409, "command_id_conflict")
        result = CommandStore(RoleAccess(conn, Role.API)).submit(
            CommandIntent(
                request_id=body.request_id,
                owner_id=owner.owner_id,
                type=_COMMAND_TYPES[body.command],
                scope=CommandScope(
                    connection_id=grant.connection_id,
                    account_id=grant.account_id,
                ),
                created_at=get_clock().now_iso(),
            )
        )
        return {
            "request_id": result.request_id,
            "command": body.command,
            "status": "recorded",
            "status_url": f"/api/commands/{result.request_id}",
        }
    except LifecycleError as exc:
        raise HTTPException(409, exc.code) from exc
    finally:
        conn.close()
