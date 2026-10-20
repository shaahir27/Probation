"""Opportunity Radar deterministic clue extraction.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 8.1 and docs/CONTRACT.md invariant I-21.
Clues are deterministic and strictly from user history (NO web facts).
"""

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import publicsuffix2

from probation.config import settings
from probation.core.clock import Clock
from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.packs.mail.clues import FREEMAIL_DOMAINS

PLATFORM_DOMAINS = frozenset(
    {
        "unstop.com",
        "devfolio.co",
        "hackerearth.com",
        "devpost.com",
        "internshala.com",
        "kaggle.com",
        "codechef.com",
        "leetcode.com",
    }
)


def extract_organiser_domain_class(domain_or_url: str | None) -> str:
    """Classify organiser domain: edu, corp, gov, platform, freemail, other."""
    if not domain_or_url:
        return "other"
    clean = domain_or_url.strip().lower()
    if "/" in clean:
        clean = (urlparse(clean).hostname or clean).lower()
    sld = publicsuffix2.get_sld(clean)
    registrable = str(sld).lower() if sld else clean

    if registrable in PLATFORM_DOMAINS:
        return "platform"
    if registrable in FREEMAIL_DOMAINS:
        return "freemail"
    if clean.endswith(".edu") or ".edu." in clean or ".ac." in clean:
        return "edu"
    if clean.endswith(".gov") or ".gov." in clean or clean.endswith(".nic.in"):
        return "gov"
    if "." in registrable and len(registrable.split(".")) >= 2:
        return "corp"
    return "other"


def extract_days_to_deadline_bucket(days: float | None) -> str:
    """Bucket days to deadline: none, <3, 3-7, 8-14, 15-30, >30."""
    if days is None or days < 0:
        return "none"
    if days < 3.0:
        return "<3"
    elif days <= 7.0:
        return "3-7"
    elif days <= 14.0:
        return "8-14"
    elif days <= 30.0:
        return "15-30"
    return ">30"


def extract_radar_clues(
    s: Situation,
    hist: HistoryView,
    payload: dict[str, Any] | None = None,
) -> dict[str, float | str | bool]:
    """Extract deterministic clues for an opportunity situation without web facts (Invariant I-21)."""
    p = payload or {}
    source_kind = "link" if s.variant == "link" or p.get("url") else "mail"

    sender_email = (
        p.get("from")
        or p.get("sender")
        or p.get("official_url")
        or p.get("url")
        or s.sender_key
        or ""
    )
    sender_domain = ""
    if "@" in sender_email:
        sender_domain = sender_email.split("@")[-1].strip().lower()
    elif sender_email:
        sender_domain = sender_email

    organiser_domain_class = extract_organiser_domain_class(sender_domain)

    # Time clues in USER_TZ
    tz = ZoneInfo(settings.user_tz)
    try:
        dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00")).astimezone(tz)
    except Exception:
        dt = Clock().now(tz)

    hour_of_day = dt.hour
    weekday = dt.weekday()

    # Deadline estimation from mail or opportunity payload
    deadline_text = p.get("deadline_text") or p.get("deadline") or p.get("deadline_date") or ""
    has_deadline_in_mail = bool(deadline_text)
    days_to_deadline: float | None = None

    if has_deadline_in_mail:
        try:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", str(deadline_text))
            if m:
                dead_dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=ZoneInfo("UTC"))
                occ_dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00"))
                days_to_deadline = (dead_dt - occ_dt).total_seconds() / 86400.0
        except Exception:
            days_to_deadline = None

    days_to_deadline_bucket = extract_days_to_deadline_bucket(days_to_deadline)

    # History queries bounded strictly by as_of=s.occurred_at
    prior_sits = hist.get_situations(pack="radar")
    prior_ids_for_organiser: list[str] = []
    for sit_row in prior_sits:
        if sit_row["id"] == s.id:
            continue
        if sit_row["sender_key"] and sit_row["sender_key"] == s.sender_key:
            prior_ids_for_organiser.append(sit_row["id"])

    n_prior_from_organiser = len(prior_ids_for_organiser)
    organiser_known = n_prior_from_organiser > 0

    # History rates for tracked opportunities
    tracked_share_for_opp_type = 0.5
    tracked_share_for_topic = 0.5

    if prior_sits:
        all_prior_ids = [r["id"] for r in prior_sits if r["id"] != s.id]
        if all_prior_ids:
            outcomes = hist.get_outcomes(situation_ids=all_prior_ids)
            tracked_count = sum(1 for o in outcomes if str(o["observed_action"]) == "TRACK")
            total_outcomes = len(outcomes)
            tracked_share_for_opp_type = (tracked_count + 1.0) / (total_outcomes + 2.0)
            tracked_share_for_topic = (tracked_count + 1.0) / (total_outcomes + 2.0)

    return {
        "source_kind": source_kind,
        "organiser_domain_class": organiser_domain_class,
        "organiser_known": organiser_known,
        "n_prior_from_organiser": n_prior_from_organiser,
        "hour_of_day": hour_of_day,
        "weekday": weekday,
        "has_deadline_in_mail": has_deadline_in_mail,
        "days_to_deadline_bucket_from_mail": days_to_deadline_bucket,
        "tracked_share_for_opp_type": float(tracked_share_for_opp_type),
        "tracked_share_for_topic": float(tracked_share_for_topic),
    }
