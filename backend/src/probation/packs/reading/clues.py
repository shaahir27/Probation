"""Reading Triage pack deterministic clue extraction.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 9.1 and docs/PACKS_SPEC.md section 5b.
Clues are computed deterministically through HistoryView.
"""

from collections import Counter
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import publicsuffix2

from probation.config import settings
from probation.core.history import HistoryView
from probation.core.types import Situation


def extract_path_kind(url: str) -> str:
    """Classify URL path kind: article, video, pdf, repo, doc, other."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    netloc = (parsed.hostname or "").lower()

    if path.endswith(".pdf"):
        return "pdf"
    if "youtube.com" in netloc or "vimeo.com" in netloc or "/video" in path or "/watch" in path:
        return "video"
    if "github.com" in netloc or "gitlab.com" in netloc or "/repo" in path:
        return "repo"
    if (
        "docs." in netloc
        or "/docs" in path
        or "/doc" in path
        or "documentation" in path
        or "readmes" in path
    ):
        return "doc"
    if "/article" in path or "/blog" in path or "/post" in path or "/p/" in path:
        return "article"
    return "other"


def extract_reading_clues(
    s: Situation,
    hist: HistoryView,
    payload: dict[str, Any] | None = None,
) -> dict[str, float | str | bool]:
    """Extract clues for a saved link situation bounded strictly by as_of."""
    p = payload or {}
    url = str(p.get("url") or s.sender_key or "")
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    sld = publicsuffix2.get_sld(hostname)
    url_domain = str(sld).lower() if sld else (hostname or "unknown")

    path_kind = extract_path_kind(url)
    has_pdf_ext = parsed.path.lower().endswith(".pdf")

    # Time clues
    tz = ZoneInfo(settings.user_tz)
    try:
        dt = datetime.fromisoformat(s.occurred_at.replace("Z", "+00:00")).astimezone(tz)
    except Exception:
        dt = datetime.now(tz)

    hour_of_day = dt.hour
    weekday = dt.weekday()

    # Prior history from this domain
    prior_sits = hist.get_situations(pack="reading")
    prior_ids_for_domain: list[str] = []
    for sit_row in prior_sits:
        if sit_row["id"] == s.id:
            continue
        if sit_row["sender_key"] == url_domain:
            prior_ids_for_domain.append(sit_row["id"])

    n_prior_from_domain = len(prior_ids_for_domain)
    top_collection_for_domain = "none"
    top_collection_share = 0.5

    if prior_ids_for_domain:
        outcomes = hist.get_outcomes(situation_ids=prior_ids_for_domain)
        collections: list[str] = []
        for o in outcomes:
            act = str(o["observed_action"])
            if act.startswith("FILE_TO_COLLECTION:"):
                col = act.split("FILE_TO_COLLECTION:", 1)[1].strip()
                if col:
                    collections.append(col)
        if collections:
            counts = Counter(collections)
            top_col, top_count = counts.most_common(1)[0]
            top_collection_for_domain = top_col
            top_collection_share = (top_count + 1.0) / (n_prior_from_domain + 2.0)
        else:
            top_collection_share = 1.0 / (n_prior_from_domain + 2.0)

    # Content clues (from user-saved content)
    topic = str(p.get("topic", "other"))
    content_type = str(p.get("content_type", "article"))
    actionable = bool(p.get("actionable", False))

    content_len = len(str(p.get("content_text", "")))
    if content_len < 1500:
        length_bucket = "short"
    elif content_len < 5000:
        length_bucket = "medium"
    else:
        length_bucket = "long"

    return {
        "source_kind": "link",
        "url_domain": url_domain,
        "path_kind": path_kind,
        "has_pdf_ext": has_pdf_ext,
        "hour_of_day": hour_of_day,
        "weekday": weekday,
        "n_prior_from_domain": n_prior_from_domain,
        "top_collection_for_domain": top_collection_for_domain,
        "top_collection_share": float(top_collection_share),
        "topic": topic,
        "content_type": content_type,
        "actionable": actionable,
        "length_bucket": length_bucket,
    }
