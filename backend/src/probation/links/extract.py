"""Quarantined web page text extraction gateway.

Authority: docs/CONTRACT.md invariants I-22, I-24, I-26 and docs/TAVILY_AND_NEW_PACKS.md section 7.
Enforces:
- Invariant I-24: URLs found in mail bodies are NEVER fetched or extracted.
  Extract is used ONLY on user-saved URLs (intake user_saved) and official URLs discovered by Search.
- Sanitisation: Must pass links/sanitise.py.
- Vetting gate: Abort extraction if entity status is lookalike or reports_found.
- Caching & Truncation: Stored in extractions table truncated to QUARANTINE_MAX_INPUT_CHARS.
"""

import hashlib
import sqlite3
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from probation.config import settings
from probation.core.clock import format_timestamp, get_clock, parse_timestamp
from probation.core.hashing import det_id
from probation.db.access import Role, RoleAccess
from probation.links.sanitise import sanitise_url
from probation.web.client import TavilyClient


def extract_url_content(
    url: str,
    conn: sqlite3.Connection,
    client: TavilyClient,
    purpose: str = "extract_item",
    extract_depth: str = "basic",
    is_user_saved: bool = False,
    is_official_search: bool = False,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Extract and quarantine web content following Invariant I-24 and safety checks."""
    # 1. Invariant I-24: Never fetch URLs from mail bodies
    if not is_user_saved and not is_official_search:
        return {
            "ok": False,
            "error": "Invariant I-24 violation: URL extraction is restricted to user-saved or official search URLs only",
            "content_text": None,
            "extraction_id": None,
        }

    # 2. URL sanitisation & safety check
    clean_url, hands_off_reason = sanitise_url(url)
    if hands_off_reason is not None:
        return {
            "ok": False,
            "error": f"URL hands-off rejected: {hands_off_reason}",
            "content_text": None,
            "extraction_id": None,
        }

    # 3. Vetting gate check: lookalike or reports_found prohibited from extraction
    domain = (urlparse(clean_url).hostname or "").lower()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM web_facts WHERE entity_key = ?;",
            (domain,),
        )
        fact_row = cur.fetchone()
        if fact_row:
            status = fact_row["status"]
            if status in ("lookalike", "reports_found"):
                return {
                    "ok": False,
                    "error": f"Extraction blocked by entity vetting status: {status}",
                    "content_text": None,
                    "extraction_id": None,
                }
    except sqlite3.OperationalError:
        pass

    # 4. Check extractions cache
    query_hash = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()
    cached = None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM extractions
            WHERE url_norm = ? AND extract_depth = ? AND query_hash = ?;
            """,
            (clean_url, extract_depth, query_hash),
        )
        cached = cur.fetchone()
    except sqlite3.OperationalError:
        cached = None
    now_ts = now_iso or get_clock().now_iso()

    if cached and cached["ok"]:
        return {
            "ok": True,
            "content_text": cached["content_text"],
            "extraction_id": cached["id"],
            "cached": True,
        }

    # 5. Outbound Tavily Extract call
    extract_resp = client.extract(clean_url, purpose=purpose, extract_depth=extract_depth)
    if extract_resp.get("status") != "ok":
        return {
            "ok": False,
            "error": extract_resp.get("error", "Tavily Extract failed"),
            "content_text": None,
            "extraction_id": None,
        }

    results = extract_resp.get("results", [])
    raw_text = ""
    if results and isinstance(results, list):
        first_item = results[0]
        if isinstance(first_item, dict):
            raw_text = str(first_item.get("raw_content") or first_item.get("markdown") or "")

    max_chars = getattr(settings, "quarantine_max_input_chars", 6000)
    truncated_text = raw_text[:max_chars]
    content_hash = hashlib.sha256(truncated_text.encode("utf-8")).hexdigest()

    extraction_id = det_id("extraction", clean_url, extract_depth, query_hash)
    ttl_days = getattr(settings, "extract_ttl_days", 30)
    ttl_until = format_timestamp(parse_timestamp(now_ts) + timedelta(days=ttl_days))

    # Store in extractions
    try:
        role_access = RoleAccess(conn, Role.WEBFACTS)
        role_access.execute_write(
            "extractions",
            """
            INSERT OR REPLACE INTO extractions
            (id, url_norm, extract_depth, query_hash, ok, content_text, content_hash, fetched_at, ttl_until)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                extraction_id,
                clean_url,
                extract_depth,
                query_hash,
                1,
                truncated_text,
                content_hash,
                now_ts,
                ttl_until,
            ),
        )
    except Exception:
        pass

    return {
        "ok": True,
        "content_text": truncated_text,
        "extraction_id": extraction_id,
        "cached": False,
    }
