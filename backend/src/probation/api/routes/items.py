"""Item detail explanation endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /items/{proposal_id}:
Everything needed to explain one item: situation summary, proposal, evidence line for its (class_key, action),
explanation (top clues, similar past cases), web status and sources (if checked) and the draft if any.
"""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from probation.api.db import connect_api as get_connection
from probation.config import settings

router = APIRouter(prefix="/api", tags=["items"])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/items/{proposal_id}")
def get_item_detail(proposal_id: str) -> dict[str, Any]:
    """Retrieve full explanation context for a single proposal."""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.id, p.situation_id, p.family, p.class_key, p.action, p.probs_json,
                   p.p_max, p.novelty, p.licence_level, p.cap, p.gate, p.reasons_json,
                   p.params_json, p.explanation_json, p.web_json, p.audit_holdout, p.proposed_at,
                   s.sender_key, s.occurred_at, s.redacted_text,s.raw_item_id,
                   d.body_text AS draft_body, d.needs_user_input AS draft_needs_input,
                   d.model_id AS draft_model_id,
                   ur.response AS user_response, ur.edited_action, ur.responded_at
            FROM proposals p
            JOIN situations s ON p.situation_id = s.id
            LEFT JOIN drafts d ON p.id = d.proposal_id
            LEFT JOIN user_responses ur ON ur.id=(SELECT u.id FROM user_responses u
                WHERE u.proposal_id=p.id AND u.response IN('accept','reject','edit')
                ORDER BY u.responded_at COLLATE UTC_TIMESTAMP,u.id LIMIT 1)
            WHERE p.id = ?;
            """,
            (proposal_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Item '{proposal_id}' not found")

        probs = json.loads(row["probs_json"]) if row["probs_json"] else {}
        params = json.loads(row["params_json"]) if row["params_json"] else {}
        explanation = json.loads(row["explanation_json"]) if row["explanation_json"] else {}
        web = json.loads(row["web_json"]) if row["web_json"] else {}
        reasons = json.loads(row["reasons_json"]) if row["reasons_json"] else []

        from probation.core.clock import get_clock
        from probation.engine.licence import derive_licences

        now = get_clock().now_iso()
        view = derive_licences(conn, now, pair=(row["class_key"], row["action"]))[
            (row["class_key"], row["action"])
        ]
        evidence_line = {
            "n_strong": view.n_strong,
            "k_strong": view.k_strong,
            "n_all": view.n_all,
            "k_all": view.k_all,
            "n_recent": view.n_recent,
            "lb_strong": view.lb_strong,
            "lb_all": view.lb_all,
            "as_of": now,
        }
        licence_info = {
            "level": int(view.level),
            "lower_bound": view.lower_bound,
            "reasons": view.reasons,
            "valid_until": view.valid_until,
        }

        return {
            "proposal_id": row["id"],
            "review_version": "v2",
            "review_url": f"/api/queue/{row['id']}/review",
            "supported_actions": ["ARCHIVE", "TRASH", "LEAVE", "REPLY", "FORWARD"]
            if row["family"] == "email_action"
            else [],
            "readiness": {
                "reply_draft_available": row["draft_body"] is not None,
                "reply_needs_user_input": bool(row["draft_needs_input"]),
                "forward_requires_controlled_recipient": True,
            },
            "source_identity": {"raw_item_id": row["raw_item_id"]},
            "situation_id": row["situation_id"],
            "family": row["family"],
            "class_key": row["class_key"],
            "action": row["action"],
            "probs": probs,
            "p_max": row["p_max"],
            "novelty": row["novelty"],
            "licence_level": row["licence_level"],
            "cap": row["cap"],
            "gate": row["gate"],
            "reasons": reasons,
            "params": params,
            "audit_holdout": bool(row["audit_holdout"]),
            "proposed_at": row["proposed_at"],
            "situation": {
                "sender_key": row["sender_key"],
                "occurred_at": row["occurred_at"],
                "summary": row["redacted_text"],
            },
            "explanation": {
                "top_clues": explanation.get("top_clues", []),
                "similar_cases": explanation.get("similar_cases", []),
                "summary_reason": explanation.get("summary_reason", ""),
            },
            "web_status": {
                "status": web.get("status", "not_checked"),
                "cap": web.get("cap"),
                "sources": web.get("source_ids", []),
            },
            "draft": (
                {
                    "body_text": row["draft_body"],
                    "needs_user_input": bool(row["draft_needs_input"]),
                    "model_id": row["draft_model_id"],
                }
                if row["draft_body"] is not None
                else None
            ),
            "evidence": evidence_line,
            "licence": licence_info,
            "user_response": (
                {
                    "response": row["user_response"],
                    "edited_action": row["edited_action"],
                    "responded_at": row["responded_at"],
                }
                if row["user_response"] is not None
                else None
            ),
        }
    finally:
        conn.close()
