"""Mail pack outcome resolution and censorship window handling.

Authority: docs/PACKS_SPEC.md section 1.6 and docs/ENGINE_SPEC.md section 1.1.
Enforces priority order: REPLY > FORWARD > TRASH > ARCHIVE > LEAVE.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from probation.config import settings
from probation.core.enums import EvidenceStrength
from probation.core.types import Outcome, Situation
from probation.packs.base import WorldView
from probation.packs.mail.clues import normalize_address

DEFAULT_MAIL_WINDOW_DAYS = 7


def resolve_mail_outcome(
    s: Situation,
    world: WorldView,
    now: datetime,
    raw_payload: dict[str, Any] | None = None,
    window_days: int | None = None,
) -> Outcome | None:
    """Resolve observed user action for a mail situation per priority order."""
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

    days = window_days if window_days is not None else DEFAULT_MAIL_WINDOW_DAYS
    window_end = occ_dt + timedelta(days=days)
    window_end_iso = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = raw_payload or {}
    msg_id = payload.get("message_id") or ""
    subject = payload.get("subject") or ""

    user_addrs = [normalize_address(a) for a in settings.user_addresses.split(",")]

    # Check simulated messages in the world for REPLY or FORWARD
    all_msgs = world.get_messages()

    reply_msg: dict[str, Any] | None = None
    forward_msg: dict[str, Any] | None = None

    for m in all_msgs:
        m_from = normalize_address(m.get("from_addr") or m.get("from") or "")
        is_user_sent = any(u in m_from for u in user_addrs)
        if not is_user_sent:
            continue

        try:
            m_time = datetime.fromisoformat(m["received_at"].replace("Z", "+00:00"))
            if m_time.tzinfo is None:
                m_time = m_time.replace(tzinfo=UTC)
            else:
                m_time = m_time.astimezone(UTC)
        except Exception:
            continue

        # Must occur after the situation arrived and within the window
        if not (occ_dt <= m_time <= window_end):
            continue
        # And cannot be known in the future relative to `now`
        if m_time > now:
            continue

        m_in_reply = m.get("in_reply_to") or ""
        m_subj = m.get("subject") or ""

        # Check Reply
        if msg_id and m_in_reply == msg_id:
            if reply_msg is None or m_time < datetime.fromisoformat(
                reply_msg["received_at"].replace("Z", "+00:00")
            ):
                reply_msg = m

        # Check Forward
        is_fwd_subj = m_subj.lower().startswith("fwd:") or m_subj.lower().startswith("fw:")
        if is_fwd_subj and (
            msg_id in m.get("body", "") or (subject and subject.lower() in m_subj.lower())
        ):
            if forward_msg is None or m_time < datetime.fromisoformat(
                forward_msg["received_at"].replace("Z", "+00:00")
            ):
                forward_msg = m

    # Rank 1: REPLY
    if reply_msg is not None:
        rep_iso = reply_msg["received_at"]
        return Outcome(
            situation_id=s.id,
            observed_action="REPLY",
            strength=EvidenceStrength.STRONG,
            source="footprint",
            observed_at=rep_iso,
            known_at=rep_iso,
            details={"reply_message_id": reply_msg.get("message_id")},
        )

    # Rank 2: FORWARD
    if forward_msg is not None:
        fwd_iso = forward_msg["received_at"]
        return Outcome(
            situation_id=s.id,
            observed_action="FORWARD",
            strength=EvidenceStrength.STRONG,
            source="footprint",
            observed_at=fwd_iso,
            known_at=fwd_iso,
            details={"forward_message_id": forward_msg.get("message_id")},
        )

    # If the observation window has not closed yet, censor (outcome is not yet final)
    if now < window_end:
        return None

    # Retrieve current label state for this message
    orig_msg = world.get_message(msg_id) if msg_id else None
    labels = orig_msg.get("labels", []) if orig_msg else payload.get("labels", ["INBOX"])
    labels_upper = [str(lbl).upper() for lbl in labels]

    # Rank 3: TRASH
    if "TRASH" in labels_upper:
        return Outcome(
            situation_id=s.id,
            observed_action="TRASH",
            strength=EvidenceStrength.STRONG,
            source="footprint",
            observed_at=window_end_iso,
            known_at=window_end_iso,
            details={"final_labels": labels},
        )

    # Rank 4: ARCHIVE (not in INBOX, not in TRASH or SPAM)
    if "INBOX" not in labels_upper and "SPAM" not in labels_upper:
        return Outcome(
            situation_id=s.id,
            observed_action="ARCHIVE",
            strength=EvidenceStrength.STRONG,
            source="footprint",
            observed_at=window_end_iso,
            known_at=window_end_iso,
            details={"final_labels": labels},
        )

    # Rank 5: LEAVE (still in INBOX)
    return Outcome(
        situation_id=s.id,
        observed_action="LEAVE",
        strength=EvidenceStrength.WEAK,
        source="footprint",
        observed_at=window_end_iso,
        known_at=window_end_iso,
        details={"final_labels": labels},
    )
