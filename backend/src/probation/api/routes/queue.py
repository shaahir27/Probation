"""Queue endpoints per CONTRACT.md section 9.

Authority: CONTRACT.md section 3, section 8, section 9.
Note: API writes strictly to user_responses table only using Role.API.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from probation.config import settings
from probation.core.enums import GateDecision
from probation.db.access import Role, get_role_access
from probation.db.connection import get_connection

router = APIRouter(prefix="/api", tags=["queue"])


class QueueRespondBody(BaseModel):
    response: Literal["accept", "reject", "edit"] = Field(
        ..., description="User response: accept, reject, or edit"
    )
    edited_action: str | None = Field(
        default=None, description="Action chosen by user if response is edit"
    )


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/queue")
def get_queue() -> dict[str, Any]:
    """Items needing the user (ASK, SUGGEST), grouped into a digest by class_key and proposed action."""
    if not settings.db_path.exists():
        return {"items": [], "digests": [], "total_count": 0}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        # Find proposals whose gate is ASK or SUGGEST that haven't been responded to yet
        cursor.execute(
            """
            SELECT p.id, p.situation_id, p.family, p.class_key, p.action, p.probs_json,
                   p.p_max, p.novelty, p.licence_level, p.cap, p.gate, p.reasons_json,
                   p.params_json, p.explanation_json, p.web_json, p.audit_holdout, p.proposed_at,
                   s.sender_key, s.occurred_at, s.redacted_text,
                   d.body_text AS draft_body, d.needs_user_input AS draft_needs_input
            FROM proposals p
            JOIN situations s ON p.situation_id = s.id
            LEFT JOIN drafts d ON p.id = d.proposal_id
            LEFT JOIN user_responses ur ON p.id = ur.proposal_id
            WHERE p.gate IN (?, ?)
              AND ur.id IS NULL
            ORDER BY p.proposed_at ASC;
            """,
            (GateDecision.ASK.value, GateDecision.SUGGEST.value),
        )
        rows = cursor.fetchall()

        items = []
        digests_map: dict[str, dict[str, Any]] = {}

        for r in rows:
            probs = json.loads(r["probs_json"]) if r["probs_json"] else {}
            params = json.loads(r["params_json"]) if r["params_json"] else {}
            explanation = json.loads(r["explanation_json"]) if r["explanation_json"] else {}
            web = json.loads(r["web_json"]) if r["web_json"] else {}
            reasons = json.loads(r["reasons_json"]) if r["reasons_json"] else []

            item = {
                "id": r["id"],
                "situation_id": r["situation_id"],
                "family": r["family"],
                "class_key": r["class_key"],
                "action": r["action"],
                "probs": probs,
                "p_max": r["p_max"],
                "novelty": r["novelty"],
                "licence_level": r["licence_level"],
                "cap": r["cap"],
                "gate": r["gate"],
                "reasons": reasons,
                "params": params,
                "explanation": explanation,
                "web": web,
                "audit_holdout": bool(r["audit_holdout"]),
                "proposed_at": r["proposed_at"],
                "sender_key": r["sender_key"],
                "occurred_at": r["occurred_at"],
                "summary": r["redacted_text"],
                "draft": (
                    {
                        "body_text": r["draft_body"],
                        "needs_user_input": bool(r["draft_needs_input"]),
                    }
                    if r["draft_body"] is not None
                    else None
                ),
            }
            items.append(item)

            digest_key = f"{r['class_key']}|{r['action']}"
            if digest_key not in digests_map:
                digests_map[digest_key] = {
                    "class_key": r["class_key"],
                    "action": r["action"],
                    "family": r["family"],
                    "count": 0,
                    "ask_count": 0,
                    "suggest_count": 0,
                    "items": [],
                }
            digests_map[digest_key]["count"] += 1
            if r["gate"] == GateDecision.ASK.value:
                digests_map[digest_key]["ask_count"] += 1
            else:
                digests_map[digest_key]["suggest_count"] += 1
            digests_map[digest_key]["items"].append(r["id"])

        return {
            "items": items,
            "digests": list(digests_map.values()),
            "total_count": len(items),
        }
    finally:
        conn.close()


@router.post("/queue/{proposal_id}/respond")
def respond_queue(proposal_id: str, body: QueueRespondBody) -> dict[str, Any]:
    """Record a user response to a pending queue proposal.

    Authority: CONTRACT.md section 3 & 8. API writes strictly to user_responses.
    """
    conn = _get_db()
    try:
        cursor = conn.cursor()
        # Verify proposal exists
        cursor.execute("SELECT id FROM proposals WHERE id = ?;", (proposal_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found")

        # Check if already answered
        cursor.execute(
            "SELECT id, response FROM user_responses WHERE proposal_id = ?;", (proposal_id,)
        )
        existing = cursor.fetchone()
        if existing:
            return {
                "ok": False,
                "message": "Already answered",
                "id": existing["id"],
                "response": existing["response"],
            }

        if body.response == "edit" and not body.edited_action:
            raise HTTPException(
                status_code=422, detail="edited_action required when response is 'edit'"
            )

        resp_id = f"resp-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Strictly use RoleAccess with Role.API (permits user_responses only)
        role_access = get_role_access(conn, Role.API)
        role_access.execute_write(
            "user_responses",
            """
            INSERT INTO user_responses (id, proposal_id, action_id, response, edited_action, responded_at)
            VALUES (?, ?, NULL, ?, ?, ?);
            """,
            (resp_id, proposal_id, body.response, body.edited_action, now_iso),
        )
        role_access.commit()

        return {
            "ok": True,
            "id": resp_id,
            "proposal_id": proposal_id,
            "response": body.response,
            "edited_action": body.edited_action,
            "responded_at": now_iso,
        }
    finally:
        conn.close()
