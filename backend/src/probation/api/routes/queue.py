"""Queue endpoints per CONTRACT.md section 9.

Authority: CONTRACT.md section 3, section 8, section 9.
Note: API writes strictly to user_responses table only using Role.API.
"""

import json
import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.config import settings
from probation.core.clock import get_clock, timestamp_key
from probation.core.enums import GateDecision

router = APIRouter(prefix="/api", tags=["queue"], dependencies=[Depends(require_owner)])


class QueueRespondBody(BaseModel):
    response: Literal["accept", "reject", "edit"] = Field(
        ..., description="User response: accept, reject, or edit"
    )
    edited_action: str | None = Field(
        default=None, description="Action chosen by user if response is edit"
    )


def _empty_queue() -> dict[str, Any]:
    return {
        "items": [],
        "digests": [],
        "total_count": 0,
        "handled_count": 0,
        "handled_digests": [],
        "expired_count": 0,
        "expired_digests": [],
    }


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/queue")
def get_queue(owner: Annotated[OwnerContext, Depends(require_owner)]) -> dict[str, Any]:
    """Waiting decisions only, plus grouped counts of already-handled and expired work.

    The cutoff is the API's event-time clock, not the wall clock, so Review, Permissions
    and Activity agree. An item with a known outcome is never waiting: a non-window_close
    outcome is a decision, while a window_close outcome is expired unanswered work.
    """
    if not settings.db_path.exists():
        return _empty_queue()
    # Capability is checked before the grant short-circuit: an old schema is unavailable,
    # never silently reported as an empty queue.
    conn = _get_db()
    allowed_sources = tuple(grant.source_id for grant in owner.grants)
    if not allowed_sources:
        conn.close()
        return _empty_queue()

    try:
        cursor = conn.cursor()
        as_of = get_clock().now_iso()
        placeholders = ",".join("?" for _ in allowed_sources)
        cursor.execute(
            f"""
            SELECT p.id, p.situation_id, p.family, p.class_key, p.action, p.probs_json,
                   p.p_max, p.novelty, p.licence_level, p.cap, p.gate, p.reasons_json,
                   p.params_json, p.explanation_json, p.web_json, p.audit_holdout, p.proposed_at,
                   s.sender_key, s.occurred_at, s.redacted_text,
                   d.body_text AS draft_body, d.needs_user_input AS draft_needs_input,
                   o.known_at AS outcome_known_at, o.source AS outcome_source,
                   ur.response_at AS response_at
            FROM proposals p
            JOIN situations s ON p.situation_id = s.id
            JOIN raw_items r ON r.id=s.raw_item_id
            LEFT JOIN drafts d ON p.id = d.proposal_id
            LEFT JOIN outcomes o ON o.situation_id = p.situation_id
                AND o.known_at COLLATE UTC_TIMESTAMP <= ?
            LEFT JOIN (
                SELECT proposal_id, MAX(responded_at) AS response_at
                FROM user_responses
                WHERE responded_at COLLATE UTC_TIMESTAMP <= ?
                GROUP BY proposal_id
            ) ur ON ur.proposal_id = p.id
            WHERE p.gate IN (?, ?)
              AND p.proposed_at COLLATE UTC_TIMESTAMP <= ?
              AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
              AND r.known_at COLLATE UTC_TIMESTAMP <= ?
              AND r.source_id IN ({placeholders})
            ORDER BY p.proposed_at COLLATE UTC_TIMESTAMP ASC;
            """,
            (
                as_of,
                as_of,
                GateDecision.ASK.value,
                GateDecision.SUGGEST.value,
                as_of,
                as_of,
                as_of,
                *allowed_sources,
            ),
        )
        rows = cursor.fetchall()

        items = []
        digests_map: dict[str, dict[str, Any]] = {}
        handled_map: dict[str, dict[str, Any]] = {}
        expired_map: dict[str, dict[str, Any]] = {}
        handled_count = 0
        expired_count = 0

        def _group(groups: dict[str, dict[str, Any]], row: Any, last_at: str) -> None:
            key = f"{row['class_key']}|{row['action']}"
            entry = groups.setdefault(
                key,
                {
                    "class_key": row["class_key"],
                    "action": row["action"],
                    "family": row["family"],
                    "count": 0,
                    "last_at": last_at,
                },
            )
            entry["count"] += 1
            if timestamp_key(last_at) > timestamp_key(str(entry["last_at"])):
                entry["last_at"] = last_at

        for r in rows:
            outcome_at = r["outcome_known_at"]
            response_at = r["response_at"]
            handled = response_at is not None or (
                outcome_at is not None and r["outcome_source"] != "window_close"
            )
            if handled:
                handled_count += 1
                _group(handled_map, r, str(response_at or outcome_at))
                continue
            if outcome_at is not None:
                expired_count += 1
                _group(expired_map, r, str(outcome_at))
                continue

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
            "handled_count": handled_count,
            "handled_digests": list(handled_map.values()),
            "expired_count": expired_count,
            "expired_digests": list(expired_map.values()),
        }
    finally:
        conn.close()


