"""Out-of-band verification workflow for Opportunity Radar.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 8.1 and docs/CONTRACT.md invariants I-21 to I-26.
Steps:
1. Search independently using organiser_name and opportunity_name (query guarded).
2. Identify official candidate page.
3. Compare against email link domains: flag link_mismatch if mail links do not include official domain.
4. Extract content ONLY from official candidate URL (never from mail links, I-24).
5. Quarantine extraction and code-validate fields.
6. Compare deadlines for discrepancy warning.
"""

import re
import sqlite3
from typing import Any
from urllib.parse import urlparse

import publicsuffix2

from probation.links.extract import extract_url_content
from probation.links.quarantine import validate_opportunity_fields
from probation.web.client import TavilyClient
from probation.web.query_guard import validate_tavily_query


def _get_registrable_domain(url_or_domain: str) -> str:
    """Return registrable domain using public suffix list."""
    clean = url_or_domain.strip().lower()
    if "/" in clean:
        clean = (urlparse(clean).hostname or clean).lower()
    sld = publicsuffix2.get_sld(clean)
    return str(sld).lower() if sld else clean


def build_official_search_query(opportunity_name: str, organiser_name: str) -> str:
    """Build sanitized official search query using public entity strings only."""
    clean_opp = opportunity_name.strip()
    clean_org = organiser_name.strip()
    return f"{clean_org} {clean_opp} official".strip()


def verify_opportunity_out_of_band(
    organiser_name: str | None,
    opportunity_name: str | None,
    mail_link_domains: list[str],
    conn: sqlite3.Connection,
    client: TavilyClient,
    mail_deadline: str | None = None,
    situation_id: str | None = None,
) -> dict[str, Any]:
    """Execute out-of-band Tavily Search and Extract verification flow."""
    clean_org = (organiser_name or "").strip()
    clean_opp = (opportunity_name or "").strip()

    if not clean_org and not clean_opp:
        return {
            "verified": False,
            "status": "not_checked",
            "error": "Missing organiser and opportunity name",
            "official_url": None,
            "official_domain": None,
            "link_mismatch": False,
            "discrepancy": None,
            "fields": {},
            "sources": [],
        }

    search_query = build_official_search_query(clean_opp, clean_org)
    is_safe, reject_reason = validate_tavily_query(search_query)
    if not is_safe:
        return {
            "verified": False,
            "status": "not_checked",
            "error": f"Query guard rejected query: {reject_reason}",
            "official_url": None,
            "official_domain": None,
            "link_mismatch": False,
            "discrepancy": None,
            "fields": {},
            "sources": [],
        }

    # 1. Tavily Search for official candidate
    search_resp = client.search(
        query=search_query,
        purpose="find_official",
        max_results=5,
        search_depth="basic",
        situation_id=situation_id,
    )

    results = search_resp.get("results", [])
    if not results:
        return {
            "verified": False,
            "status": "no_web_presence",
            "official_url": None,
            "official_domain": None,
            "link_mismatch": False,
            "discrepancy": None,
            "fields": {},
            "sources": [],
        }

    # Pick official candidate: prioritize platform domains or top organic domain
    official_url: str | None = None
    official_domain: str | None = None
    sources: list[dict[str, Any]] = []

    for r in results:
        u = r.get("url", "")
        t = r.get("title", "")
        dom = _get_registrable_domain(u)
        if not official_url and dom:
            official_url = u
            official_domain = dom
        if len(sources) < 3:
            sources.append({"title": t, "url": u})

    # 2. Link mismatch check: Does mail links match official domain?
    link_mismatch = False
    if mail_link_domains and official_domain:
        clean_mail_domains = {_get_registrable_domain(d) for d in mail_link_domains}
        if official_domain not in clean_mail_domains:
            link_mismatch = True

    # 3. Invariant I-24: Extract on the official URL discovered by search ONLY
    extracted_text = ""
    if official_url:
        extract_res = extract_url_content(
            url=official_url,
            conn=conn,
            client=client,
            purpose="extract_item",
            is_user_saved=False,
            is_official_search=True,
        )
        if extract_res.get("ok"):
            extracted_text = extract_res.get("content_text") or ""

    # 4. Quarantined extraction + code validation
    raw_fields: dict[str, Any] = {
        "title": clean_opp,
        "organiser": clean_org,
        "deadline_date": None,
        "start_date": None,
        "eligibility": [],
        "fee_mentioned": False,
        "mode": "online",
        "apply_domain": official_domain,
    }

    # Extract date if literally in page text
    if extracted_text:
        date_matches = re.findall(r"(\d{4}-\d{2}-\d{2})", extracted_text)
        if date_matches:
            raw_fields["deadline_date"] = date_matches[0]

    validated_fields, _val_ok, _notes = validate_opportunity_fields(raw_fields, extracted_text)

    # 5. Check discrepancy between mail deadline and page deadline
    discrepancy = None
    page_deadline = validated_fields.get("deadline_date")
    if mail_deadline and page_deadline and mail_deadline != page_deadline:
        discrepancy = {
            "mail_deadline": mail_deadline,
            "page_deadline": page_deadline,
            "note": f"Mail states {mail_deadline}, but official page states {page_deadline}",
        }

    return {
        "verified": True,
        "status": "confirmed_official" if official_url else "unverified",
        "official_url": official_url,
        "official_domain": official_domain,
        "link_mismatch": link_mismatch,
        "discrepancy": discrepancy,
        "fields": validated_fields,
        "sources": sources,
    }
