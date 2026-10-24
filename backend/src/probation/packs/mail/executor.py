"""Mail pack action execution and undo operations in SimWorld/Live.

Authority: docs/PACKS_SPEC.md section 1.7 and docs/CONTRACT.md section 8.
"""

from probation.core.types import Action, ExecResult
from probation.packs.base import ExecutorIO
from probation.packs.mail.lifecycle_io import MailExecutionIO
from probation.packs.mail.lifecycle_operations import prepare_effect, prepare_undo


def execute_mail_action(action: Action, io: ExecutorIO) -> ExecResult:
    """Execute a mail side-effect action against the world interface."""
    action_type = action.type.upper()
    msg_id = action.params.get("message_id") or action.params.get("msg_id", "")

    if not msg_id:
        return ExecResult(
            success=False,
            action_id=action.id,
            error="Missing 'message_id' in action parameters.",
        )

    if action_type in {"ARCHIVE", "TRASH"}:
        if not isinstance(io, MailExecutionIO):
            return ExecResult(success=False, action_id=action.id, error="mail_snapshot_unavailable")
        try:
            before = io.snapshot_mail(str(msg_id))
            prepared = prepare_effect(action, before, action.created_at)
            receipt = io.apply_mail(
                f"{action.id}:execute",
                prepared["payload_hash"],
                prepared["payload"],
                before.revision,
            )
            return ExecResult(
                success=receipt.outcome == "confirmed",
                action_id=action.id,
                error=receipt.safe_code,
                undo_data=prepared["undo"],
            )
        except (ValueError, KeyError):
            return ExecResult(success=False, action_id=action.id, error="mail_state_conflict")

    elif action_type == "REPLY":
        # Send reply message to original sender
        body_text = action.params.get("body", "")
        thread_id = action.params.get("thread_id", msg_id)
        to_addr = action.params.get("to_addr", "")
        from_addr = action.params.get("from_addr", "")
        reply_id = f"<reply-{action.id}@probation.local>"
        now_iso = action.created_at

        io.add_message(
            msg_id=action.id,
            message_id=reply_id,
            thread_id=thread_id,
            from_addr=from_addr,
            to_addr=to_addr,
            subject=action.params.get("subject", "Re: "),
            body=body_text,
            labels=["SENT"],
            received_at=now_iso,
            in_reply_to=msg_id,
            has_attachment=False,
        )
        return ExecResult(
            success=True,
            action_id=action.id,
            undo_data=None,  # Not recallable
        )

    elif action_type == "FORWARD":
        # Forward message
        fwd_id = f"<fwd-{action.id}@probation.local>"
        io.add_message(
            msg_id=action.id,
            message_id=fwd_id,
            thread_id=action.params.get("thread_id", msg_id),
            from_addr=action.params.get("from_addr", ""),
            to_addr=action.params.get("to_addr", ""),
            subject=action.params.get("subject", "Fwd: "),
            body=action.params.get("body", ""),
            labels=["SENT"],
            received_at=action.created_at,
            in_reply_to=msg_id,
            has_attachment=False,
        )
        return ExecResult(
            success=True,
            action_id=action.id,
            undo_data=None,  # Not recallable
        )

    elif action_type == "LEAVE":
        return ExecResult(success=True, action_id=action.id, undo_data=None)

    return ExecResult(
        success=False,
        action_id=action.id,
        error=f"Unsupported mail action type: '{action.type}'.",
    )


def undo_mail_action(action: Action, io: ExecutorIO) -> ExecResult:
    """Reverse an executed mail action."""
    if not isinstance(io, MailExecutionIO):
        return ExecResult(success=False, action_id=action.id, error="mail_snapshot_unavailable")
    undo = action.undo or {}
    try:
        resource = str(undo.get("resource_id", ""))
        before = io.snapshot_mail(resource)
        prepared = prepare_undo(action, before)
        receipt = io.apply_mail(
            f"{action.id}:undo", prepared["payload_hash"], prepared["payload"], before.revision
        )
        return ExecResult(
            success=receipt.outcome == "confirmed", action_id=action.id, error=receipt.safe_code
        )
    except (ValueError, KeyError):
        return ExecResult(success=False, action_id=action.id, error="undo_state_conflict")
