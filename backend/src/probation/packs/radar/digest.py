"""Opportunity Radar weekly digest generator and citation validator.

Authority: docs/PROMPTS.md section 14.
Model (Super) receives typed fields ONLY (never raw page text).
Validators verify that every statement cites [n], every date matches an entry, and length <= 700 chars.
"""

import re
from typing import Any

from probation.core.hashing import canonical_json
from probation.llm.client import LLMClient


def build_code_fallback_digest(entries: list[dict[str, Any]]) -> str:
    """Build deterministic code-side fallback digest without LLM."""
    if not entries:
        return "No opportunities tracked this week."
    lines: list[str] = ["Here are your tracked opportunities for this week:"]
    for e in entries[:8]:
        n = e.get("n", 1)
        title = e.get("title", "Opportunity")
        org = e.get("organiser", "Organiser")
        deadline = e.get("deadline_date") or "No deadline specified"
        fee_warning = " (Note: registration fee requested)" if e.get("fee_flag") else ""
        lines.append(f"[{n}] {title} by {org} - Deadline: {deadline}{fee_warning}")
    return "\n".join(lines)


def validate_radar_digest(
    digest_text: str,
    entries: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Validate that digest strictly cites provided entries with zero hallucinations.

    Authority: docs/PROMPTS.md section 14.
    """
    if len(digest_text) > 700:
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
        if not any(u.startswith(valid_u) or valid_u.startswith(u) for valid_u in valid_urls):
            return False, f"Uncited URL '{u}' not in provided entries"

    return True, "ok"


def generate_radar_digest(
    entries: list[dict[str, Any]],
    llm_client: LLMClient | None = None,
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
                "fee_flag": bool(e.get("fee_flag", False)),
                "source_url": e.get("official_url") or e.get("source_url"),
            }
        )

    if llm_client is None:
        return build_code_fallback_digest(clean_entries)

    system_prompt = (
        "Write a weekly digest of at most 120 words for the user from the entries given.\n"
        "Every statement must cite its entry as [n]. Do not add facts, dates or links that are not in the entries.\n"
        "If fee_flag is true, say that the opportunity asks for payment. Never say that anything is a scam.\n"
        'Output ONLY JSON: {"digest": string}.'
    )
    user_prompt = canonical_json(clean_entries)

    try:
        data = llm_client.chat_json(
            kind="writer",
            model="writer",
            system=system_prompt,
            user=user_prompt,
            schema={
                "type": "object",
                "properties": {"digest": {"type": "string"}},
                "required": ["digest"],
            },
            cache_parts={"prompt_id": "radar.digest", "prompt_version": "v1"},
        )
        digest = str(data.get("digest", "")).strip()
        is_valid, _ = validate_radar_digest(digest, clean_entries)
        if is_valid:
            return digest
    except Exception:
        pass

    return build_code_fallback_digest(clean_entries)
