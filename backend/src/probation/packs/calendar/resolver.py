"""Calendar pack outcome resolution and censorship window handling.

Authority: docs/PACKS_SPEC.md section 2.5.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from probation.core.enums import EvidenceStrength
from probation.core.types import Outcome, Situation
from probation.packs.base import WorldView

DEFAULT_INVITE_MAX_DAYS = 7


def resolve_calendar_outcome(
    s: Situation,
    world: WorldView,
    now: datetime,
    raw_payload: dict[str, Any] | None = None,
    max_window_days: int | None = None,
    user_addresses: list[str] | str | None = None,
) -> Outcome | None:
    """Resolve observed attendee RSVP outcome for an invite situation."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    try:
        occ_dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00"))
        if occ_dt.tzinfo is None:
            occ_dt = occ_dt.replace(tzinfo=UTC)
        else:
            occ_dt = occ_dt.astimezone(UTC)
    except Exception:
        occ_dt = now

    payload = raw_payload or {}
    start_str = payload.get("start_time") or s.occurred_at
    try:
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=UTC)
        else:
            start_dt = start_dt.astimezone(UTC)
    except Exception:
        start_dt = occ_dt + timedelta(days=DEFAULT_INVITE_MAX_DAYS)

    days = max_window_days if max_window_days is not None else DEFAULT_INVITE_MAX_DAYS
    max_window_end = occ_dt + timedelta(days=days)

    # Window close: min(event_start, occurred_at + max_window_days)
    window_close = min(start_dt, max_window_end)
    window_close_iso = window_close.strftime("%Y-%m-%dT%H:%M:%SZ")

    uid = payload.get("uid") or ""
    event_obj = world.get_event(uid) if uid else None

    # Retrieve current attendee status from world or payload
    my_status = "NEEDS_ACTION"
    if event_obj:
        my_status = str(
            event_obj.get("my_status") or event_obj.get("status", "NEEDS_ACTION")
        ).upper()
    elif "my_status" in payload:
        my_status = str(payload["my_status"]).upper()
    elif "status" in payload:
        my_status = str(payload["status"]).upper()

    # Strong responses
    if "ACCEPT" in my_status:
        # Known at response time or window close
        resp_time = payload.get("responded_at") or window_close_iso
        return Outcome(
            situation_id=s.id,
            observed_action="ACCEPT",
            strength=EvidenceStrength.STRONG,
            source="footprint",
            observed_at=resp_time,
            known_at=resp_time,
            details={"my_status": my_status},
        )

    if "DECLIN" in my_status:
        resp_time = payload.get("responded_at") or window_close_iso
        return Outcome(
            situation_id=s.id,
            observed_action="DECLINE",
            strength=EvidenceStrength.STRONG,
            source="footprint",
            observed_at=resp_time,
            known_at=resp_time,
            details={"my_status": my_status},
        )

    if "TENTATIVE" in my_status:
        resp_time = payload.get("responded_at") or window_close_iso
        return Outcome(
            situation_id=s.id,
            observed_action="TENTATIVE",
            strength=EvidenceStrength.STRONG,
            source="footprint",
            observed_at=resp_time,
            known_at=resp_time,
            details={"my_status": my_status},
        )

    # If status is still NEEDS_ACTION, check whether observation window has closed
    if now < window_close:
        return None  # Right-censored

    return Outcome(
        situation_id=s.id,
        observed_action="NO_RESPONSE",
        strength=EvidenceStrength.WEAK,
        source="footprint",
        observed_at=window_close_iso,
        known_at=window_close_iso,
        details={"my_status": my_status},
    )
