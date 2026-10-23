"""Opportunity Radar weekly digest generator and citation validator.

Authority: docs/PROMPTS.md section 14.
Model (Super) receives typed fields ONLY (never raw page text).
Validators verify that every statement cites [n], every date matches an entry, and length <= 700 chars.
"""

import re
from typing import Any

from probation.core.hashing import canonical_json
from probation.llm.consumers import RegisteredConsumer
from probation.llm.gateway import JobFailure
from probation.llm.prompt_loader import PromptAssetError


def build_code_fallback_digest(entries: list[dict[str, Any]]) -> str:
    """Build deterministic code-side fallback digest without LLM."""
    if not entries:
        return "No opportunities tracked this week."
    lines: list[str] = ["Here are your tracked opportunities for this week:"]
    for e in entries[:8]:
        n = e.get("n", 1)
        title = " ".join(str(e.get("title", "Opportunity")).split())[:80]
        org = " ".join(str(e.get("organiser", "Organiser")).split())[:60]
        deadline = e.get("deadline_date") or "No deadline specified"
        fee_warning = " (Note: registration fee requested)" if e.get("fee_flag") is True else ""
        line = f"[{n}] {title} by {org} - Deadline: {deadline}{fee_warning}"
        candidate = "\n".join([*lines, line])
        if len(candidate) > 700 or len(candidate.split()) > 120:
            break
        lines.append(line)
    return "\n".join(lines)


def validate_radar_digest(
    digest_text: str,
    entries: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Validate that digest strictly cites provided entries with zero hallucinations.

    Authority: docs/PROMPTS.md section 14.
    """
    if len(digest_text) > 700 or len(digest_text.split()) > 120:
        return False, f"Digest length {len(digest_text)} exceeds 700 characters"

    valid_ns = {str(e.get("n", i + 1)) for i, e in enumerate(entries)}
    valid_dates = {str(e.get("deadline_date")) for e in entries if e.get("deadline_date")}
    valid_urls = {
        str(e.get("source_url") or e.get("official_url"))
        for e in entries
        if e.get("source_url") or e.get("official_url")
    }

    # 1. Every citation [n] must exist in input
    citations = re.findall(r"\[(\d+)\]", digest_text)
    if not citations and entries:
        return False, "Digest missing citations [n]"

    for cit in citations:
        if cit not in valid_ns:
            return False, f"Invalid citation [{cit}] not in provided entries"

    # 2. Every date in the text must match a provided deadline_date
    dates_found = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", digest_text)
    for d in dates_found:
        if d not in valid_dates:
            return False, f"Uncited date '{d}' not in provided entries"

    # 3. Any URL in text must match a provided source_url
    urls_found = re.findall(r"https?://[^\s)\]]+", digest_text)
    for u in urls_found:
        if u.rstrip(".,;!") not in valid_urls:
            return False, f"Uncited URL '{u}' not in provided entries"

    return True, "ok"


def generate_radar_digest(
    entries: list[dict[str, Any]],
    llm_client: RegisteredConsumer | None = None,
) -> str:
    """Generate weekly Opportunity Radar digest with strict code fallback on validation failure."""
    if not entries:
        return "No opportunities tracked this week."

    clean_entries = []
    for i, e in enumerate(entries[:8]):
        clean_entries.append(
            {
                "n": i + 1,
                "title": str(e.get("title", ""))[:80],
                "organiser": str(e.get("organiser") or e.get("organizer", ""))[:60],
                "type": str(e.get("opp_type") or e.get("type", "other")),
                "deadline_date": e.get("deadline_date"),
                "status": str(e.get("status", "TRACKED")),
                "fee_flag": e.get("fee_flag") is True,
                "source_url": e.get("official_url") or e.get("source_url"),
            }
        )

    if llm_client is None:
        return build_code_fallback_digest(clean_entries)

    if not isinstance(llm_client, RegisteredConsumer):
        return build_code_fallback_digest(clean_entries)
    try:
        result = llm_client.call(
            "radar.digest", {"entries": canonical_json(clean_entries)}, purpose="radar_digest"
        )
        digest = str(result.data["digest"]).strip()
        is_valid, _ = validate_radar_digest(digest, clean_entries)
        # Only emit model prose whose lexical assertions are supported by typed data.
        allowed = set(re.findall(r"\w+", canonical_json(clean_entries).casefold()))
        boilerplate = set(
            "here are your tracked opportunities for this week check out with deadline at by the and no specified note registration fee requested".split()
        )
        words = set(re.findall(r"\w+", digest.casefold()))
        if is_valid and words <= allowed | boilerplate:
            return digest
    except (JobFailure, PromptAssetError):
        pass
    return build_code_fallback_digest(clean_entries)
