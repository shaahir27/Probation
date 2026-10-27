"""Immutable reviewed intents and truthful asynchronous processing status."""

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from probation.api.authority import OwnerContext, require_owner
from probation.api.event_time import response_time
from probation.api.review_models import RespondBody, ReviewBody, UndoBody
from probation.api.routes.queue import _get_db
from probation.core.clock import get_clock
from probation.core.lifecycle import ApprovalBinding, LifecycleError, ResponseIntent, binding_hash
from probation.core.review_binding import build_review_binding
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_receipts import ReceiptStore
from probation.db.lifecycle_responses import ResponseStore
from probation.llm.draft_validation import DraftInvalid
from probation.workers.restrictions import restrictions_for

router = APIRouter(prefix="/api", tags=["responses"])
Owner = Annotated[OwnerContext, Depends(require_owner)]


def reviewed(
    conn: sqlite3.Connection, proposal_id: str, body: ReviewBody, owner: OwnerContext
) -> Any:
    row = conn.execute(
        """SELECT r.source_id,p.proposed_at,p.class_key FROM proposals p
        JOIN situations s ON s.id=p.situation_id JOIN raw_items r ON r.id=s.raw_item_id WHERE p.id=?""",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "proposal_not_found")
    grant = owner.grant_for(row["source_id"])
    binding = build_review_binding(
        conn,
        proposal_id,
        grant=grant,
        owner_id=owner.owner_id,
        restriction_revision="0",
        as_of=get_clock().now_iso(),
        response=body.response,
        edited_action=body.edited_action,
        edited_body=body.edited_body,
        forward_recipient=body.forward_recipient,
        allowed_forward_recipients=owner.forward_recipients,
    )
    restriction = restrictions_for(
        conn,
        owner_id=owner.owner_id,
        connection_id=grant.connection_id,
        account_id=grant.account_id,
        resource_id=binding.resource_id,
        class_key=row["class_key"],
        action=binding.action,
        as_of=get_clock().now_iso(),
        authorized_at=grant.authorized_at,
    )
    if restriction.blocked and body.response not in {"reject", "leave"}:
        raise HTTPException(409, "operation_restricted")
    binding = binding.model_copy(update={"restriction_revision": restriction.revision})
    return binding


@router.post("/queue/{proposal_id}/review")
def review(proposal_id: str, body: ReviewBody, owner: Owner) -> dict[str, Any]:
    conn = _get_db()
    try:
        binding = reviewed(conn, proposal_id, body, owner)
        return {
            "version": "v2",
            "proposal_id": proposal_id,
            "reviewed_payload": binding.model_dump(),
            "reviewed_payload_hash": binding_hash(binding),
        }
    except (DraftInvalid, ValueError, TypeError) as exc:
        raise HTTPException(
            422, str(exc) if isinstance(exc, DraftInvalid) else "invalid_review"
        ) from exc
    finally:
        conn.close()


