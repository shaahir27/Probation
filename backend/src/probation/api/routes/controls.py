"""Owner-scoped pause/resume/revoke intents; Examiner performs consumption."""

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from probation.api.authority import OwnerContext, require_owner
from probation.api.routes.queue import _get_db
from probation.core.clock import get_clock
from probation.core.lifecycle import CommandIntent, CommandScope, LifecycleError
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_commands import CommandStore
from probation.db.lifecycle_receipts import ReceiptStore

router = APIRouter(prefix="/api", tags=["controls"])


class ControlBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["v2"]
    request_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    type: Literal["pause", "resume", "revoke"]
    scope: CommandScope


@router.post("/commands", status_code=202)
def submit_control(
    body: ControlBody, owner: Annotated[OwnerContext, Depends(require_owner)]
) -> dict[str, Any]:
    if not any(
        grant.connection_id == body.scope.connection_id
        and grant.account_id == body.scope.account_id
        for grant in owner.grants
    ):
        raise HTTPException(403, "source_grant_required")
    conn = _get_db()
    try:
        if conn.execute("SELECT id FROM admin_commands WHERE id=?", (body.request_id,)).fetchone():
            raise HTTPException(409, "command_id_conflict")
        result = CommandStore(RoleAccess(conn, Role.API)).submit(
            CommandIntent(
                request_id=body.request_id,
                owner_id=owner.owner_id,
                type=body.type,
                scope=body.scope,
                created_at=get_clock().now_iso(),
            )
        )
        return {
            "request_id": result.request_id,
            "status": "recorded",
            "status_url": f"/api/commands/{result.request_id}",
        }
    except LifecycleError as exc:
        raise HTTPException(409, exc.code) from exc
    finally:
        conn.close()


def control_status(
    conn: sqlite3.Connection, command_id: str, owner: OwnerContext | None
) -> dict[str, Any]:
    access = RoleAccess(conn, Role.API)
    if owner is None:
        raise HTTPException(403, "authenticated_owner_required")
    row = conn.execute(
        "SELECT schema_version FROM command_requests WHERE id=?", (command_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "command_not_found")
    if int(row["schema_version"]) == 1:
        lifecycle_intent = CommandStore(access).get(command_id)
        if lifecycle_intent is None or lifecycle_intent.owner_id != owner.owner_id:
            raise HTTPException(404, "command_not_found")
        receipt = ReceiptStore(access).get_command(command_id)
        return {
            "request_id": command_id,
            "type": lifecycle_intent.type,
            "scope": lifecycle_intent.scope.model_dump(),
            "status": receipt.state if receipt else "pending",
            "safe_code": receipt.safe_code if receipt else None,
        }
    if int(row["schema_version"]) == 2:
        from probation.db.replay_commands import ReplayCommandStore

        replay_intent = ReplayCommandStore(access).get(command_id)
        if replay_intent is None or replay_intent.owner_id != owner.owner_id:
            raise HTTPException(404, "command_not_found")
        receipt = ReceiptStore(access).get_command(command_id)
        return {
            "request_id": command_id,
            "type": replay_intent.type,
            "status": receipt.state if receipt else "pending",
            "result": receipt.result if receipt else None,
            "safe_code": receipt.safe_code if receipt else None,
            "status_url": f"/api/commands/{command_id}",
        }
    raise HTTPException(404, "command_not_found")
