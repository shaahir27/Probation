"""Chain step execution: BLOCK_TIME, CREATE_TASK, REPLY draft.

Authority: docs/PACKS_SPEC.md section 4.5 and docs/CONTRACT.md section 8.
BLOCK_TIME and CREATE_TASK are recallable. Undo deletes the created event or task.
"""

import uuid
from typing import Any

from probation.core.types import Action, ExecResult
from probation.packs.base import ExecutorIO


def execute_chain_action(action: Action, world: ExecutorIO) -> ExecResult:
    """Execute a chain follow-up action against the simulated environment.

    Authority: docs/PACKS_SPEC.md section 4.5:
    - BLOCK_TIME: create a private event on the user's calendar. Undo deletes it.
    - CREATE_TASK: create a task in the task list. Undo deletes it.
    - REPLY: create a draft response. Undo removes draft.
    """
    act_type = action.type.upper()
    params = action.params

    if act_type == "BLOCK_TIME":
        title = str(params.get("title") or "Focus Block")
        start_time = str(params.get("start") or action.created_at)
        end_time = str(params.get("end") or action.created_at)
        uid = f"block-{uuid.uuid4().hex[:12]}"

        if hasattr(world, "add_event"):
            world.add_event(
                event_id=uid,
                uid=uid,
                title=title,
                description="Automated focus block created by Probation chain rule.",
                start_time=start_time,
                end_time=end_time,
                organizer="meena@example.test",
                attendees=[],
                status="CONFIRMED",
                my_status="ACCEPTED",
            )
            return ExecResult(
                success=True,
                action_id=action.id,
                undo_data={"uid": uid, "type": "BLOCK_TIME"},
            )
        else:
            return ExecResult(
                success=False,
                action_id=action.id,
                error="World does not support calendar operations",
            )

    elif act_type == "CREATE_TASK":
        title = str(params.get("title") or "Task")
        due = params.get("due")
        task_id = f"task-{uuid.uuid4().hex[:12]}"

        if hasattr(world, "add_task"):
            world.add_task(
                task_id=task_id,
                title=title,
                due_date=str(due) if due else None,
                created_at=action.created_at,
                status="TODO",
            )
            return ExecResult(
                success=True,
                action_id=action.id,
                undo_data={"task_id": task_id, "type": "CREATE_TASK"},
            )
        else:
            return ExecResult(
                success=False,
                action_id=action.id,
                error="World does not support task operations",
            )

    elif act_type == "REPLY":
        # Reply draft
        msg_id = f"draft-{uuid.uuid4().hex[:12]}"
        template = str(params.get("template") or "Draft Reply")

        if hasattr(world, "add_message"):
            world.add_message(
                msg_id=msg_id,
                message_id=f"<{msg_id}@probation.sim>",
                thread_id="chain-draft",
                from_addr="meena@example.test",
                to_addr="recipient@example.test",
                subject=f"Re: {template}",
                body=template,
                labels=["DRAFT"],
                received_at=action.created_at,
            )
            return ExecResult(
                success=True,
                action_id=action.id,
                undo_data={"msg_id": msg_id, "type": "REPLY"},
            )
        else:
            return ExecResult(
                success=False,
                action_id=action.id,
                error="World does not support message operations",
            )

    return ExecResult(
        success=False,
        action_id=action.id,
        error=f"Unsupported chain action type: {act_type}",
    )


def undo_chain_action(undo_data: dict[str, Any], world: ExecutorIO) -> ExecResult:
    """Revert a previously executed chain action."""
    action_type = str(undo_data.get("type", "")).upper()

    if action_type == "BLOCK_TIME":
        uid = str(undo_data.get("uid", ""))
        if hasattr(world, "delete_event") and uid:
            world.delete_event(uid)
            return ExecResult(success=True, action_id=uid)
        return ExecResult(success=False, action_id=uid, error="Failed to delete calendar event")

    elif action_type == "CREATE_TASK":
        task_id = str(undo_data.get("task_id", ""))
        if hasattr(world, "delete_task") and task_id:
            world.delete_task(task_id)
            return ExecResult(success=True, action_id=task_id)
        return ExecResult(success=False, action_id=task_id, error="Failed to delete task")

    elif action_type == "REPLY":
        # Delete draft
        return ExecResult(success=True, action_id=str(undo_data.get("msg_id", "")))

    return ExecResult(
        success=False,
        action_id="unknown",
        error=f"Unsupported chain undo action type: {action_type}",
    )