@router.get("/watching")
def get_watching(owner: Annotated[OwnerContext, Depends(require_owner)]) -> dict[str, Any]:
    """Return source-authorized shadow observations that do not ask the owner to decide."""
    if not settings.db_path.exists():
        return {"items": [], "total_count": 0}
    allowed_sources = tuple(grant.source_id for grant in owner.grants)
    if not allowed_sources:
        return {"items": [], "total_count": 0}

    as_of = get_clock().now_iso()
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT p.id,p.situation_id,p.family,p.class_key,p.action,p.probs_json,
                      p.p_max,p.novelty,p.licence_level,p.cap,p.gate,p.reasons_json,
                      p.params_json,p.explanation_json,p.web_json,p.audit_holdout,p.proposed_at,
                      s.sender_key,s.occurred_at,s.redacted_text,
                      d.body_text AS draft_body,d.needs_user_input AS draft_needs_input
               FROM proposals p JOIN situations s ON s.id=p.situation_id
               JOIN raw_items r ON r.id=s.raw_item_id
               LEFT JOIN drafts d ON d.proposal_id=p.id
               WHERE p.gate=? AND r.source_id IN ({})
                 AND p.proposed_at COLLATE UTC_TIMESTAMP<=?
                 AND s.occurred_at COLLATE UTC_TIMESTAMP<=?
                 AND r.known_at COLLATE UTC_TIMESTAMP<=?
               ORDER BY p.proposed_at COLLATE UTC_TIMESTAMP ASC""".format(
                ",".join("?" for _ in allowed_sources)
            ),
            (GateDecision.SHADOW.value, *allowed_sources, as_of, as_of, as_of),
        ).fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "id": row["id"],
                    "situation_id": row["situation_id"],
                    "family": row["family"],
                    "class_key": row["class_key"],
                    "action": row["action"],
                    "probs": json.loads(row["probs_json"]) if row["probs_json"] else {},
                    "p_max": row["p_max"],
                    "novelty": row["novelty"],
                    "licence_level": row["licence_level"],
                    "cap": row["cap"],
                    "gate": row["gate"],
                    "reasons": json.loads(row["reasons_json"]) if row["reasons_json"] else [],
                    "params": json.loads(row["params_json"]) if row["params_json"] else {},
                    "explanation": json.loads(row["explanation_json"])
                    if row["explanation_json"]
                    else {},
                    "web": json.loads(row["web_json"]) if row["web_json"] else {},
                    "audit_holdout": bool(row["audit_holdout"]),
                    "proposed_at": row["proposed_at"],
                    "sender_key": row["sender_key"],
                    "occurred_at": row["occurred_at"],
                    "summary": row["redacted_text"],
                    "draft": None
                    if row["draft_body"] is None
                    else {
                        "body_text": row["draft_body"],
                        "needs_user_input": bool(row["draft_needs_input"]),
                    },
                }
            )
        return {"items": items, "total_count": len(items)}
    finally:
        conn.close()
