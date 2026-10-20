"""Calendar pack deterministic clue extraction via HistoryView.

Authority: docs/PACKS_SPEC.md sections 0.3 and 2.1-2.2.
Enforces Invariant I-6: History is read strictly through HistoryView(as_of=t).
"""

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from probation.config import settings
from probation.core.clock import Clock
from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.packs.mail.clues import normalize_address


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
        start_dt = Clock().now(user_tz)

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

    # Count interactions with this organiser across BOTH calendar AND mail (Section 0.3)
    prior_cal_items = hist.get_raw_items(pack="calendar")
    prior_mail_items = hist.get_raw_items(pack="mail")
    prior_situations = {row["id"]: row for row in hist.get_situations(pack="calendar")}
    prior_outcomes = {row["situation_id"]: row for row in hist.get_outcomes()}

    n_prior_organizer_events = 0
    n_prior_accepted_organizer = 0

    n_prior_bucket_events = 0
    n_prior_accepted_bucket = 0

    conflicts_count = 0
    adjacent_conflict = False

    # 1. Check mail interactions with organizer
    n_prior_mail_with_organizer = 0
    for m in prior_mail_items:
        try:
            m_payload = json.loads(m["payload_json"])
            m_from = normalize_address(m_payload.get("from", ""))
            m_to = normalize_address(m_payload.get("to", ""))
            if m_from == organizer_key or organizer_key in m_to:
                n_prior_mail_with_organizer += 1
        except Exception:
            continue

    # 2. Check calendar events
    for c in prior_cal_items:
        if c["id"] == s.raw_item_id:
            continue
        try:
            c_payload = json.loads(c["payload_json"])
        except Exception:
            continue

        c_org = normalize_address(c_payload.get("organizer", ""))
        c_status = str(c_payload.get("my_status") or c_payload.get("status", "")).upper()

        c_start_str = c_payload.get("start_time") or ""
        c_end_str = c_payload.get("end_time") or c_start_str
        try:
            c_start = datetime.fromisoformat(c_start_str.replace("Z", "+00:00")).astimezone(user_tz)
            c_end = datetime.fromisoformat(c_end_str.replace("Z", "+00:00")).astimezone(user_tz)
        except Exception:
            c_start = None
            c_end = None

        # Check outcome if this event had a situation
        is_accepted = "ACCEPT" in c_status
        for sit_id, sit_row in prior_situations.items():
            if sit_row["raw_item_id"] == c["id"]:
                out = prior_outcomes.get(sit_id)
                if out and out["observed_action"] == "ACCEPT":
                    is_accepted = True
                break

        # Check overlap conflicts with this new event if already accepted
        if is_accepted and c_start and c_end:
            # Overlap: max(start1, start2) < min(end1, end2)
            if max(start_dt, c_start) < min(end_dt, c_end):
                conflicts_count += 1

            # Adjacent conflict: within 30 minutes before or after
            gap_before = (start_dt - c_end).total_seconds() / 60.0
            gap_after = (c_start - end_dt).total_seconds() / 60.0
            if (0 <= gap_before <= 30) or (0 <= gap_after <= 30):
                adjacent_conflict = True

        if c_org == organizer_key:
            n_prior_organizer_events += 1
            if is_accepted:
                n_prior_accepted_organizer += 1

        # Check hour bucket rate
        if c_start:
            c_bucket = get_start_hour_bucket(c_start.hour)
            if c_bucket == start_hour_bucket:
                n_prior_bucket_events += 1
                if is_accepted:
                    n_prior_accepted_bucket += 1

    total_prior_organizer = n_prior_organizer_events + n_prior_mail_with_organizer
    if total_prior_organizer >= 10:
        organizer_tier = "frequent"
    elif total_prior_organizer >= 1:
        organizer_tier = "known"
    else:
        organizer_tier = "unknown"

    accept_rate_organizer = (n_prior_accepted_organizer + 1.0) / (n_prior_organizer_events + 2.0)
    accept_rate_hour_bucket = (n_prior_accepted_bucket + 1.0) / (n_prior_bucket_events + 2.0)

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