@router.post("/queue/{proposal_id}/respond", status_code=202)
def respond(proposal_id: str, body: RespondBody, owner: Owner) -> dict[str, Any]:
    conn = _get_db()
    try:
        proposed = conn.execute(
            "SELECT proposed_at FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        if proposed is None:
            raise HTTPException(404, "proposal_not_found")
        responded_at = response_time(proposed[0])
        binding = reviewed(conn, proposal_id, body, owner)
        if binding_hash(binding) != body.reviewed_payload_hash:
            raise HTTPException(409, "review_binding_changed")
        response = "edit" if body.response == "leave" else body.response
        intent = ResponseIntent(
            request_id=body.request_id,
            proposal_id=proposal_id,
            response=response,
            owner_id=owner.owner_id,
            responded_at=responded_at,
            reviewed_payload=binding,
            reviewed_payload_hash=body.reviewed_payload_hash,
            edited_action=binding.action if response == "edit" else None,
        )
        result = ResponseStore(RoleAccess(conn, Role.API)).submit(intent)
        return {
            "ok": True,
            "response": response,
            "request_id": result.request_id,
            "id": result.request_id,
            "status": "recorded",
            "status_url": f"/api/responses/{result.request_id}",
        }
    except LifecycleError as exc:
        raise HTTPException(409, exc.code) from exc
    except DraftInvalid as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        conn.close()


def response_status(
    conn: sqlite3.Connection, request_id: str, owner: OwnerContext
) -> dict[str, Any]:
    access = RoleAccess(conn, Role.API)
    intent = ResponseStore(access).get(request_id)
    if intent is None or intent.owner_id != owner.owner_id:
        raise HTTPException(404, "response_not_found")
    receipts = ReceiptStore(access)
    decision = receipts.get_response(request_id, "resolver")
    execution = receipts.get_response(request_id, "executor")
    decision_status = (
        "not_required" if intent.response == "undo" else decision.state if decision else "pending"
    )
    execution_status = (
        "not_required"
        if intent.response == "reject" or intent.reviewed_payload.action == "LEAVE"
        else "pending"
    )
    action_id = (execution.result or {}).get("action_id") if execution else None
    if execution and execution.state == "failed":
        execution_status = "failed"
    if action_id:
        action = conn.execute("SELECT status FROM actions WHERE id=?", (action_id,)).fetchone()
        if action:
            execution_status = {
                "DONE": "succeeded",
                "UNDONE": "undone",
                "FAILED": "failed",
                "CANCELLED": "cancelled",
            }.get(action[0], "pending")
            if intent.response == "undo" and action[0] == "DONE":
                execution_status = "pending"
        attempt = conn.execute(
            "SELECT state FROM execution_attempts WHERE action_id=? AND operation=?",
            (action_id, "undo" if intent.response == "undo" else "execute"),
        ).fetchone()
        if attempt and attempt[0] in {"unknown", "dispatched"}:
            execution_status = "needs-reconciliation"
        elif attempt and attempt[0] == "failed":
            execution_status = "failed"
    return {
        "request_id": request_id,
        "proposal_id": intent.proposal_id,
        "response": intent.response,
        "decision_status": decision_status,
        "execution_status": execution_status,
        "action_id": action_id,
    }


@router.get("/responses/{request_id}")
def get_response_status(request_id: str, owner: Owner) -> dict[str, Any]:
    conn = _get_db()
    try:
        return response_status(conn, request_id, owner)
    finally:
        conn.close()


@router.post("/actions/{action_id}/undo", status_code=202)
def undo(action_id: str, body: UndoBody, owner: Owner) -> dict[str, Any]:
    conn = _get_db()
    try:
        store = ResponseStore(RoleAccess(conn, Role.API))
        existing = store.get(body.request_id)
        if existing:
            if (
                existing.owner_id != owner.owner_id
                or existing.action_id != action_id
                or existing.response != "undo"
            ):
                raise HTTPException(409, "request_payload_conflict")
            return {
                "request_id": body.request_id,
                "status": "recorded",
                "status_url": f"/api/responses/{body.request_id}",
            }
        row = conn.execute(
            """SELECT a.*,p.proposed_at,s.raw_item_id FROM actions a
            JOIN proposals p ON p.id=a.proposal_id JOIN situations s ON s.id=p.situation_id WHERE a.id=?""",
            (action_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "action_not_found")
        if not row["binding_json"]:
            raise HTTPException(409, "legacy_action_binding_unavailable")
        binding = ApprovalBinding.model_validate_json(row["binding_json"])
        if binding.owner_id != owner.owner_id:
            raise HTTPException(404, "action_not_found")
        source = conn.execute(
            "SELECT source_id FROM raw_items WHERE id=?", (row["raw_item_id"],)
        ).fetchone()
        grant = owner.grant_for(source[0])
        if (grant.connection_id, grant.account_id) != (binding.connection_id, binding.account_id):
            raise HTTPException(403, "source_grant_mismatch")
        if row["status"] not in {"HELD", "DONE"} or (
            row["status"] == "DONE" and not row["recallable"]
        ):
            raise HTTPException(409, "action_not_undoable")
        intent = ResponseIntent(
            request_id=body.request_id,
            proposal_id=row["proposal_id"],
            response="undo",
            owner_id=owner.owner_id,
            responded_at=response_time(row["proposed_at"], row["created_at"]),
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
            action_id=action_id,
        )
        store.submit(intent)
        return {
            "request_id": body.request_id,
            "status": "recorded",
            "status_url": f"/api/responses/{body.request_id}",
        }
    except LifecycleError as exc:
        raise HTTPException(409, exc.code) from exc
    finally:
        conn.close()
