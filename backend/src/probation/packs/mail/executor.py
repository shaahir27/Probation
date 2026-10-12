"""Mail pack action execution and undo operations in SimWorld/Live.

Authority: docs/PACKS_SPEC.md section 1.7 and docs/CONTRACT.md section 8.
"""

from probation.core.types import Action, ExecResult
from probation.packs.base import ExecutorIO


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

    if action_type == "ARCHIVE":
        # Remove INBOX label; store original state in undo_data
        io.update_message_labels(msg_id, remove_labels=["INBOX"])
        return ExecResult(
            success=True,
            action_id=action.id,
            undo_data={"action": "ARCHIVE", "message_id": msg_id, "restored_label": "INBOX"},
        )

    elif action_type == "TRASH":
        # Add TRASH label
        io.update_message_labels(msg_id, add_labels=["TRASH"])
        return ExecResult(
            success=True,
            action_id=action.id,
            undo_data={"action": "TRASH", "message_id": msg_id, "removed_label": "TRASH"},
        )

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
    undo = action.undo or {}
    msg_id = undo.get("message_id") or action.params.get("message_id", "")

    if not msg_id:
        return ExecResult(
            success=False,
            action_id=action.id,
            error="Missing 'message_id' for undo.",
        )

    action_type = undo.get("action", action.type).upper()

    if action_type == "ARCHIVE":
        # Add INBOX back
        io.update_message_labels(msg_id, add_labels=["INBOX"])
        return ExecResult(success=True, action_id=action.id)

    elif action_type == "TRASH":
        # Remove TRASH label
        io.update_message_labels(msg_id, remove_labels=["TRASH"])
        return ExecResult(success=True, action_id=action.id)

    return ExecResult(
        success=False,
        action_id=action.id,
        error=f"Action '{action.type}' cannot be undone or is not recallable.",
    )
