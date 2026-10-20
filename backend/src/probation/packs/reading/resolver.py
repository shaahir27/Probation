"""Reading Triage outcome resolution.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 9.1.
Rules:
- Item moved to specific collection -> FILE_TO_COLLECTION:{collection} (STRONG).
- Item archived -> ARCHIVE_LINK (STRONG).
- Item deleted -> DELETE (STRONG disagreement).
- Item still in inbox at window close -> LEAVE (WEAK).
- Window: 14 days.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import EvidenceStrength
from probation.core.types import Outcome, Situation
from probation.packs.base import WorldView

DEFAULT_READING_WINDOW_DAYS = 14


def _iso_str(dt: datetime) -> str:
    """Format UTC datetime to ISO string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_reading_outcome(
    s: Situation,
    world: WorldView,
    now: datetime,
    raw_payload: dict[str, Any] | None = None,
) -> Outcome | None:
    """Resolve observed reading outcome from SimWorld library state."""
    try:
        occurred_dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00"))
        if occurred_dt.tzinfo is None:
            occurred_dt = occurred_dt.replace(tzinfo=UTC)
        else:
            occurred_dt = occurred_dt.astimezone(UTC)
    except Exception:
        occurred_dt = Clock().now()

    window_days = getattr(settings, "reading_window_days", DEFAULT_READING_WINDOW_DAYS)
    window_close_dt = occurred_dt + timedelta(days=window_days)
    now_utc = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    p = raw_payload or {}
    url = str(p.get("url") or s.sender_key or "")

    # 1. Check explicit payload outcome (fixture/replay)
    observed = p.get("observed_action") or p.get("final_action")
    if observed:
        act = str(observed).upper()
        if act.startswith("FILE_TO_COLLECTION:") or act == "ARCHIVE_LINK" or act == "DELETE":
            return Outcome(
                situation_id=s.id,
                observed_action=act,
                strength=EvidenceStrength.STRONG,
                known_at=_iso_str(now_utc if now_utc < window_close_dt else window_close_dt),
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

    # 2. Query SimWorld library
    try:
        entry = world.get_library_entry(url)
        if entry:
            col = str(entry.get("collection", "inbox")).lower()
            if col == "archive":
                return Outcome(
                    situation_id=s.id,
                    observed_action="ARCHIVE_LINK",
                    strength=EvidenceStrength.STRONG,
                    known_at=_iso_str(now_utc if now_utc < window_close_dt else window_close_dt),
                )
            elif col != "inbox":
                return Outcome(
                    situation_id=s.id,
                    observed_action=f"FILE_TO_COLLECTION:{col}",
                    strength=EvidenceStrength.STRONG,
                    known_at=_iso_str(now_utc if now_utc < window_close_dt else window_close_dt),
                )
        else:
            # Entry was deleted
            return Outcome(
                situation_id=s.id,
                observed_action="DELETE",
                strength=EvidenceStrength.STRONG,
                known_at=_iso_str(window_close_dt),
            )
    except Exception:
        pass

    # 3. Unresolved item at window close becomes LEAVE
    if now_utc >= window_close_dt:
        return Outcome(
            situation_id=s.id,
            observed_action="LEAVE",
            strength=EvidenceStrength.WEAK,
            known_at=_iso_str(window_close_dt),
        )

    return None
