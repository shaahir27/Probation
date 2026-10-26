"""Item detail explanation endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /items/{proposal_id}:
Everything needed to explain one item: situation summary, proposal, evidence line for its (class_key, action),
explanation (top clues, similar past cases), web status and sources (if checked) and the draft if any.
"""

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.api.routes import gmail_connector
from probation.config import settings
from probation.engine.caps import get_action_cap
from probation.llm.draft_validation import body_hash
from probation.web.types import VerificationCard

router = APIRouter(prefix="/api", tags=["items"], dependencies=[Depends(require_owner)])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


def _write_capabilities(owner: OwnerContext, source_id: str) -> set[str]:
    grant = next((item for item in owner.grants if item.source_id == source_id), None)
    if grant is None:
        return set()
    try:
        config = gmail_connector.current_config()
        access = gmail_connector._api_access(config.store_path)
    except HTTPException:
        return set()
    try:
        connection = access.one(
            "SELECT state FROM gmail_connections WHERE owner_id=? AND connection_id=?",
            (owner.owner_id, grant.connection_id),
        )
        if connection is None or str(connection["state"]) != "ACTIVE":
            return set()
        return {
            str(row["name"])
            for row in gmail_connector._capability_rows(access, grant.connection_id)
            if str(row["owner_role"]) == "write" and bool(row["supported"])
        }
    except sqlite3.Error:
        return set()
    finally:
        access.conn.close()


def _supported_actions(row: sqlite3.Row, owner: OwnerContext) -> list[str]:
    if row["family"] != "email_action":
        return []
    actions = ["LEAVE"]
    capabilities = _write_capabilities(owner, str(row["source_id"]))
    if "archive" in capabilities and get_action_cap("ARCHIVE", family="email_action") > 0:
        actions.insert(0, "ARCHIVE")
    if "trash" in capabilities and get_action_cap("TRASH", family="email_action") > 0:
        actions.insert(1 if "ARCHIVE" in actions else 0, "TRASH")

    try:
        params = json.loads(row["params_json"]) if row["params_json"] else {}
        raw_payload = json.loads(row["raw_payload_json"]) if row["raw_payload_json"] else {}
    except (TypeError, ValueError):
        params, raw_payload = {}, {}
    draft_is_bound = (
        row["draft_body"] is not None
        and bool(row["draft_validator_ok"])
        and not bool(row["draft_needs_input"])
        and params.get("draft_proposal_id") == row["id"]
        and params.get("draft_body_hash") == body_hash(str(row["draft_body"]))
        and bool(params.get("to_addr"))
    )
    if "send" in capabilities and draft_is_bound:
        actions.append("REPLY")

    has_attachments = bool(
        raw_payload.get("attachments")
        or raw_payload.get("has_attachments")
        or raw_payload.get("has_attachment")
    )
    if "forward" in capabilities and owner.forward_recipients and not has_attachments:
        actions.append("FORWARD")
    return actions


@router.get("/items/{proposal_id}")
def get_item_detail(
    proposal_id: str, owner: Annotated[OwnerContext, Depends(require_owner)]
) -> dict[str, Any]:
    """Retrieve full explanation context for a single proposal."""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.id, p.situation_id, p.family, p.class_key, p.action, p.probs_json,
                   p.p_max, p.novelty, p.licence_level, p.cap, p.gate, p.reasons_json,
                   p.params_json, p.explanation_json, p.web_json, p.audit_holdout, p.proposed_at,
                   s.sender_key, s.occurred_at, s.redacted_text,s.raw_item_id,r.source_id,
                   r.payload_json AS raw_payload_json,
                   d.body_text AS draft_body, d.needs_user_input AS draft_needs_input,
                   d.validator_ok AS draft_validator_ok,
                   d.model_id AS draft_model_id,
                   ur.response AS user_response, ur.edited_action, ur.responded_at
            FROM proposals p
            JOIN situations s ON p.situation_id = s.id
            JOIN raw_items r ON r.id=s.raw_item_id
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
            raise HTTPException(status_code=404, detail="item_not_found")
        if not any(grant.source_id == row["source_id"] for grant in owner.grants):
            raise HTTPException(status_code=404, detail="item_not_found")

        probs = json.loads(row["probs_json"]) if row["probs_json"] else {}
        params = json.loads(row["params_json"]) if row["params_json"] else {}
        explanation = json.loads(row["explanation_json"]) if row["explanation_json"] else {}
        web = json.loads(row["web_json"]) if row["web_json"] else {}
        reasons = json.loads(row["reasons_json"]) if row["reasons_json"] else []
        card_data = web.get("verification_card")
        try:
            validated_card = VerificationCard.model_validate(card_data) if card_data else None
            if validated_card and validated_card.fetched_at:
                from probation.core.clock import timestamp_key

                if timestamp_key(validated_card.fetched_at) > timestamp_key(
                    web.get("decision_cutoff", row["proposed_at"])
                ):
                    raise ValueError("Verification postdates decision")
            card = validated_card.model_dump() if validated_card else None
        except (ValidationError, ValueError):
            card = VerificationCard(
                availability="unavailable", reasons=["stored_verification_invalid"]
            ).model_dump()

        from probation.core.clock import get_clock
        from probation.engine.licence import derive_licences

        now = get_clock().now_iso()
        from probation.web.view import WebFactsView

        current_web = WebFactsView(conn).get_entity_facts(str(row["sender_key"] or ""), now)
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
        supported_actions = _supported_actions(row, owner)

        return {
            "proposal_id": row["id"],
            "review_version": "v2",
            "review_url": f"/api/queue/{row['id']}/review",
            "supported_actions": supported_actions,
            "readiness": {
                "reply_draft_available": "REPLY" in supported_actions,
                "reply_needs_user_input": bool(row["draft_needs_input"]),
                "forward_requires_controlled_recipient": "FORWARD" in supported_actions,
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
            "verification_version": "d5.v1",
            "verification_card": card,
            "verification_as_of": web.get("decision_cutoff", row["proposed_at"]),
            "current_sender_verification": current_web.model_dump() if current_web else None,
            "current_verification_as_of": now,
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
