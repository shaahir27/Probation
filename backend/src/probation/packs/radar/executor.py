"""Opportunity Radar executor and undo implementation.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 8.1 and docs/CONTRACT.md section 8.
Actions:
- TRACK: Create tracker entry in SimWorld (recallable=True). Undo deletes it.
- DISMISS: Move to not interested (recallable=True).
- LEAVE: No-op.
"""

from probation.core.types import Action, ExecResult
from probation.packs.base import ExecutorIO


def execute_radar_action(a: Action, io: ExecutorIO) -> ExecResult:
    """Execute Opportunity Radar side-effect into SimWorld."""
    act_type = a.type.upper()
    if act_type == "LEAVE":
        return ExecResult(success=True, action_id=a.id, undo_data={})

    if act_type == "TRACK":
        entry_id = a.params.get("entry_id") or f"track-{a.id}"
        title = a.params.get("title") or "Opportunity"
        organizer = a.params.get("organizer") or a.params.get("organiser") or "Unknown"
        opp_type = a.params.get("opp_type") or "other"
        deadline_date = a.params.get("deadline_date")
        official_url = a.params.get("official_url")
        fee_flag = bool(a.params.get("fee_mentioned", False))
        sources = a.params.get("sources") or []
        details = a.params

        try:
            io.add_tracker_entry(
                entry_id=entry_id,
                title=title,
                organizer=organizer,
                opp_type=opp_type,
                deadline_date=deadline_date,
                official_url=official_url,
                status="TRACKED",
                fee_flag=fee_flag,
                sources=sources,
                details=details,
                created_at=a.created_at,
            )
        except Exception as e:
            return ExecResult(
                success=False,
                action_id=a.id,
                error=f"Failed to write to Radar tracker: {e}",
            )

        undo_data = {"entry_id": entry_id, "previous_status": None}
        return ExecResult(success=True, action_id=a.id, undo_data=undo_data)

    elif act_type == "DISMISS":
        entry_id = a.params.get("entry_id") or f"track-{a.id}"
        title = a.params.get("title") or "Opportunity"
        organizer = a.params.get("organizer") or a.params.get("organiser") or "Unknown"
        opp_type = a.params.get("opp_type") or "other"
        try:
            existing = io.get_tracker_entry(entry_id)
            if existing:
                io.update_tracker_status(entry_id, "DISMISSED")
            else:
                io.add_tracker_entry(
                    entry_id=entry_id,
                    title=title,
                    organizer=organizer,
                    opp_type=opp_type,
                    status="DISMISSED",
                    created_at=a.created_at,
                )
        except Exception:
            pass
        return ExecResult(
            success=True,
            action_id=a.id,
            undo_data={"entry_id": entry_id, "previous_status": "DISMISSED"},
        )

    return ExecResult(
        success=False,
        action_id=a.id,
        error=f"Unsupported radar action: {a.type}",
    )


def undo_radar_action(a: Action, io: ExecutorIO) -> ExecResult:
    """Reverse executed Opportunity Radar action."""
    undo_info = a.undo or {}
    entry_id = undo_info.get("entry_id")

    if not entry_id:
        return ExecResult(
            success=False,
            action_id=a.id,
            error="Missing entry_id in undo_data",
        )

    try:
        io.delete_tracker_entry(entry_id)
    except Exception as e:
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Failed to delete entry from tracker: {e}",
        )

    return ExecResult(success=True, action_id=a.id, undo_data={})
