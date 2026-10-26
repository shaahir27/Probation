"""GET /api/readiness: honest liveness and role readiness for the private dashboard.

Rules: this route only reads. It never migrates, never starts a runtime, never calls a provider,
and never reports a role online because configuration exists. The supervisor document is the only
source of role state; without it everything is unavailable.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.api.readiness_models import ReadinessResponse, simulated_projection
from probation.config import settings
from probation.core.clock import get_clock, operational_clock
from probation.core.runtime_status import SUPERVISED_ROLES, read_runtime_status, runtime_status_path

router = APIRouter(prefix="/api", tags=["readiness"], dependencies=[Depends(require_owner)])


@router.get("/readiness", response_model=ReadinessResponse)
def get_readiness(owner: Annotated[OwnerContext, Depends(require_owner)]) -> dict[str, Any]:
    """Supervisor-reported role readiness plus the durable replay projection for this owner."""
    payload = read_runtime_status(
        runtime_status_path(settings.db_path),
        now=operational_clock().now(),
        clock_mode=settings.clock_mode,
        role_names=SUPERVISED_ROLES,
    )
    if not settings.db_path.is_file():
        payload["replay"] = {"available": False, "running": False, "reason": "database_absent"}
        return payload
    conn = get_connection(settings.db_path)
    try:
        payload["replay"] = simulated_projection(
            conn,
            owner_id=owner.owner_id,
            target=settings.db_path,
            now_iso=get_clock().now_iso(),
        )
    except HTTPException:
        raise
    finally:
        conn.close()
    return payload
