"""Owner-scoped replay intent submission and durable read-only state.

Frozen wire contract (docs/wp9/D6_API_CONTRACT.md):

* `POST /api/replay/{start|pause}` body `{"request_id": str}` -> 202
* `POST /api/replay/speed` body `{"request_id": str, "speed": 1|10|100}` -> 202
* both respond `{"ok", "request_id", "status": "accepted", "status_url", "existing"}`
* `GET /api/replay/state` -> `{"running", "speed", "simulated_date", "mode", "available",
  "last_request_id"?}` plus the honest resume markers

Unknown fields are refused, non-finite speeds are refused, and no body may name a workspace,
run or database: scope is derived only from trusted server configuration. This route submits
intents and reads durable receipts; it never advances replay.
"""

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from probation.api.authority import OwnerContext, require_owner
from probation.api.routes.queue import _get_db
from probation.config import settings
from probation.core.clock import Clock, get_clock
from probation.core.lifecycle import LifecycleConflict
from probation.core.replay_controls import REPLAY_SPEEDS, ReplayCommandIntent, server_replay_scope
from probation.db.access import Role, RoleAccess
from probation.db.replay_commands import ReplayCommandStore
from probation.engine.replay_kernel import open_decision_count, project_replay_state

router = APIRouter(prefix="/api", tags=["replay"])
Owner = Annotated[OwnerContext, Depends(require_owner)]

_REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"


def _safe_identifier(value: str) -> str:
    if ".." in value or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError("request_id must not contain a path or traversal token")
    return value


class ReplayControlBody(BaseModel):
    """The only field a replay control may carry, closed against everything else."""

    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=1, max_length=160, pattern=_REQUEST_ID_PATTERN)

    @field_validator("request_id")
    @classmethod
    def no_traversal(cls, value: str) -> str:
        return _safe_identifier(value)


class ReplaySpeedBody(ReplayControlBody):
    speed: int

    @field_validator("speed")
    @classmethod
    def supported_speed(cls, value: int) -> int:
        if isinstance(value, bool) or value not in REPLAY_SPEEDS:
            raise ValueError("speed must be one of the supported multipliers")
        return value


def _read_state(conn: sqlite3.Connection, owner: OwnerContext) -> dict[str, object]:
    scope = server_replay_scope(owner.owner_id, settings.db_path.resolve())
    checkpoint = ReplayCommandStore(RoleAccess(conn, Role.API)).checkpoint(
        workspace_id=scope.workspace_id, run_id=scope.run_id
    )
    # Operational time is real process time; the simulated instant is only ever projected from
    # the durable checkpoint. With no checkpoint the surface reports the application clock.
    operational_at = Clock.live().now_iso()
    default_simulated_at = get_clock().now_iso()
    anchor = checkpoint.get("simulated_at") if isinstance(checkpoint, dict) else None
    decisions = open_decision_count(
        conn, simulated_at=str(anchor or default_simulated_at), limit=20
    )
    return project_replay_state(
        checkpoint,
        operational_at=operational_at,
        default_simulated_at=default_simulated_at,
        mode=settings.clock_mode,
        open_decisions=decisions,
    ).as_state_document()


@router.get("/replay/state")
def get_replay_state(owner: Owner) -> dict[str, object]:
    conn = _get_db()
    try:
        return _read_state(conn, owner)
    finally:
        conn.close()


def _submit(
    command_type: Literal["replay_start", "replay_pause", "replay_speed"],
    body: ReplayControlBody,
    owner: OwnerContext,
) -> dict[str, object]:
    conn = _get_db()
    try:
        intent = ReplayCommandIntent(
            request_id=body.request_id,
            owner_id=owner.owner_id,
            type=command_type,
            scope=server_replay_scope(owner.owner_id, settings.db_path.resolve()),
            speed=body.speed if isinstance(body, ReplaySpeedBody) else None,
            created_at=Clock.live().now_iso(),
        )
        result = ReplayCommandStore(RoleAccess(conn, Role.API)).submit(intent)
        return {
            "ok": True,
            "request_id": result.request_id,
            "status": "accepted",
            "status_url": f"/api/commands/{result.request_id}",
            "existing": result.existing,
        }
    except (LifecycleConflict, ValueError) as exc:
        code = getattr(exc, "code", "invalid_replay_command")
        raise HTTPException(409 if isinstance(exc, LifecycleConflict) else 422, code) from exc
    finally:
        conn.close()


@router.post("/replay/start", status_code=202)
def start_replay(body: ReplayControlBody, owner: Owner) -> dict[str, object]:
    return _submit("replay_start", body, owner)


@router.post("/replay/pause", status_code=202)
def pause_replay(body: ReplayControlBody, owner: Owner) -> dict[str, object]:
    return _submit("replay_pause", body, owner)


@router.post("/replay/speed", status_code=202)
def set_replay_speed(body: ReplaySpeedBody, owner: Owner) -> dict[str, object]:
    return _submit("replay_speed", body, owner)
