"""Calendar pack action execution and undo operations in SimWorld/Live.

Authority: docs/PACKS_SPEC.md section 2.6 and docs/CONTRACT.md section 8.
"""

from probation.core.types import Action, ExecResult
from probation.packs.base import ExecutorIO


def execute_calendar_action(action: Action, io: ExecutorIO) -> ExecResult:
    """Execute a calendar RSVP or event creation action in the world interface."""
    action_type = action.type.upper()
    uid = action.params.get("uid") or action.params.get("event_uid", "")

    if action_type in ("ACCEPT", "DECLINE", "TENTATIVE"):
        if not uid:
            return ExecResult(
                success=False,
                action_id=action.id,
                error="Missing 'uid' in calendar action parameters.",
            )
        target_status = (
            "ACCEPTED"
            if action_type == "ACCEPT"
            else ("DECLINED" if action_type == "DECLINE" else "TENTATIVE")
        )
        io.update_rsvp(uid, target_status)
        return ExecResult(
            success=True,
            action_id=action.id,
            undo_data={"action": action_type, "uid": uid, "previous_status": "NEEDS_ACTION"},
        )

    elif action_type == "BLOCK_TIME":
        # Create private event in world
        event_uid = uid or f"block-{action.id}"
        io.add_event(
            event_id=action.id,
            uid=event_uid,
            title=action.params.get("title", "Focus / Blocked Time"),
            description=action.params.get("description", "Created by Probation AI"),
            start_time=action.params.get("start_time", action.created_at),
            end_time=action.params.get("end_time", action.created_at),
            organizer=action.params.get("organizer", "user@probation.local"),
            attendees=[],
            status="CONFIRMED",
            my_status="ACCEPTED",
        )
        return ExecResult(
            success=True,
            action_id=action.id,
            undo_data={"action": "BLOCK_TIME", "uid": event_uid},
        )

    elif action_type == "NO_RESPONSE":
        return ExecResult(success=True, action_id=action.id, undo_data=None)

    return ExecResult(
        success=False,
        action_id=action.id,
        error=f"Unsupported calendar action type: '{action.type}'.",
    )


def undo_calendar_action(action: Action, io: ExecutorIO) -> ExecResult:
    """Reverse an executed calendar action."""
    undo = action.undo or {}
    uid = undo.get("uid") or action.params.get("uid", "")

    if not uid:
        return ExecResult(
            success=False,
            action_id=action.id,
            error="Missing 'uid' for calendar undo.",
        )

    action_type = undo.get("action", action.type).upper()

    if action_type in ("ACCEPT", "DECLINE", "TENTATIVE"):
        prev = undo.get("previous_status", "NEEDS_ACTION")
        io.update_rsvp(uid, prev)
        return ExecResult(success=True, action_id=action.id)

    elif action_type == "BLOCK_TIME":
        io.delete_event(uid)
        return ExecResult(success=True, action_id=action.id)

    return ExecResult(
        success=False,
        action_id=action.id,
        error=f"Action '{action.type}' cannot be undone.",
    )
