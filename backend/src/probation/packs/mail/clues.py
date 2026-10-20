"""Mail pack deterministic clue extraction via HistoryView.

Authority: docs/PACKS_SPEC.md sections 0.1-0.3 and 1.1-1.3.
Enforces Invariant I-6: History is read strictly through HistoryView(as_of=t).
"""

import email.utils
import json
import re
import statistics
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from probation.config import settings
from probation.core.clock import Clock
from probation.core.history import HistoryView
from probation.core.types import Situation

FREEMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "zoho.com",
        "aol.com",
        "gmx.com",
        "mail.com",
        "yandex.com",
    }
)

AUTOMATED_LOCAL_PARTS = frozenset(
    {
        "noreply",
        "no-reply",
        "donotreply",
        "do-not-reply",
        "notifications",
        "notification",
        "newsletter",
        "mailer-daemon",
        "postmaster",
    }
)


def normalize_address(addr: str) -> str:
    """Normalize email address per docs/PACKS_SPEC.md section 0.2.

    Lower-case, strip display names, and strip +tag from local part.
    """
    if not addr:
        return ""
    _, clean_addr = email.utils.parseaddr(addr)
    if not clean_addr:
        clean_addr = addr.strip()
    clean_addr = clean_addr.lower().strip()
    if "@" in clean_addr:
        local, domain = clean_addr.split("@", 1)
        local_base = local.split("+", 1)[0]
        return f"{local_base}@{domain}"
    return clean_addr


def extract_domain(addr: str) -> str:
    """Extract domain from an address string."""
    norm = normalize_address(addr)
    if "@" in norm:
        return norm.split("@", 1)[1]
    return ""


def classify_domain(domain: str) -> str:
    """Classify domain into edu, freemail, corp, or other per docs/PACKS_SPEC.md section 0.2."""
    d = domain.lower().strip()
    if not d:
        return "other"
    if d in FREEMAIL_DOMAINS:
        return "freemail"
    if (
        d.endswith(".edu")
        or re.search(r"\.edu\.[a-z]{2,3}$", d)
        or re.search(r"\.ac\.[a-z]{2,3}$", d)
    ):
        return "edu"
    if "." in d:
        return "corp"
    return "other"


def is_automated_sender(
    from_addr: str,
    headers: dict[str, Any] | None = None,
) -> bool:
    """Check if sender is automated per docs/PACKS_SPEC.md section 1.2."""
    norm = normalize_address(from_addr)
    local_part = norm.split("@", 1)[0] if "@" in norm else norm
    if local_part in AUTOMATED_LOCAL_PARTS:
        return True

    if headers:
        if (
            headers.get("List-Unsubscribe")
            or headers.get("List-Id")
            or headers.get("list_unsubscribe")
        ):
            return True
        prec = str(headers.get("Precedence", "")).lower()
        if prec in ("bulk", "list"):
            return True

    return False


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
        occ_dt = Clock().now(user_tz)

    hour_of_day = occ_dt.hour
    weekday = occ_dt.weekday()  # 0=Monday, 6=Sunday
    is_weekend = weekday >= 5

    # 3. Context clues from payload
    to_field = payload.get("to") or ""
    cc_field = payload.get("cc") or ""
    recipients = [r for r in (to_field + "," + cc_field).split(",") if r.strip()]
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
    prior_raw_items = hist.get_raw_items(pack="mail")
    prior_situations = {row["id"]: row for row in hist.get_situations(pack="mail")}
    prior_outcomes = {row["situation_id"]: row for row in hist.get_outcomes()}

    n_prior_in = 0
    n_prior_total = 0
    n_prior_replied = 0
    reply_deltas_hours: list[float] = []

    # Thread tracking
    msg_id = payload.get("message_id") or ""
    in_reply_to = payload.get("in_reply_to") or ""
    thread_msgs = 0
    user_sent_in_thread = False
    if user_addresses is not None:
        if isinstance(user_addresses, str):
            user_addrs = [normalize_address(a) for a in user_addresses.split(",") if a.strip()]
        else:
            user_addrs = [normalize_address(a) for a in user_addresses if a.strip()]
    else:
        user_addrs = [normalize_address(a) for a in settings.user_addresses.split(",") if a.strip()]

    for row in prior_raw_items:
        if row["id"] == s.raw_item_id:
            continue
        try:
            p_payload = json.loads(row["payload_json"])
        except Exception:
            continue

        p_from = normalize_address(p_payload.get("from", ""))
        p_to = normalize_address(p_payload.get("to", ""))
        p_kind = row["item_kind"]

        # Thread analysis
        p_msg_id = p_payload.get("message_id", "")
        p_in_reply = p_payload.get("in_reply_to", "")

        is_same_thread = False
        if msg_id and (p_in_reply == msg_id or p_msg_id == in_reply_to):
            is_same_thread = True
        elif in_reply_to and p_in_reply == in_reply_to:
            is_same_thread = True

        if is_same_thread:
            thread_msgs += 1
            if p_kind == "mail_sent" or any(u in p_from for u in user_addrs):
                user_sent_in_thread = True

        # Sender interaction history
        is_from_sender = p_from == sender_key
        is_to_sender = sender_key in p_to

        if is_from_sender:
            n_prior_in += 1
            n_prior_total += 1

            # Check if this prior situation had an observed reply outcome
            p_sit_id = row["id"]
            for sit_id, sit_row in prior_situations.items():
                if sit_row["raw_item_id"] == p_sit_id:
                    outcome = prior_outcomes.get(sit_id)
                    if outcome and outcome["observed_action"] == "REPLY":
                        n_prior_replied += 1
                        try:
                            t_occ = datetime.fromisoformat(
                                sit_row["occurred_at"].replace("Z", "+00:00")
                            )
                            t_res = datetime.fromisoformat(
                                outcome["known_at"].replace("Z", "+00:00")
                            )
                            hours = (t_res - t_occ).total_seconds() / 3600.0
                            if hours >= 0:
                                reply_deltas_hours.append(hours)
                        except Exception:
                            pass
                    break
        elif is_to_sender:
            n_prior_total += 1

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
