"""Webfacts-owned email verification. Reader output is validated before any lookup."""

import json
import re
import sqlite3
from datetime import timedelta
from email.utils import parseaddr
from typing import Any

from probation.config import settings
from probation.core.clock import Clock, format_timestamp, parse_timestamp
from probation.core.hashing import canonical_json
from probation.core.history import HistoryView
from probation.core.types import Features, Situation
from probation.db.access import Role, RoleAccess
from probation.db.guards import AccessError
from probation.llm.jobs import MailReader
from probation.web.catalog import load_catalog, reviewed_entry
from probation.web.client import TavilyClient
from probation.web.derive import (
    check_local_brand_list,
    derive_entity_facts,
    extract_domain_label,
    extract_email_domains,
    extract_registrable_domain,
)
from probation.web.query_guard import validate_tavily_query
from probation.web.view import RestrictionOnly, WebFactsView

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
    return extract_registrable_domain(domain) in FREEMAIL_DOMAINS


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "not_checked",
        "origin": "tavily",
        "facts": {"reason": reason},
        "sources": [],
        "cached": False,
    }


def vet_entity(
    conn: sqlite3.Connection,
    domain: str,
    brand_token: str | None = None,
    situation_id: str | None = None,
    as_of: str | None = None,
    tavily_client: TavilyClient | None = None,
    present_knowledge: bool = False,
    *,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """Persist truthful fetch time; historical as_of never backdates a response."""
    clean = extract_registrable_domain(domain)
    clk = clock or Clock.live()
    now = clk.now_iso()
    if not clean:
        return _unavailable("invalid_domain")
    if is_freemail_domain(clean):
        return _unavailable("freemail_excluded")
    entry = reviewed_entry(brand_token or extract_domain_label(clean), as_of=now)
    brand = entry.brand if entry else extract_domain_label(clean)
    if conn.in_transaction:
        return _unavailable("verification_transaction_open")
    try:
        cached = conn.execute("SELECT * FROM web_facts WHERE entity_key=?", (clean,)).fetchone()
        if cached and parse_timestamp(cached["fetched_at"]) <= parse_timestamp(
            now
        ) < parse_timestamp(cached["ttl_until"]):
            if (cached["origin"] != "fixture" or present_knowledge) and WebFactsView(
                conn
            ).get_entity_facts(clean, as_of=now) is not None:
                return {
                    "status": cached["status"],
                    "origin": cached["origin"],
                    "facts": json.loads(cached["facts_json"]),
                    "sources": json.loads(cached["sources_json"]),
                    "fetched_at": cached["fetched_at"],
                    "ttl_until": cached["ttl_until"],
                    "cached": True,
                }
        local = check_local_brand_list(brand, clean) if entry is not None else None
        if local is None:
            client = tavily_client or TavilyClient(conn=conn)
            query = f"{brand} official website"
            safe, _ = validate_tavily_query(
                query, user_name_tokens=settings.user_name_tokens.split(",")
            )
            if not safe:
                return _unavailable("query_rejected")
            ident = client.search(
                query=query,
                purpose="vet_ident",
                max_results=5,
                search_depth="basic",
                situation_id=situation_id,
            )
            local = derive_entity_facts(clean, ident, brand_token=brand)
            if local["status"] == "unverified" and ident.get("results"):
                report = client.search(
                    query=f"{clean} scam OR fake OR phishing OR complaint",
                    purpose="vet_report",
                    max_results=5,
                    search_depth="basic",
                    situation_id=situation_id,
                )
                local = derive_entity_facts(clean, ident, brand_token=brand, report_results=report)
            now = clk.now_iso()
        if local["status"] == "not_checked":
            return local
        origin = "fixture" if present_knowledge else local["origin"]
        ttl = _persist_web_facts(
            conn,
            clean,
            local["status"],
            local["facts"],
            local["sources"],
            origin,
            now,
            present_knowledge,
        )
        return {
            **local,
            "origin": origin,
            "fetched_at": now,
            "ttl_until": ttl,
            "cached": False,
            "present_knowledge": present_knowledge,
        }
    except (sqlite3.Error, AccessError, ValueError, TypeError, KeyError):
        return _unavailable("verification_store_unavailable")


def _persist_web_facts(
    conn: sqlite3.Connection,
    entity_key: str,
    status: str,
    facts: dict[str, Any],
    sources: list[dict[str, str]],
    origin: str,
    fetched_at: str,
    present_knowledge: bool = False,
) -> str:
    days = (
        settings.web_facts_ttl_positive_days
        if status == "confirmed_official"
        else settings.web_facts_ttl_negative_days
    )
    ttl = format_timestamp(parse_timestamp(fetched_at) + timedelta(days=days))
    access = RoleAccess(conn, Role.WEBFACTS)
    with access.transaction():
        access.execute_write(
            "web_facts",
            """INSERT INTO web_facts
        (entity_key,status,facts_json,sources_json,origin,present_knowledge,fetched_at,ttl_until)
        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(entity_key) DO UPDATE SET
        status=excluded.status,facts_json=excluded.facts_json,sources_json=excluded.sources_json,
        origin=excluded.origin,present_knowledge=excluded.present_knowledge,
        fetched_at=excluded.fetched_at,ttl_until=excluded.ttl_until""",
            (
                entity_key,
                status,
                canonical_json(facts),
                canonical_json(sources),
                origin,
                int(present_knowledge),
                fetched_at,
                ttl,
            ),
        )
    return ttl


def _not_checked(domain: str, reason: str) -> RestrictionOnly:
    return RestrictionOnly(
        entity_key=domain, status="not_checked", web_cap=3, origin="tavily", reasons=[reason]
    )


def verify_email_entities(
    conn: sqlite3.Connection,
    situation: Situation,
    features: Features,
    history: HistoryView,
    *,
    client: TavilyClient,
    clock: Clock,
) -> list[RestrictionOnly]:
    """Email entity rules with public-domain-only egress and bounded familiarity."""
    sender = extract_registrable_domain(situation.sender_key or "")
    if situation.pack != "mail" or situation.family != "email_action":
        return []
    if features.situation_id != situation.id or not features.reader_ok or not features.reader:
        return [_not_checked(sender, "reader_not_validated")]
    try:
        MailReader.model_validate(features.reader)
    except ValueError:
        return [_not_checked(sender, "reader_not_validated")]
    raw = history.get_raw_item(situation.raw_item_id)
    if raw is None:
        return [_not_checked(sender, "source_not_known")]
    try:
        payload = json.loads(raw["payload_json"])
        sender, domains = extract_email_domains(situation.sender_key, payload)
        known = {extract_registrable_domain(value) for value in history.known_entity_senders()}
        display, _ = parseaddr(str(payload.get("from") or payload.get("from_addr") or ""))
        matches = [
            entry.brand
            for entry in load_catalog()
            if re.search(r"(?<!\w)" + re.escape(entry.brand) + r"(?!\w)", display.casefold())
        ]
        claimed = matches[0] if len(matches) == 1 else None
        unknown_link = any(
            d != sender and d not in known and not is_freemail_domain(d) for d in domains
        )
        trigger = features.deterministic.get("sender_tier") == "unknown" or unknown_link
        results = []
        for domain in dict.fromkeys([sender, *domains]):
            if not domain:
                continue
            reason = ""
            if is_freemail_domain(domain):
                reason = "freemail_excluded"
            elif domain in known:
                reason = "known_domain_excluded"
            elif not trigger:
                reason = "no_trigger"
            if reason:
                cached = WebFactsView(conn).get_entity_facts(domain, as_of=clock.now_iso())
                results.append(cached if cached is not None else _not_checked(domain, reason))
                continue
            result = vet_entity(
                conn,
                domain,
                brand_token=claimed if domain == sender else None,
                situation_id=situation.id,
                as_of=history.as_of,
                tavily_client=client,
                clock=clock,
            )
            fact = WebFactsView(conn).get_entity_facts(domain, as_of=clock.now_iso())
            results.append(
                fact
                if fact is not None and result["status"] != "not_checked"
                else _not_checked(
                    domain, str(result.get("facts", {}).get("reason", "verification_unavailable"))
                )
            )
        return results
    except (sqlite3.Error, AccessError, ValueError, TypeError, KeyError):
        return [_not_checked(sender, "verification_unavailable")]


def vet_situations_batch(
    conn: sqlite3.Connection,
    situations: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
    tavily_client: TavilyClient | None = None,
) -> int:
    """Batch only persisted validated, knowable mail reads through the same adapter."""
    client = tavily_client or TavilyClient(conn=conn)
    clock = client.clock
    history = HistoryView(conn, as_of or clock.now_iso())
    rows = [dict(row) for row in history.get_situations(pack="mail")]
    selected = {str(row["id"]) for row in situations} if situations is not None else None
    count = 0
    for row in rows:
        if selected is not None and str(row["id"]) not in selected:
            continue
        stored = history.known_features(str(row["id"]))
        if stored is None or not stored["reader_ok"]:
            continue
        situation = Situation.model_validate(row)
        features = Features(
            situation_id=situation.id,
            deterministic=json.loads(stored["deterministic_json"]),
            reader=json.loads(stored["reader_json"]) if stored["reader_json"] else None,
            reader_ok=True,
            featurizer_version=stored["featurizer_version"],
            features_hash=stored["features_hash"],
        )
        facts = verify_email_entities(
            conn, situation, features, history, client=client, clock=clock
        )
        if any(fact.status != "not_checked" for fact in facts):
            count += 1
    return count
