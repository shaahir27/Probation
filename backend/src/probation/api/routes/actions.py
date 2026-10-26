"""Actions endpoints per CONTRACT.md section 8 and 9.

Authority: CONTRACT.md section 8, section 9.
Note: API writes strictly to user_responses with response='undo' using Role.API.
Action execution and undos are performed by the Executor worker.
Contract ActionStatus enum: PENDING | HELD | DONE | UNDONE | CANCELLED | FAILED.
"""

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.config import settings
from probation.core.clock import get_clock, parse_timestamp

router = APIRouter(prefix="/api", tags=["actions"], dependencies=[Depends(require_owner)])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/actions")
def get_actions(owner: Annotated[OwnerContext, Depends(require_owner)]) -> dict[str, Any]:
    """Executed and held actions per CONTRACT.md section 9."""
    if not settings.db_path.exists():
        return {"actions": [], "total_count": 0}

    conn = _get_db()
    try:
        allowed_sources = tuple(grant.source_id for grant in owner.grants)
        if not allowed_sources:
            return {"actions": [], "total_count": 0}
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.id, a.proposal_id, a.pack, a.type, a.params_json, a.level_required,
                   a.recallable, a.status, a.hold_until, a.undo_json, a.created_at,
                   a.updated_at, a.executed_at,
                   a.binding_json,a.undo_deadline,
                   p.class_key, p.family, s.redacted_text AS summary
            FROM actions a
            LEFT JOIN proposals p ON a.proposal_id = p.id
            LEFT JOIN situations s ON p.situation_id = s.id
            LEFT JOIN raw_items r ON r.id=s.raw_item_id
            WHERE r.source_id IN ({})
            ORDER BY a.created_at COLLATE UTC_TIMESTAMP DESC;
            """.format(",".join("?" for _ in allowed_sources)),
            allowed_sources,
        )
        rows = cursor.fetchall()

        actions = []
        for r in rows:
            params = json.loads(r["params_json"]) if r["params_json"] else {}
            undo = json.loads(r["undo_json"]) if r["undo_json"] else None
            attempt = conn.execute(
                "SELECT state FROM execution_attempts WHERE action_id=? AND operation='execute'",
                (r["id"],),
            ).fetchone()
            unresolved = bool(attempt and attempt[0] in {"unknown", "dispatched"})
            undo_available = bool(
                r["binding_json"]
                and not unresolved
                and (
                    r["status"] == "HELD"
                    or (
                        r["status"] == "DONE"
                        and r["recallable"]
                        and r["undo_deadline"]
                        and parse_timestamp(get_clock().now_iso())
                        <= parse_timestamp(r["undo_deadline"])
                    )
                )
            )
            actions.append(
                {
                    "id": r["id"],
                    "proposal_id": r["proposal_id"],
                    "pack": r["pack"],
                    "type": r["type"],
                    "params": params,
                    "level_required": r["level_required"],
                    "recallable": bool(r["recallable"]),
                    "status": r["status"],  # PENDING, HELD, DONE, UNDONE, CANCELLED, FAILED
                    "hold_until": r["hold_until"],
                    "undo": undo,
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "executed_at": r["executed_at"],
                    "class_key": r["class_key"],
                    "family": r["family"],
                    "summary": r["summary"],
                    "execution_status": "needs-reconciliation"
                    if unresolved
                    else r["status"].lower(),
                    "undo_available": undo_available,
                    "undo_deadline": r["undo_deadline"],
                }
            )

        return {"actions": actions, "total_count": len(actions)}
    finally:
        conn.close()
