"""Actions endpoints per CONTRACT.md section 8 and 9.

Authority: CONTRACT.md section 8, section 9.
Note: API writes strictly to user_responses with response='undo' using Role.API.
Action execution and undos are performed by the Executor worker.
Contract ActionStatus enum: PENDING | HELD | DONE | UNDONE | CANCELLED | FAILED.
"""

import json
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from probation.api.event_time import response_time
from probation.config import settings
from probation.db.access import Role, get_role_access
from probation.db.connection import get_connection

router = APIRouter(prefix="/api", tags=["actions"])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/actions")
def get_actions() -> dict[str, Any]:
    """Executed and held actions per CONTRACT.md section 9."""
    if not settings.db_path.exists():
        return {"actions": [], "total_count": 0}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.id, a.proposal_id, a.pack, a.type, a.params_json, a.level_required,
                   a.recallable, a.status, a.hold_until, a.undo_json, a.created_at,
                   a.updated_at, a.executed_at,
                   p.class_key, p.family, s.redacted_text AS summary
            FROM actions a
            LEFT JOIN proposals p ON a.proposal_id = p.id
            LEFT JOIN situations s ON p.situation_id = s.id
            ORDER BY a.created_at COLLATE UTC_TIMESTAMP DESC;
            """
        )
        rows = cursor.fetchall()

        actions = []
        for r in rows:
            params = json.loads(r["params_json"]) if r["params_json"] else {}
            undo = json.loads(r["undo_json"]) if r["undo_json"] else None
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
                }
            )

        return {"actions": actions, "total_count": len(actions)}
    finally:
        conn.close()


@router.post("/actions/{action_id}/undo")
def request_undo(action_id: str) -> dict[str, Any]:
    """Request an undo for an action.

    Authority: CONTRACT.md section 8 and section 9:
    'POST /actions/{id}/undo: Request an undo (writes a user_responses row; the Executor performs it and records the outcome)'
    """
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT a.id, a.proposal_id, a.status, a.recallable, a.created_at, p.proposed_at "
            "FROM actions a JOIN proposals p ON p.id=a.proposal_id WHERE a.id = ?;",
            (action_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")

        # Verify action is in a recallable/cancellable state
        if row["status"] not in ("HELD", "DONE"):
            raise HTTPException(
                status_code=400,
                detail=f"Action '{action_id}' status is '{row['status']}', cannot undo or cancel.",
            )

        if row["status"] == "DONE" and not row["recallable"]:
            raise HTTPException(
                status_code=400,
                detail=f"Action '{action_id}' is non-recallable.",
            )

        resp_id = f"resp-undo-{uuid.uuid4().hex[:12]}"
        now_iso = response_time(str(row["proposed_at"]), created_at=str(row["created_at"]))

        # Write strictly to user_responses using Role.API
        role_access = get_role_access(conn, Role.API)
        role_access.execute_write(
            "user_responses",
            """
            INSERT INTO user_responses (id, proposal_id, action_id, response, edited_action, responded_at)
            VALUES (?, ?, ?, 'undo', NULL, ?);
            """,
            (resp_id, row["proposal_id"], action_id, now_iso),
        )
        role_access.commit()

        return {
            "ok": True,
            "id": resp_id,
            "action_id": action_id,
            "proposal_id": row["proposal_id"],
            "response": "undo",
            "requested_at": now_iso,
            "status": "UNDO_REQUESTED",
        }
    finally:
        conn.close()
