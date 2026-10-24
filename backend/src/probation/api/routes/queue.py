"""Queue endpoints per CONTRACT.md section 9.

Authority: CONTRACT.md section 3, section 8, section 9.
Note: API writes strictly to user_responses table only using Role.API.
"""

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from probation.api.db import connect_api as get_connection
from probation.config import settings
from probation.core.enums import GateDecision

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
            ORDER BY p.proposed_at COLLATE UTC_TIMESTAMP ASC;
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
