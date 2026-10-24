"""Executor request consumption persists intent separately from target effects."""

from typing import TYPE_CHECKING, Any

from probation.core.enums import GateDecision
from probation.core.lifecycle import LifecycleError
from probation.core.types import ExecResult
from probation.db.lifecycle_receipts import ReceiptStore
from probation.db.lifecycle_responses import ResponseStore

if TYPE_CHECKING:
    from probation.workers.executor import Executor


def consume_responses(worker: "Executor", now: str, limit: int) -> int:
    if worker.conn.in_transaction:
        raise ValueError("Response consumption requires committed intent")
    if not 1 <= limit <= 100:
        raise ValueError("Invalid consumption batch")
    access = worker.role_access
    receipts, responses = ReceiptStore(access), ResponseStore(access)
    count = 0
    for intent in responses.pending(now, limit):
        with access.transaction():
            claim = receipts.claim_response(intent.request_id, now=now, owner=worker.worker_id)
            if claim is None:
                continue
            try:
                result: dict[str, Any]
                if intent.response == "undo":
                    if intent.action_id is None:
                        raise ValueError("undo_action_missing")
                    result = {"action_id": intent.action_id, "operation": "undo"}
                elif intent.reviewed_payload.action == "LEAVE":
                    result = {"not_required": True}
                else:
                    from probation.engine.caps import is_recallable

                    binding = intent.reviewed_payload
                    action = worker.create_action(
                        intent.proposal_id,
                        "mail",
                        binding.action,
                        binding.params,
                        1,
                        is_recallable(binding.action),
                        GateDecision.SUGGEST,
                        now,
                        binding=binding,
                        approval_response_id=intent.request_id,
                    )
                    result = {"action_id": action.id, "operation": "execute"}
                receipts.finish(claim, now=now, status="succeeded", result=result)
            except (LifecycleError, ValueError):
                receipts.finish(claim, now=now, status="failed", safe_code="invalid_action_intent")
            count += 1
    return count


def consume_undo_effects(worker: "Executor", now: str, limit: int = 32) -> list[ExecResult]:
    """Consumed undo requests remain durable work even while the action is DONE."""
    from probation.workers.mail_execution import MailLifecycle

    rows = worker.role_access.conn.execute(
        """SELECT u.action_id FROM user_responses u
        JOIN command_receipts r ON r.response_id=u.id AND r.consumer='executor'
        JOIN actions a ON a.id=u.action_id
        WHERE u.schema_version=2 AND u.response='undo' AND r.state='succeeded'
        AND u.responded_at COLLATE UTC_TIMESTAMP<=? AND a.pack='mail'
        AND a.status IN('DONE','HELD','PENDING') ORDER BY u.responded_at COLLATE UTC_TIMESTAMP,u.id LIMIT ?""",
        (now, limit),
    ).fetchall()
    return [MailLifecycle(worker).undo(str(row["action_id"]), now) for row in rows]
