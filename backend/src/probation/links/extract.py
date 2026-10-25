"""Provenance-bound, expiring page quarantine. No mail-body URL is fetchable."""

import hashlib
import json
import sqlite3
from datetime import timedelta
from typing import Any

from probation.config import settings
from probation.core.clock import format_timestamp, get_clock, parse_timestamp
from probation.core.hashing import canonical_json, det_id
from probation.db.access import Role, RoleAccess
from probation.links.sanitise import sanitise_url
from probation.web.client import TavilyClient
from probation.web.derive import extract_registrable_domain
from probation.web.types import OfficialSearchReference
from probation.web.view import WebFactsView

EXTRACTION_VERSION = "d5-extract-v1"


def _denied(code: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "content_text": None, "extraction_id": None}


def validate_search_reference(
    reference: OfficialSearchReference, conn: sqlite3.Connection, url: str, now: str
) -> bool:
    """Recheck persisted discovery and reviewed catalog; a model is no authority."""
    from probation.web.catalog import reviewed_entry

    try:
        entry = reviewed_entry(reference.catalog_brand, as_of=now)
        if entry is None or (
            entry.version != reference.catalog_version
            or entry.source_url != reference.catalog_source_url
            or entry.verified_at != reference.catalog_verified_at
            or reference.entity_key not in entry.official_domains
            or extract_registrable_domain(url) != reference.entity_key
            or reference.url != url
        ):
            return False
        row = conn.execute(
            "SELECT * FROM tavily_calls WHERE id=? AND endpoint='search' "
            "AND purpose='find_official' AND ok=1 AND accounting_version=1",
            (reference.search_attempt_id,),
        ).fetchone()
        if row is None:
            return False
        proof = json.loads(row["params_json"])
        discovered = parse_timestamp(reference.discovered_at)
        return (
            url in proof.get("result_urls", [])
            and reference.catalog_brand.casefold() in str(row["query_text"]).casefold()
            and reference.discovered_at == row["reconciled_at"]
            and discovered <= parse_timestamp(now) < discovered + timedelta(days=7)
        )
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return False


def extract_url_content(
    url: str,
    conn: sqlite3.Connection,
    client: TavilyClient,
    purpose: str = "extract_item",
    extract_depth: str = "basic",
    is_user_saved: bool = False,
    is_official_search: bool = False,
    now_iso: str | None = None,
    *,
    official_reference: OfficialSearchReference | None = None,
    query: str = "deadline eligibility fee registration",
    chunks_per_source: int = 3,
    format: str = "markdown",
) -> dict[str, Any]:
    """Only trusted saved intake or independently persisted official Search can fetch."""
    clean_url, reason = sanitise_url(url)
    if reason:
        return _denied("url_hands_off")
    now = now_iso or get_clock().now_iso()
    if not is_user_saved and (
        official_reference is None
        or not validate_search_reference(official_reference, conn, clean_url, now)
    ):
        return _denied("Invariant I-24 violation: official Search provenance required")
    if extract_depth not in {"basic", "advanced"} or format not in {"markdown", "text"}:
        return _denied("unsupported_extract_options")
    if not 1 <= chunks_per_source <= 5:
        return _denied("unsupported_extract_options")
    try:
        facts = WebFactsView(conn).get_entity_facts(extract_registrable_domain(clean_url), now)
        if facts and facts.status in {"lookalike", "reports_found"}:
            return _denied("entity_veto")
        options = {
            "url": clean_url,
            "depth": extract_depth,
            "format": format,
            "query": query,
            "chunks": chunks_per_source,
            "version": EXTRACTION_VERSION,
        }
        query_hash = hashlib.sha256(canonical_json(options).encode()).hexdigest()
        cached = conn.execute(
            "SELECT * FROM extractions WHERE url_norm=? AND extract_depth=? AND query_hash LIKE ? "
            "AND fetched_at COLLATE UTC_TIMESTAMP <= ? AND ttl_until COLLATE UTC_TIMESTAMP > ? "
            "ORDER BY fetched_at COLLATE UTC_TIMESTAMP DESC,id DESC LIMIT 1",
            (clean_url, extract_depth, query_hash + ":%", now, now),
        ).fetchone()
        if (
            cached
            and cached["ok"]
            and (
                parse_timestamp(cached["fetched_at"])
                <= parse_timestamp(now)
                < parse_timestamp(cached["ttl_until"])
            )
            and hashlib.sha256(str(cached["content_text"]).encode()).hexdigest()
            == cached["content_hash"]
        ):
            return {
                "ok": True,
                "content_text": cached["content_text"][: settings.quarantine_max_input_chars],
                "extraction_id": cached["id"],
                "cached": True,
                "fetched_at": cached["fetched_at"],
                "ttl_until": cached["ttl_until"],
            }
        if conn.in_transaction:
            return _denied("quarantine_transaction_open")
    except (sqlite3.Error, ValueError, TypeError):
        return _denied("quarantine_store_unavailable")

    response = client.extract(
        clean_url,
        purpose=purpose,
        extract_depth=extract_depth,
        query=query,
        chunks_per_source=chunks_per_source,
        format=format,
    )
    if response.get("status") != "ok":
        return _denied("extract_unavailable")
    results = response.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        return _denied("extract_response_invalid")
    result = results[0]
    returned_url, returned_error = sanitise_url(str(result.get("url", "")))
    # Provider redirects are not observable beyond the returned URL. Require identity,
    # never infer redirect-hop safety from a returned public destination.
    if returned_error or returned_url != clean_url:
        return _denied("extract_source_changed")
    text = result.get("raw_content") or result.get("markdown")
    if not isinstance(text, str) or not text.strip():
        return _denied("extract_content_unavailable")
    text = text[: settings.extract_max_chars]
    fetched = str(response.get("fetched_at") or get_clock().now_iso())
    try:
        ttl = format_timestamp(parse_timestamp(fetched) + timedelta(days=settings.extract_ttl_days))
        access = RoleAccess(conn, Role.WEBFACTS)
        with access.transaction():
            generation = conn.execute(
                "SELECT count(*) FROM extractions WHERE url_norm=? AND extract_depth=? "
                "AND query_hash LIKE ?",
                (clean_url, extract_depth, query_hash + ":%"),
            ).fetchone()[0]
            extraction_id = det_id("extraction", clean_url, query_hash, fetched, str(generation))
            access.execute_write(
                "extractions",
                "INSERT INTO extractions "
                "(id,url_norm,extract_depth,query_hash,ok,content_text,content_hash,fetched_at,ttl_until) "
                "VALUES (?,?,?,?,1,?,?,?,?)",
                (
                    extraction_id,
                    clean_url,
                    extract_depth,
                    query_hash + ":" + str(generation),
                    text,
                    hashlib.sha256(text.encode()).hexdigest(),
                    fetched,
                    ttl,
                ),
            )
    except (sqlite3.Error, ValueError):
        return _denied("quarantine_persistence_failed")
    return {
        "ok": True,
        "content_text": text[: settings.quarantine_max_input_chars],
        "extraction_id": extraction_id,
        "cached": False,
        "fetched_at": fetched,
        "ttl_until": ttl,
    }
