"""Email verification card: independent Search, reviewed provenance and quarantine."""

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from probation.core.clock import Clock, parse_timestamp
from probation.db.access import Role, RoleAccess
from probation.links.extract import extract_url_content
from probation.links.extractor_jobs import extract_stored_page
from probation.links.sanitise import sanitise_url
from probation.llm.consumers import RegisteredConsumer
from probation.web.catalog import reviewed_entry
from probation.web.client import TavilyClient
from probation.web.derive import extract_registrable_domain
from probation.web.query_guard import validate_tavily_query
from probation.web.types import Citation, OfficialSearchReference, VerificationCard


def normalize_deadline(value: str | None) -> str | None:
    """Only complete unambiguous calendar dates; timed deadlines need a timezone."""
    if not value or (
        re.search(r"\d{1,2}:\d{2}", value)
        and not re.search(r"\b(?:UTC|GMT|IST|PST|PDT|EST|EDT)\b|[+-]\d{2}:?\d{2}", value, re.I)
    ):
        return None
    match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", value)
    if match:
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            return None
    text = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", value.strip(), flags=re.I)
    for pattern in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    return None


def _cached_search(conn: sqlite3.Connection, query: str, now: str) -> dict[str, Any] | None:
    """Safe citation-only replay of a recorded successful physical Search."""
    try:
        rows = conn.execute(
            "SELECT id,params_json,reconciled_at FROM tavily_calls WHERE endpoint='search' "
            "AND purpose='find_official' AND query_text=? AND ok=1 AND accounting_version=1 "
            "ORDER BY reconciled_at COLLATE UTC_TIMESTAMP DESC LIMIT 20",
            (query,),
        ).fetchall()
        for row in rows:
            fetched = parse_timestamp(row["reconciled_at"])
            if not fetched <= parse_timestamp(now) < fetched + timedelta(days=7):
                continue
            params = json.loads(row["params_json"])
            if (
                params.get("search_depth") != "basic"
                or params.get("max_results") != 5
                or params.get("include_answer") is not False
                or params.get("include_raw_content") is not False
            ):
                continue
            sources = params.get("result_sources")
            if isinstance(sources, list):
                return {
                    "status": "ok",
                    "results": sources,
                    "attempt_id": row["id"],
                    "fetched_at": row["reconciled_at"],
                    "cached": True,
                }
    except (sqlite3.Error, ValueError, TypeError):
        return None
    return None


def _candidate(
    results: list[dict[str, Any]], domains: frozenset[str], name: str
) -> tuple[str, str] | None:
    words = {
        word
        for word in re.findall(r"[a-z0-9]+", name.casefold())
        if len(word) >= 3 and word not in {"the", "and", "official", "program", "programme"}
    }
    if not words:
        return None
    candidates: dict[str, str] = {}
    for result in results:
        url, reason = sanitise_url(str(result.get("url", "")))
        if reason or extract_registrable_domain(url) not in domains:
            continue
        title = re.sub(r"<[^>]*>", "", str(result.get("title", "")))[:300]
        title_words = set(re.findall(r"[a-z0-9]+", title.casefold()))
        if words <= title_words:
            candidates[url] = title
    # Reviewed domain plus distinctive name words; generic program suffixes may be omitted.
    if len(candidates) != 1:
        return None
    return next(iter(candidates.items()))


