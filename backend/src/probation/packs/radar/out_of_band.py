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

import sqlite3
from typing import Any
from urllib.parse import urlparse

import publicsuffix2

from probation.core.clock import Clock, get_clock
from probation.llm.consumers import RegisteredConsumer
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
    *,
    official_domains: frozenset[str] = frozenset(),
    consumer: RegisteredConsumer | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Execute out-of-band Tavily Search and Extract verification flow."""
    if consumer is not None:
        from probation.web.verification import verify_email_opportunity

        card = verify_email_opportunity(
            conn,
            client,
            consumer,
            organiser_name=organiser_name,
            opportunity_name=opportunity_name,
            clock=clock or get_clock(),
            mail_deadline=mail_deadline,
            mail_link_domains=mail_link_domains,
            situation_id=situation_id,
        )
        source = card.citations[0] if card.citations else None
        return {
            "verified": card.availability in {"validated", "partial"},
            "extraction_status": card.availability,
            "status": "confirmed_official" if card.availability == "validated" else "unverified",
            "official_url": source.url if source else None,
            "official_domain": _get_registrable_domain(source.url) if source else None,
            "link_mismatch": card.fields.get("link_mismatch", False),
            "discrepancy": card.fields.get("deadline_discrepancy"),
            "fields": card.fields,
            "sources": [source.model_dump() for source in card.citations],
            "verification_card": card.model_dump(),
        }
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

    # This allowlist comes from reviewed public-entity provenance in the Webfacts
    # caller, never a browser field. Search rank alone grants no official authority.
    official_url: str | None = None
    official_domain: str | None = None
    sources: list[dict[str, Any]] = []

    for r in results:
        u = r.get("url", "")
        t = r.get("title", "")
        dom = _get_registrable_domain(u)
        if not official_url and dom in official_domains:
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

    # Legacy candidate inspection has no extraction authority or generated fields.
    return {
        "verified": official_url is not None,
        "extraction_status": "unavailable",
        "status": "confirmed_official" if official_url else "unverified",
        "official_url": official_url,
        "official_domain": official_domain,
        "link_mismatch": link_mismatch,
        "discrepancy": None,
        "fields": {},
        "sources": sources,
    }
