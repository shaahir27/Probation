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
    # Authority: docs/CONTRACT.md Invariant I-7 (proposed_at < known_at)
    window_close = min(start_dt, max_window_end)
    if window_close <= occ_dt:
        window_close = occ_dt + timedelta(hours=1)
    window_close_iso = window_close.strftime("%Y-%m-%dT%H:%M:%SZ")

    uid = payload.get("uid") or ""
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Check user_actions stream if available
    if hasattr(world, "get_user_actions") and uid:
        actions = world.get_user_actions(item_id=uid, as_of=now_iso, actor="user")
        if actions:
            last_act = actions[-1]
            act_type = str(last_act["action_type"]).upper()
            act_time = str(last_act["acted_at"])
            try:
                act_dt = datetime.fromisoformat(act_time.replace("Z", "+00:00"))
                act_dt = act_dt if act_dt.tzinfo is not None else act_dt.replace(tzinfo=UTC)
                if act_dt <= occ_dt:
                    act_dt = occ_dt + timedelta(minutes=30)
                    act_time = act_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass
            if act_type in ("ACCEPT", "DECLINE", "TENTATIVE"):
                return Outcome(
                    situation_id=s.id,
                    observed_action=act_type,
                    strength=EvidenceStrength.STRONG,
                    source="footprint",
                    observed_at=act_time,
                    known_at=act_time,
                    details={
                        "my_status": f"{act_type}ED" if act_type != "TENTATIVE" else "TENTATIVE"
                    },
                )

    event_obj: dict[str, Any] | None = None
    if uid:
        try:
            event_obj = world.get_event(uid, as_of=now_iso)
        except TypeError:
            event_obj = world.get_event(uid)

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

    # Prevent peeking: if response timestamp is recorded and in the future relative to `now`, it is not known yet
    responded_at_str = payload.get("responded_at") or (
        event_obj.get("responded_at") if event_obj else None
    )
    if responded_at_str:
        try:
            resp_dt = datetime.fromisoformat(responded_at_str.replace("Z", "+00:00"))
            resp_dt = resp_dt if resp_dt.tzinfo is not None else resp_dt.replace(tzinfo=UTC)
            if now < resp_dt:
                return None
            if resp_dt <= occ_dt:
                resp_dt = occ_dt + timedelta(minutes=30)
                responded_at_str = resp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    resp_time = responded_at_str or window_close_iso

    # Strong responses
    if "ACCEPT" in my_status:
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
