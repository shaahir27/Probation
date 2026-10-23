"""Calendar pack deterministic clue extraction via HistoryView.

Authority: docs/PACKS_SPEC.md sections 0.3 and 2.1-2.2.
Enforces Invariant I-6: History is read strictly through HistoryView(as_of=t).
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from probation.config import settings
from probation.core.clock import get_clock
from probation.core.history import HistoryView
from probation.core.identity import normalize_address
from probation.core.types import Situation


def get_start_hour_bucket(hour: int) -> str:
    """Bucket hour of day per docs/PACKS_SPEC.md section 2.2."""
    if hour < 9:
        return "early"
    elif hour < 12:
        return "morning"
    elif hour < 17:
        return "afternoon"
    return "evening"


def extract_calendar_clues(
    s: Situation,
    hist: HistoryView,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, float | str | bool]:
    """Compute all 12 deterministic clues for an invitation situation strictly via HistoryView."""
    payload = raw_payload or {}
    organizer_raw = payload.get("organizer") or s.sender_key or ""
    organizer_key = normalize_address(organizer_raw)

    tz_str = settings.user_tz or "Asia/Kolkata"
    try:
        user_tz = ZoneInfo(tz_str)
    except Exception:
        user_tz = ZoneInfo("Asia/Kolkata")

    # Parse start and end times
    start_str = payload.get("start_time") or s.occurred_at
    end_str = payload.get("end_time") or start_str

    try:
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(user_tz)
    except Exception:
        start_dt = get_clock().now(user_tz)

    try:
        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(user_tz)
    except Exception:
        end_dt = start_dt

    try:
        occ_dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00")).astimezone(user_tz)
    except Exception:
        occ_dt = start_dt

    duration_min = max(0, int((end_dt - start_dt).total_seconds() // 60))
    lead_days = max(0.0, round((start_dt - occ_dt).total_seconds() / 86400.0, 2))

    start_hour_bucket = get_start_hour_bucket(start_dt.hour)
    start_weekday = start_dt.weekday()

    attendees = payload.get("attendees") or []
    n_attendees = max(1, len(attendees))

    is_recurring = bool(payload.get("is_recurring") or payload.get("rrule"))
    location = str(payload.get("location") or "")
    description = str(payload.get("description") or "")
    has_location_or_link = bool(
        location.strip() or ("http://" in description) or ("https://" in description)
    )

    aggregate = hist.calendar_statistics(
        organizer_key,
        current_id=s.id,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        timezone=tz_str,
    )
    organizer_tier = str(aggregate["organizer_tier"])
    conflicts_count = int(aggregate["conflicts_count"])
    adjacent_conflict = bool(aggregate["adjacent_conflict"])
    accept_rate_organizer = float(aggregate["accept_rate_organizer"])
    accept_rate_hour_bucket = float(aggregate["accept_rate_hour_bucket"])

    return {
        "organizer_tier": organizer_tier,
        "start_hour_bucket": start_hour_bucket,
        "start_weekday": start_weekday,
        "duration_min": duration_min,
        "lead_days": lead_days,
        "n_attendees": n_attendees,
        "is_recurring": is_recurring,
        "conflicts_count": conflicts_count,
        "adjacent_conflict": adjacent_conflict,
        "accept_rate_organizer": round(accept_rate_organizer, 4),
        "accept_rate_hour_bucket": round(accept_rate_hour_bucket, 4),
        "has_location_or_link": has_location_or_link,
    }
