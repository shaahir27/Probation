"""Reading Triage executor and undo implementation.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 9.1 and docs/CONTRACT.md section 8.
Actions:
- FILE_TO_COLLECTION:{collection}: Move item to library collection (recallable=True).
- ARCHIVE_LINK: Move item to archive collection (recallable=True).
- LEAVE: No-op.
"""

from probation.core.types import Action, ExecResult
from probation.packs.base import ExecutorIO


def execute_reading_action(a: Action, io: ExecutorIO) -> ExecResult:
    """Execute Reading Triage side-effect into SimWorld library."""
    act_type = a.type.upper()
    if act_type == "LEAVE":
        return ExecResult(success=True, action_id=a.id, undo_data={})

    url = a.params.get("url") or a.params.get("link")
    if not url:
        return ExecResult(
            success=False,
            action_id=a.id,
            error="Missing URL in action params",
        )

    target_collection = "archive"
    if act_type.startswith("FILE_TO_COLLECTION:"):
        target_collection = a.type.split("FILE_TO_COLLECTION:", 1)[1].strip()
    elif act_type == "ARCHIVE_LINK":
        target_collection = "archive"
    else:
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Unsupported reading action: {a.type}",
        )

    try:
        current_entry = io.get_library_entry(url)
        if current_entry:
            prev_col = current_entry.get("collection", "inbox")
            io.update_library_collection(url, target_collection)
        else:
            prev_col = "inbox"
            io.add_library_entry(
                entry_id=f"lib-{a.id}",
                url=url,
                title=str(a.params.get("title", "")),
                collection=target_collection,
                topic=str(a.params.get("topic", "other")),
                content_type=str(a.params.get("content_type", "article")),
                saved_at=a.created_at,
            )
    except Exception as e:
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Failed to update library collection: {e}",
        )

    undo_data = {"url": url, "previous_collection": prev_col}
    return ExecResult(success=True, action_id=a.id, undo_data=undo_data)


def undo_reading_action(a: Action, io: ExecutorIO) -> ExecResult:
    """Reverse executed Reading Triage action."""
    undo_info = a.undo or {}
    url = undo_info.get("url")
    prev_col = undo_info.get("previous_collection", "inbox")

    if not url:
        return ExecResult(
            success=False,
            action_id=a.id,
            error="Missing url in undo_data",
        )

    try:
        io.update_library_collection(url, prev_col)
    except Exception as e:
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Failed to restore library collection: {e}",
        )

    return ExecResult(success=True, action_id=a.id, undo_data={})
