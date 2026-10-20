"""Webfacts worker: Entity vetting and web fact caching via Tavily.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 5, docs/CONTRACT.md section 3, and CCR-1.
Role.WEBFACTS write isolation: writes strictly to web_facts, tavily_calls, extractions, etc.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from probation.core.clock import Clock
from probation.core.hashing import canonical_json
from probation.db.access import Role, RoleAccess
from probation.web.client import TavilyClient
from probation.web.derive import (
    check_local_brand_list,
    derive_entity_facts,
    extract_domain_label,
    extract_registrable_domain,
)

FREEMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.in",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "aol.com",
        "zoho.com",
        "proton.me",
        "protonmail.com",
        "mail.com",
        "yandex.com",
    }
)


def is_freemail_domain(domain: str) -> bool:
    """Return True if domain is a personal freemail provider."""
    reg = extract_registrable_domain(domain)
    return reg.lower() in FREEMAIL_DOMAINS


def vet_entity(
    conn: sqlite3.Connection,
    domain: str,
    brand_token: str | None = None,
    situation_id: str | None = None,
    as_of: str | None = None,
    tavily_client: TavilyClient | None = None,
    present_knowledge: bool = False,
) -> dict[str, Any]:
    """Vet an entity (registrable domain) and record results in web_facts table.

    Authority: docs/TAVILY_AND_NEW_PACKS.md section 5:
    1. Local brand check first (config/brands.json) -> immediate status without network.
    2. Check fresh entry in web_facts (TTL 30 days confirmed_official, 7 days otherwise).
    3. If unknown / trigger met, execute vet_ident search via TavilyClient.
    4. If vet_ident inconclusive, execute conditional vet_report search.
    5. Derive EntityFacts and persist to web_facts table.
    """
    clean_domain = extract_registrable_domain(domain)
    if not clean_domain:
        return {
            "status": "not_checked",
            "origin": "tavily",
            "facts": {},
            "sources": [],
        }

    domain_label = extract_domain_label(clean_domain)
    effective_brand = (brand_token or domain_label).strip().lower()
    now_iso = as_of or Clock().now_iso()

    # 1. Skip personal freemail providers from entity brand vetting
    if is_freemail_domain(clean_domain):
        return {
            "status": "unverified",
            "origin": "tavily",
            "facts": {
                "official_candidates": [],
                "lookalike_of": None,
                "report_hits": 0,
                "domain_in_results": False,
                "freemail": True,
            },
            "sources": [],
        }

    # 2. Local brand list pre-check (free, zero network)
    local_check = check_local_brand_list(effective_brand, clean_domain)
    if local_check is not None:
        _persist_web_facts(
            conn,
            entity_key=clean_domain,
            status=local_check["status"],
            facts=local_check["facts"],
            sources=local_check["sources"],
            origin=local_check["origin"],
            fetched_at=now_iso,
            present_knowledge=present_knowledge,
        )
        return local_check

    # 3. Check fresh entry in web_facts cache
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status, facts_json, sources_json, origin, fetched_at, ttl_until
        FROM web_facts
        WHERE entity_key = ?;
        """,
        (clean_domain,),
    )
    cached = cur.fetchone()
    if cached:
        ttl = str(cached["ttl_until"])
        if now_iso <= ttl:
            facts_dict = json.loads(cached["facts_json"]) if cached["facts_json"] else {}
            sources_list = json.loads(cached["sources_json"]) if cached["sources_json"] else []
            return {
                "status": cached["status"],
                "origin": cached["origin"],
                "facts": facts_dict,
                "sources": sources_list,
            }

    # 4. Outbound Tavily calls
    client = tavily_client or TavilyClient(conn=conn)

    # Call 1: vet_ident
    ident_query = f"{effective_brand} official website"
    ident_res = client.search(
        query=ident_query,
        purpose="vet_ident",
        max_results=5,
        search_depth="basic",
        situation_id=situation_id,
        as_of=as_of,
    )

    facts = derive_entity_facts(
        domain=clean_domain,
        search_results=ident_res,
        brand_token=effective_brand,
    )

    # Call 2: vet_report (only if vet_ident is inconclusive: unverified and results found)
    if facts["status"] == "unverified" and ident_res.get("results"):
        report_query = f'"{clean_domain}" scam OR fake OR phishing OR complaint'
        report_res = client.search(
            query=report_query,
            purpose="vet_report",
            max_results=5,
            search_depth="basic",
            situation_id=situation_id,
            as_of=as_of,
        )
        facts = derive_entity_facts(
            domain=clean_domain,
            search_results=ident_res,
            brand_token=effective_brand,
            report_results=report_res,
        )

    # 5. Persist derived facts to web_facts table
    _persist_web_facts(
        conn,
        entity_key=clean_domain,
        status=facts["status"],
        facts=facts["facts"],
        sources=facts["sources"],
        origin="tavily",
        fetched_at=now_iso,
        present_knowledge=present_knowledge,
    )

    return facts


def _persist_web_facts(
    conn: sqlite3.Connection,
    entity_key: str,
    status: str,
    facts: dict[str, Any],
    sources: list[dict[str, str]],
    origin: str,
    fetched_at: str,
    present_knowledge: bool = False,
) -> None:
    """Write verified entity facts into web_facts table under Role.WEBFACTS."""
    try:
        now_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except Exception:
        now_dt = Clock().now()

    # TTL: 30 days for confirmed_official, 7 days otherwise (docs/TAVILY_AND_NEW_PACKS 5.3)
    days = 30 if status == "confirmed_official" else 7
    ttl_dt = now_dt + timedelta(days=days)
    ttl_until = ttl_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    facts_json = canonical_json(facts)
    sources_json = canonical_json(sources)

    access = RoleAccess(conn, Role.WEBFACTS)
    access.execute_write(
        "web_facts",
        """
        INSERT OR REPLACE INTO web_facts
        (entity_key, status, facts_json, sources_json, origin, present_knowledge, fetched_at, ttl_until)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            entity_key,
            status,
            facts_json,
            sources_json,
            origin,
            1 if present_knowledge else 0,
            fetched_at,
            ttl_until,
        ),
    )
    access.commit()


def vet_situations_batch(
    conn: sqlite3.Connection,
    situations: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
    tavily_client: TavilyClient | None = None,
) -> int:
    """Vet sender and link entities for situations batch."""
    cur = conn.cursor()
    if situations is None:
        cur.execute(
            """
            SELECT id, pack, sender_key, occurred_at
            FROM situations
            WHERE pack IN ('mail', 'calendar')
            ORDER BY occurred_at ASC;
            """
        )
        sit_rows = cur.fetchall()
    else:
        sit_rows = situations

    vetted_count = 0
    seen_domains: set[str] = set()

    for s in sit_rows:
        sender = s["sender_key"]
        if not sender:
            continue

        domain = sender.split("@")[-1].strip().lower()
        reg_domain = extract_registrable_domain(domain)
        if not reg_domain or reg_domain in seen_domains:
            continue

        seen_domains.add(reg_domain)
        occ = s["occurred_at"] if "occurred_at" in (s.keys() if hasattr(s, "keys") else s) else None
        vet_entity(
            conn,
            domain=reg_domain,
            situation_id=s["id"],
            as_of=as_of or occ,
            tavily_client=tavily_client,
        )
        vetted_count += 1

    return vetted_count