def verify_email_opportunity(
    conn: sqlite3.Connection,
    client: TavilyClient,
    consumer: RegisteredConsumer | None,
    *,
    organiser_name: str | None,
    opportunity_name: str | None,
    clock: Clock,
    mail_deadline: str | None = None,
    mail_link_domains: list[str] | None = None,
    situation_id: str | None = None,
) -> VerificationCard:
    """Called only after the validated opportunity form. Creates no Radar action."""
    if consumer is None:
        return VerificationCard(availability="unavailable", reasons=["quarantine_unavailable"])
    organiser, opportunity = (organiser_name or "").strip(), (opportunity_name or "").strip()
    query = f"{organiser} {opportunity} official".strip()
    if not organiser or not opportunity or not validate_tavily_query(query)[0]:
        return VerificationCard(availability="not_checked", reasons=["public_query_unavailable"])
    entry = reviewed_entry(organiser, as_of=clock.now_iso())
    if entry is None:
        return VerificationCard(
            availability="not_checked", reasons=["reviewed_organiser_unavailable"]
        )
    response = _cached_search(conn, query, clock.now_iso())
    if response is None:
        response = client.search(
            query,
            purpose="find_official",
            search_depth="basic",
            max_results=5,
            situation_id=situation_id,
        )
    if response.get("status") != "ok":
        return VerificationCard(availability="not_checked", reasons=["official_search_unavailable"])
    results = response.get("results")
    selected = _candidate(
        results if isinstance(results, list) else [], entry.official_domains, opportunity
    )
    if selected is None:
        return VerificationCard(
            availability="unavailable", reasons=["official_candidate_ambiguous_or_missing"]
        )
    url, title = selected
    reference = OfficialSearchReference(
        search_attempt_id=str(response.get("attempt_id") or ""),
        entity_key=extract_registrable_domain(url),
        url=url,
        catalog_brand=entry.brand,
        catalog_version=entry.version,
        catalog_source_url=entry.source_url,
        catalog_verified_at=entry.verified_at,
        discovered_at=str(response.get("fetched_at") or ""),
    )
    extracted = extract_url_content(
        url, conn, client, official_reference=reference, now_iso=clock.now_iso()
    )
    if not extracted.get("ok"):
        return VerificationCard(
            availability="unavailable",
            reasons=[str(extracted["error"])],
            citations=[Citation(title=title, url=url)],
        )
    try:
        output = extract_stored_page(
            RoleAccess(conn, Role.WEBFACTS),
            consumer,
            extraction_id=str(extracted["extraction_id"]),
            kind="opportunity",
            clock=clock,
        )
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return VerificationCard(availability="unavailable", reasons=["quarantine_unavailable"])
    fields = dict(output.get("fields", {}))
    if not fields:
        return VerificationCard(
            availability="unavailable",
            reasons=[str(output.get("reason", "quarantine_unavailable"))],
        )
    validated = bool(output.get("ok"))
    reasons = list(output.get("notes", []))
    organiser_value = fields.get("organiser")
    if organiser_value and str(organiser_value).casefold() != entry.brand:
        fields["organiser"] = None
        validated = False
        reasons.append("organiser_role_unverified")
    page_deadline = fields.get("deadline_date")
    mail_date = normalize_deadline(mail_deadline)
    if mail_date and page_deadline:
        fields["mail_deadline_date"] = mail_date
        fields["deadline_discrepancy"] = mail_date != page_deadline
    domains = {extract_registrable_domain(domain) for domain in mail_link_domains or []}
    fields["link_mismatch"] = bool(domains and reference.entity_key not in domains)
    raw_provenance = output.get("provenance", {})
    provenance = {
        key: value
        for key, value in raw_provenance.items()
        if value is None or isinstance(value, (str, int, bool))
    }
    provenance.update(
        search_attempt_id=reference.search_attempt_id,
        search_origin="cache" if response.get("cached") else "live",
        catalog_version=entry.version,
        catalog_source_url=entry.source_url,
        extraction_origin="cache" if extracted.get("cached") else "live",
        redirect_validation="returned_url_identity_only",
    )
    return VerificationCard(
        availability="validated" if validated else "partial",
        fields=fields,
        fee_status=output.get("fee_status", "unknown"),
        citations=[Citation(title=title, url=url)],
        reasons=reasons,
        extraction_id=str(extracted["extraction_id"]),
        fetched_at=output.get("fetched_at"),
        ttl_until=output.get("ttl_until"),
        provenance=provenance,
    )
