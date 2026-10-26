"""Strict readiness response models for the private API surface.

``core.runtime_status`` owns the cross-process document; this module owns only what the browser
may see: the validated envelope plus the durable replay projection the home screen reads.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from probation.core.clock import format_timestamp, parse_timestamp


class RoleReadinessView(BaseModel):
    """One role as supervision reported it. Absence is a state, never a default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    state: str
    ready: bool
    code: str | None = None
    last_tick_at: str | None = None


class ReadinessResponse(BaseModel):
    """API liveness and role readiness are separate claims and must never be merged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    reason: str | None = None
    clock_mode: str
    api_live: bool
    generated_at: str | None = None
    stale: bool
    age_seconds: float | None = None
    roles: list[RoleReadinessView] = Field(default_factory=list)
    replay: dict[str, Any] | None = None


class ReplayProjection(BaseModel):
    """Durable replay state read from the Examiner checkpoint, never from process memory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    running: bool
    available: bool
    simulated_date: str | None = None
    speed: int = 1
    last_request_id: str | None = None


def simulated_projection(
    conn: sqlite3.Connection, *, owner_id: str, target: Path, now_iso: str
) -> dict[str, Any]:
    """Project simulated time from the durable checkpoint; operational time drives the advance."""
    from probation.core.replay_controls import ReplayScope
    from probation.db.access import Role, RoleAccess
    from probation.db.replay_commands import ReplayCommandStore

    scope = ReplayScope.for_owner(owner_id=owner_id, target=str(Path(target).resolve()))
    checkpoint = ReplayCommandStore(RoleAccess(conn, Role.API)).checkpoint(
        workspace_id=scope.workspace_id, run_id=scope.run_id
    )
    if checkpoint is None:
        return {"running": False, "available": True, "simulated_date": None, "speed": 1}
    running = bool(checkpoint.get("running", False))
    simulated = checkpoint.get("simulated_at")
    speed = int(checkpoint.get("speed", 1) or 1)
    if running and isinstance(simulated, str) and isinstance(checkpoint.get("operational_at"), str):
        elapsed = (
            parse_timestamp(now_iso) - parse_timestamp(str(checkpoint["operational_at"]))
        ).total_seconds()
        if elapsed < 0:
            return {
                "running": running,
                "available": False,
                "simulated_date": simulated,
                "speed": speed,
            }
        simulated = format_timestamp(
            parse_timestamp(simulated) + timedelta(seconds=elapsed * speed)
        )
    return {
        "running": running,
        "available": bool(checkpoint.get("available", True)),
        "simulated_date": simulated,
        "speed": speed,
        "last_request_id": checkpoint.get("last_request_id"),
    }
