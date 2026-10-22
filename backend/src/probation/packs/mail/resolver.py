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
from probation.packs.identity import world_user_addresses
from probation.packs.mail.clues import normalize_address

DEFAULT_MAIL_WINDOW_DAYS = 7


class MailResolverIndex:
    """Pre-indexed user-sent messages for high performance O(1) outcome resolution."""

    def __init__(
        self,
        user_addrs: list[str],
        messages: list[dict[str, Any]],
    ) -> None:
        self.replies_by_in_reply_to: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
        self.user_forwards: list[tuple[datetime, dict[str, Any]]] = []

        norm_addrs = [normalize_address(a) for a in user_addrs if a.strip()]

        for m in messages:
            m_from = normalize_address(m.get("from_addr") or m.get("from") or "")
            if not any(u in m_from for u in norm_addrs):
                continue

            rec_str = m.get("received_at")
            if not rec_str:
                continue
            try:
                m_time = datetime.fromisoformat(rec_str.replace("Z", "+00:00"))
                if m_time.tzinfo is None:
                    m_time = m_time.replace(tzinfo=UTC)
                else:
                    m_time = m_time.astimezone(UTC)
            except Exception:
                continue

            in_reply = m.get("in_reply_to")
            if in_reply:
                self.replies_by_in_reply_to.setdefault(in_reply, []).append((m_time, m))

            m_subj = m.get("subject") or ""
            if m_subj.lower().startswith("fwd:") or m_subj.lower().startswith("fw:"):
                self.user_forwards.append((m_time, m))


def resolve_mail_outcome(
    s: Situation,
    world: WorldView,
    now: datetime,
    raw_payload: dict[str, Any] | None = None,
    window_days: int | None = None,
    user_addresses: list[str] | str | None = None,
    index: MailResolverIndex | None = None,
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

    if user_addresses is not None:
        if isinstance(user_addresses, str):
            user_addrs = [normalize_address(a) for a in user_addresses.split(",") if a.strip()]
        else:
            user_addrs = [normalize_address(a) for a in user_addresses if a.strip()]
    elif (world_addrs := world_user_addresses(world)) is not None:
        user_addrs = [normalize_address(a) for a in world_addrs]
    else:
        user_addrs = [normalize_address(a) for a in settings.user_addresses.split(",") if a.strip()]

    # Use pre-built index or build on the fly
    mail_index = index or MailResolverIndex(user_addrs, world.get_messages())

    reply_msg: dict[str, Any] | None = None
    forward_msg: dict[str, Any] | None = None

    # Check Reply (O(1) lookup on in_reply_to)
    if msg_id and msg_id in mail_index.replies_by_in_reply_to:
        best_time: datetime | None = None
        for m_time, m in mail_index.replies_by_in_reply_to[msg_id]:
            if occ_dt <= m_time <= window_end and m_time <= now:
                if best_time is None or m_time < best_time:
                    best_time = m_time
                    reply_msg = m

    # Check Forward (iterates only over user forward messages, tiny list)
    best_fwd_time: datetime | None = None
    for m_time, m in mail_index.user_forwards:
        if occ_dt <= m_time <= window_end and m_time <= now:
            m_subj = m.get("subject") or ""
            if msg_id in m.get("body", "") or (subject and subject.lower() in m_subj.lower()):
                if best_fwd_time is None or m_time < best_fwd_time:
                    best_fwd_time = m_time
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

    # Retrieve current label state for this message as of now
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    orig_msg: dict[str, Any] | None = None
    if msg_id:
        try:
            orig_msg = world.get_message(msg_id, as_of=now_iso)  # type: ignore[call-arg]
        except TypeError:
            orig_msg = world.get_message(msg_id)
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
