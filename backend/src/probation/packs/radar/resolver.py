"""Opportunity Radar outcome resolution.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 8.1.
Rules:
- TRACK observed when user keeps or creates tracker entry, or marks applied (STRONG).
- DISMISS observed when user archives mail without tracking or taps 'not interested' (STRONG).
- LEAVE observed when no action taken at window close (WEAK).
- Window: min(14 days, days to deadline), minimum 2 days.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import EvidenceStrength
from probation.core.types import Outcome, Situation
from probation.packs.base import WorldView

DEFAULT_RADAR_WINDOW_DAYS = 14
DEFAULT_MIN_RADAR_WINDOW_DAYS = 2


def _iso_str(dt: datetime) -> str:
    """Format UTC datetime to ISO string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_radar_outcome(
    s: Situation,
    world: WorldView,
    now: datetime,
    raw_payload: dict[str, Any] | None = None,
) -> Outcome | None:
    """Resolve observed opportunity triage outcome from SimWorld tracker state."""
    try:
        occurred_dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00"))
        if occurred_dt.tzinfo is None:
            occurred_dt = occurred_dt.replace(tzinfo=UTC)
        else:
            occurred_dt = occurred_dt.astimezone(UTC)
    except Exception:
        occurred_dt = Clock().now()

    p = raw_payload or {}
    deadline_text = p.get("deadline_text") or p.get("deadline") or ""
    days_to_deadline = 14.0

    if deadline_text:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(deadline_text))
        if m:
            try:
                dead_dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
                diff = (dead_dt - occurred_dt).total_seconds() / 86400.0
                if diff > 0:
                    days_to_deadline = diff
            except Exception:
                pass

    window_days = min(
        getattr(settings, "radar_window_days", DEFAULT_RADAR_WINDOW_DAYS),
        days_to_deadline,
    )
    min_window = getattr(settings, "radar_min_window_days", DEFAULT_MIN_RADAR_WINDOW_DAYS)
    effective_window_days = max(min_window, window_days)
    window_close_dt = occurred_dt + timedelta(days=effective_window_days)

    now_utc = now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    # 1. Check explicit outcome in payload (simulated / test fixture)
    observed = p.get("observed_action") or p.get("final_action")
    if observed:
        act = str(observed).upper()
        if act == "TRACK":
            return Outcome(
                situation_id=s.id,
                observed_action="TRACK",
                strength=EvidenceStrength.STRONG,
                known_at=_iso_str(now_utc if now_utc < window_close_dt else window_close_dt),
            )
        elif act == "DISMISS":
            return Outcome(
                situation_id=s.id,
                observed_action="DISMISS",
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

    # 2. Check SimWorld tracker table
    try:
        entries = world.get_tracker_entries()
        opp_name = str(p.get("opportunity_name") or p.get("subject") or "").lower()
        for e in entries:
            entry_title = str(e.get("title", "")).lower()
            if opp_name and (opp_name in entry_title or entry_title in opp_name):
                status = str(e.get("status", "")).upper()
                if status in ("TRACKED", "APPLIED"):
                    return Outcome(
                        situation_id=s.id,
                        observed_action="TRACK",
                        strength=EvidenceStrength.STRONG,
                        known_at=_iso_str(
                            now_utc if now_utc < window_close_dt else window_close_dt
                        ),
                    )
                elif status == "DISMISSED":
                    return Outcome(
                        situation_id=s.id,
                        observed_action="DISMISS",
                        strength=EvidenceStrength.STRONG,
                        known_at=_iso_str(
                            now_utc if now_utc < window_close_dt else window_close_dt
                        ),
                    )
    except Exception:
        pass

    # 3. Fallback: at window close, unresolved item becomes LEAVE
    if now_utc >= window_close_dt:
        return Outcome(
            situation_id=s.id,
            observed_action="LEAVE",
            strength=EvidenceStrength.WEAK,
            known_at=_iso_str(window_close_dt),
        )

    return None
