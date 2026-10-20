"""Files pack executor and undo implementation.

Authority: docs/PACKS_SPEC.md section 3.8 and docs/CONTRACT.md section 8 (I-20).
Enforces:
- Moves files strictly within FILES_ALLOWED_ROOTS.
- Never creates new folders in v1.
- Never overwrites existing files (appends ' (1)' on collision).
- Stores original path in undo_json; fails undo safely if original path occupied.
"""

import shutil
from pathlib import Path

from probation.config import settings
from probation.core.types import Action, ExecResult
from probation.packs.base import ExecutorIO


def _get_unique_dest_path(dest_file: Path) -> Path:
    """Resolve destination collisions by appending ' (1)', ' (2)', etc."""
    if not dest_file.exists():
        return dest_file

    parent = dest_file.parent
    stem = dest_file.stem
    suffix = dest_file.suffix

    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def execute_files_action(a: Action, io: ExecutorIO) -> ExecResult:
    """Execute file move action inside allowed roots."""
    act_type = a.type.upper()
    if act_type == "LEAVE":
        return ExecResult(success=True, action_id=a.id, undo_data={})

    if not act_type.startswith("MOVE_TO_FOLDER:"):
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Unsupported file action: {a.type}",
        )

    rel_folder = a.type.split("MOVE_TO_FOLDER:", 1)[1].strip().strip("/\\")
    allowed_roots = [
        Path(r.strip()).resolve() for r in settings.files_allowed_roots.split(",") if r.strip()
    ]

    source_path_str = a.params.get("path") or a.params.get("rel_path")
    if not source_path_str:
        return ExecResult(
            success=False,
            action_id=a.id,
            error="Missing file path in action params",
        )

    # Resolve source path
    src_file = Path(source_path_str)
    if not src_file.is_absolute():
        # Match against watched dirs / allowed roots
        found = False
        for root in allowed_roots:
            candidate = root / src_file
            if candidate.exists():
                src_file = candidate
                found = True
                break
        if not found and allowed_roots:
            src_file = allowed_roots[0] / src_file

    src_resolved = src_file.resolve()

    # Determine destination root
    dest_root = allowed_roots[0] if allowed_roots else src_resolved.parent
    for root in allowed_roots:
        try:
            src_resolved.relative_to(root)
            dest_root = root
            break
        except ValueError:
            continue

    dest_dir = (dest_root / rel_folder).resolve()

    # Validate destination is strictly inside an allowed root
    inside_allowed = False
    for root in allowed_roots:
        try:
            dest_dir.relative_to(root)
            inside_allowed = True
            break
        except ValueError:
            continue

    if not inside_allowed:
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Destination '{dest_dir}' is outside FILES_ALLOWED_ROOTS",
        )

    # In v1: Never creates folders. If directory does not exist, fail closed.
    if not dest_dir.exists():
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Destination folder '{rel_folder}' does not exist (folder creation disabled in v1)",
        )

    # If file physically exists on disk, move with collision protection
    if src_resolved.exists():
        target_file = dest_dir / src_resolved.name
        final_dest = _get_unique_dest_path(target_file)

        try:
            shutil.move(str(src_resolved), str(final_dest))
        except Exception as e:
            return ExecResult(
                success=False,
                action_id=a.id,
                error=f"Failed to move file on disk: {e}",
            )

        undo_data = {
            "original_path": str(src_resolved),
            "moved_to": str(final_dest),
        }
        return ExecResult(success=True, action_id=a.id, undo_data=undo_data)

    # Simulated fallback if running against pure world catalog
    final_sim_dest = dest_dir / src_resolved.name
    undo_data = {
        "original_path": str(src_resolved),
        "moved_to": str(final_sim_dest),
    }
    return ExecResult(success=True, action_id=a.id, undo_data=undo_data)


def undo_files_action(a: Action, io: ExecutorIO) -> ExecResult:
    """Reverse executed file move."""
    undo_info = a.undo or {}
    orig_path_str = undo_info.get("original_path")
    moved_to_str = undo_info.get("moved_to")

    if not orig_path_str or not moved_to_str:
        return ExecResult(
            success=False,
            action_id=a.id,
            error="Missing original_path or moved_to in undo_data",
        )

    orig_path = Path(orig_path_str)
    moved_to = Path(moved_to_str)

    # If original path is occupied, FAIL safely without overwriting
    if orig_path.exists():
        return ExecResult(
            success=False,
            action_id=a.id,
            error=f"Undo failed: Original path '{orig_path}' is occupied (never overwrite)",
        )

    if moved_to.exists():
        try:
            shutil.move(str(moved_to), str(orig_path))
        except Exception as e:
            return ExecResult(
                success=False,
                action_id=a.id,
                error=f"Failed to restore file: {e}",
            )

    return ExecResult(success=True, action_id=a.id, undo_data={})
