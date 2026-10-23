"""Mail pack deterministic clue extraction via HistoryView.

Authority: docs/PACKS_SPEC.md sections 0.1-0.3 and 1.1-1.3.
Enforces Invariant I-6: History is read strictly through HistoryView(as_of=t).
"""

import statistics
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from probation.config import settings
from probation.core.clock import get_clock
from probation.core.history import HistoryView
from probation.core.identity import (
    AUTOMATED_LOCAL_PARTS,
    FREEMAIL_DOMAINS,
    classify_domain,
    extract_domain,
    is_automated_sender,
    normalize_address,
    normalize_user_addresses,
)
from probation.core.types import Situation

__all__ = [
    "AUTOMATED_LOCAL_PARTS",
    "FREEMAIL_DOMAINS",
    "classify_domain",
    "extract_domain",
    "extract_mail_clues",
    "is_automated_sender",
    "normalize_address",
]


def extract_mail_clues(
    s: Situation,
    hist: HistoryView,
    raw_payload: dict[str, Any] | None = None,
    user_addresses: list[str] | str | None = None,
) -> dict[str, float | str | bool]:
    """Compute all 16 deterministic clues for a mail situation strictly via HistoryView."""
    payload = raw_payload or {}
    from_raw = payload.get("from") or s.sender_key or ""
    sender_key = s.sender_key or normalize_address(from_raw)
    domain = extract_domain(sender_key)
    sender_domain_class = classify_domain(domain)

    # 1. Automated checks
    has_unsub = bool(
        payload.get("has_unsubscribe")
        or payload.get("list_unsubscribe")
        or (isinstance(payload.get("headers"), dict) and payload["headers"].get("List-Unsubscribe"))
    )
    is_noreply = is_automated_sender(sender_key, payload.get("headers"))

    # 2. Time-of-day clues in user's timezone
    tz_str = settings.user_tz or "Asia/Kolkata"
    try:
        user_tz = ZoneInfo(tz_str)
    except Exception:
        user_tz = ZoneInfo("Asia/Kolkata")

    try:
        occ_dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00")).astimezone(user_tz)
    except Exception:
        occ_dt = get_clock().now(user_tz)

    hour_of_day = occ_dt.hour
    weekday = occ_dt.weekday()  # 0=Monday, 6=Sunday
    is_weekend = weekday >= 5

    # 3. Context clues from payload
    to_field = payload.get("to") or ""
    cc_field = payload.get("cc") or ""
    # Parsed as an RFC 2822 address list, not split on commas: a quoted display name such as
    # "Krishnamurthy, Meena" contains a comma and would otherwise count as two recipients.
    recipients = normalize_user_addresses([str(to_field), str(cc_field)])
    n_recipients = max(1, len(recipients))
    has_attachment = bool(payload.get("has_attachment", False))

    body_text = payload.get("body") or s.redacted_text or ""
    body_len = len(body_text)
    if body_len < 300:
        body_len_bucket = "short"
    elif body_len < 1500:
        body_len_bucket = "medium"
    else:
        body_len_bucket = "long"

    # 4. History queries bounded by hist (known_at <= s.occurred_at)
    msg_id = payload.get("message_id") or ""
    in_reply_to = payload.get("in_reply_to") or ""

    user_addrs = normalize_user_addresses(
        user_addresses if user_addresses is not None else settings.user_addresses
    )

    # High-performance indexed lookups strictly bounded by hist.as_of (Invariant I-6)
    n_prior_in = hist.count_prior_sender_messages(sender_key, exclude_situation_id=s.id)
    n_prior_replied = hist.count_prior_sender_replies(sender_key, exclude_situation_id=s.id)
    reply_deltas_hours = hist.get_prior_sender_reply_deltas(sender_key, exclude_situation_id=s.id)
    n_prior_sent = hist.count_prior_sent_to_recipient(sender_key)
    n_prior_total = n_prior_in + n_prior_sent

    thread_msgs, user_sent_in_thread = hist.get_prior_thread_stats(
        msg_id=msg_id,
        in_reply_to=in_reply_to,
        user_addresses=user_addrs,
        current_raw_item_id=s.raw_item_id,
    )

    reply_rate_sender = (n_prior_replied + 1.0) / (n_prior_in + 2.0)
    median_reply_hours = (
        float(statistics.median(reply_deltas_hours)) if reply_deltas_hours else -1.0
    )

    # Sender Tier per docs/PACKS_SPEC.md section 0.3 & 1.2
    if is_noreply or has_unsub:
        sender_tier = "automated"
    elif n_prior_total >= 10:
        sender_tier = "frequent"
    elif n_prior_total >= 1:
        sender_tier = "known"
    else:
        sender_tier = "unknown"

    return {
        "sender_tier": sender_tier,
        "sender_domain_class": sender_domain_class,
        "n_prior_in": n_prior_in,
        "n_prior_replied": n_prior_replied,
        "reply_rate_sender": round(reply_rate_sender, 4),
        "median_reply_hours_sender": round(median_reply_hours, 2),
        "has_unsubscribe": has_unsub,
        "is_noreply": is_noreply,
        "hour_of_day": hour_of_day,
        "weekday": weekday,
        "is_weekend": is_weekend,
        "n_recipients": n_recipients,
        "has_attachment": has_attachment,
        "in_thread_user_participated": user_sent_in_thread,
        "thread_length": thread_msgs,
        "body_len_bucket": body_len_bucket,
    }
