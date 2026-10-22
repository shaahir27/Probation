"""Files pack outcome resolution.

Authority: docs/PACKS_SPEC.md section 3.7 and docs/CONTRACT.md section 5.
Rules:
- File moved to subfolder within allowed roots -> MOVE_TO_FOLDER:{folder} (STRONG)
- File still in watched folder at window close -> LEAVE (WEAK)
- File deleted -> DELETE (STRONG)
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import EvidenceStrength
from probation.core.types import Outcome, Situation
from probation.packs.base import WorldView

DEFAULT_FILE_WINDOW_DAYS = 14


def _iso_str(dt: datetime) -> str:
    """Format UTC datetime to ISO string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_files_outcome(
    s: Situation,
    world: WorldView,
    now: datetime,
    raw_payload: dict[str, Any] | None = None,
) -> Outcome | None:
    """Resolve observed file outcome from filesystem state or world records."""
    try:
        occurred_dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00"))
        if occurred_dt.tzinfo is None:
            occurred_dt = occurred_dt.replace(tzinfo=UTC)
        else:
            occurred_dt = occurred_dt.astimezone(UTC)
    except Exception:
        occurred_dt = Clock().now()

    window_days = getattr(settings, "outcome_window_file_days", DEFAULT_FILE_WINDOW_DAYS)
    window_delta = timedelta(days=window_days)
    window_close_dt = occurred_dt + window_delta

    now_utc = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    p = raw_payload or {}
    rel_path_str = p.get("rel_path") or p.get("filename") or ""
    allowed_roots = [
        Path(r.strip()).resolve() for r in settings.files_allowed_roots.split(",") if r.strip()
    ]
    watched_dirs = [
        d.strip().replace("\\", "/").strip("/")
        for d in settings.files_watch_dirs.split(",")
        if d.strip()
    ]

    # 1. Check user_actions stream if available
    if hasattr(world, "get_user_actions"):
        now_iso = _iso_str(now_utc)
        actions = world.get_user_actions(item_id=rel_path_str, as_of=now_iso, actor="user")
        if not actions and Path(rel_path_str).name:
            actions = world.get_user_actions(
                item_id=Path(rel_path_str).name, as_of=now_iso, actor="user"
            )
        if actions:
            last_act = actions[-1]
            act_type = str(last_act["action_type"])
            act_time = str(last_act["acted_at"])
            if act_type.startswith("MOVE_TO_FOLDER:"):
                return Outcome(
                    situation_id=s.id,
                    observed_action=act_type,
                    strength=EvidenceStrength.STRONG,
                    known_at=act_time,
                )
            elif act_type == "DELETE":
                return Outcome(
                    situation_id=s.id,
                    observed_action="DELETE",
                    strength=EvidenceStrength.STRONG,
                    known_at=act_time,
                )

    # 2. Check observed location if provided in payload (simulation or fixture)
    observed_action = p.get("observed_action") or p.get("final_action")
    if observed_action:
        act = str(observed_action)
        if act == "DELETE":
            del_time_str = p.get("deleted_at")
            if del_time_str:
                try:
                    d_dt = datetime.fromisoformat(del_time_str.replace("Z", "+00:00"))
                    d_dt = d_dt if d_dt.tzinfo is not None else d_dt.replace(tzinfo=UTC)
                    if now_utc < d_dt:
                        return None
                except Exception:
                    pass
            known_at = del_time_str if del_time_str else _iso_str(window_close_dt)
            return Outcome(
                situation_id=s.id,
                observed_action="DELETE",
                strength=EvidenceStrength.STRONG,
                known_at=known_at,
            )
        elif act.startswith("MOVE_TO_FOLDER:"):
            move_time_str = p.get("moved_at")
            if move_time_str:
                try:
                    m_dt = datetime.fromisoformat(move_time_str.replace("Z", "+00:00"))
                    m_dt = m_dt if m_dt.tzinfo is not None else m_dt.replace(tzinfo=UTC)
                    if now_utc < m_dt:
                        return None
                except Exception:
                    pass
            known_at = move_time_str if move_time_str else _iso_str(window_close_dt)
            return Outcome(
                situation_id=s.id,
                observed_action=act,
                strength=EvidenceStrength.STRONG,
                known_at=known_at,
            )
        elif act == "LEAVE":
            if now_utc >= window_close_dt:
                return Outcome(
                    situation_id=s.id,
                    observed_action="LEAVE",
                    strength=EvidenceStrength.WEAK,
                    known_at=_iso_str(window_close_dt),
                )
            return None

    # 3. Check physical filesystem only after window close to avoid future leakage
    if now_utc < window_close_dt:
        return None

    filename = Path(rel_path_str).name
    current_found_rel_folder: str | None = None
    file_found_anywhere = False

    for root in allowed_roots:
        if not root.exists():
            continue
        # Search for file under root
        matches = list(root.rglob(filename))
        if matches:
            file_found_anywhere = True
            first_match = matches[0]
            rel_folder = first_match.parent.relative_to(root).as_posix()
            if any(rel_folder == w or rel_folder.endswith(f"/{w}") for w in watched_dirs):
                pass
            else:
                current_found_rel_folder = rel_folder
            break

    # If file was moved to another folder within allowed roots
    if current_found_rel_folder:
        return Outcome(
            situation_id=s.id,
            observed_action=f"MOVE_TO_FOLDER:{current_found_rel_folder}",
            strength=EvidenceStrength.STRONG,
            known_at=_iso_str(window_close_dt),
        )

    # If file was physically deleted
    if not file_found_anywhere and rel_path_str:
        return Outcome(
            situation_id=s.id,
            observed_action="DELETE",
            strength=EvidenceStrength.STRONG,
            known_at=_iso_str(window_close_dt),
        )

    # If file is still in watched directory: resolved as LEAVE at window close
    return Outcome(
        situation_id=s.id,
        observed_action="LEAVE",
        strength=EvidenceStrength.WEAK,
        known_at=_iso_str(window_close_dt),
    )
