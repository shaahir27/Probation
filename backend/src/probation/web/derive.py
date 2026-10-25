"""Deterministic restriction-only entity derivation from reviewed public provenance."""

import ipaddress
import re
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import publicsuffix2

from probation.config import settings
from probation.web.catalog import CatalogEntry, entries_from_data, load_catalog, reviewed_entry

SCAM_TERMS = frozenset({"scam", "phishing", "fraud", "fake", "complaint", "warning", "beware"})
INFRASTRUCTURE_DOMAINS = frozenset({"googleusercontent.com", "gstatic.com", "cloudfront.net"})


def extract_registrable_domain(url_or_domain: str) -> str:
    """Normalize a public hostname through the installed offline public-suffix list."""
    raw = url_or_domain.strip().lower()
    if not raw or any(ch.isspace() for ch in raw) or "\\" in raw:
        return ""
    try:
        if "://" in raw:
            parsed = urlsplit(raw)
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
                return ""
            host = parsed.hostname or ""
        else:
            host = raw.rsplit("@", 1)[-1]
            host = urlsplit("//" + host).hostname or ""
        host = host.rstrip(".").encode("idna").decode("ascii")
        if len(host) > 253 or "." not in host:
            return ""
        labels = host.split(".")
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
        ):
            return ""
        try:
            ipaddress.ip_address(host)
            return ""
        except ValueError:
            pass
        if host.endswith((".local", ".internal", ".lan", ".localhost")):
            return ""
        # Reserved synthetic domains remain valid test entities, never live destinations.
        if labels[-1] in {"example", "test", "invalid"}:
            return ".".join(labels[-2:])
        domain = publicsuffix2.get_sld(host, strict=True)
        suffix = publicsuffix2.get_tld(host, strict=True)
        return str(domain) if domain and domain != suffix else ""
    except (ValueError, UnicodeError):
        return ""


def extract_domain_label(registrable_domain: str) -> str:
    domain = extract_registrable_domain(registrable_domain)
    return domain.split(".")[0] if domain else ""


def extract_email_domains(sender_key: str | None, payload: dict[str, Any]) -> tuple[str, list[str]]:
    """Discard body URL paths locally; return sender and at most three distinct domains."""
    _, address = parseaddr(str(payload.get("from") or payload.get("from_addr") or ""))
    sender = extract_registrable_domain(sender_key or address)
    body = str(payload.get("body_text") or payload.get("body") or "")
    return sender, mail_link_domains(body)


def mail_link_domains(body: str) -> list[str]:
    """Use the same bounded domain projection for proposals and effect revalidation."""
    domains: list[str] = []
    for url in re.findall(r"https?://[^\s<>\"']+", body, re.I):
        domain = extract_registrable_domain(url)
        if domain and domain not in domains and domain not in INFRASTRUCTURE_DOMAINS:
            domains.append(domain)
        if len(domains) == 3:
            break
    return domains


def levenshtein_distance(s1: str, s2: str) -> int:
    previous = list(range(len(s2) + 1))
    for i, left in enumerate(s1, 1):
        current = [i]
        for j, right in enumerate(s2, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def fold_label(label: str) -> str:
    return (
        label.lower()
        .replace("-", "")
        .replace("_", "")
        .replace("0", "o")
        .replace("1", "l")
        .replace("rn", "m")
        .replace("vv", "w")
    )


def is_lookalike(
    candidate_label: str,
    target_label: str,
    candidate_domain: str,
    target_domain: str,
    max_edit_distance: int | None = None,
) -> bool:
    if candidate_domain.lower() == target_domain.lower():
        return False
    candidate, target = candidate_label.lower(), target_label.lower()
    limit = settings.lookalike_max_edit_distance if max_edit_distance is None else max_edit_distance
    return bool(candidate and target) and (
        (fold_label(candidate) == fold_label(target) and candidate != target)
        or (
            min(len(candidate), len(target)) >= 3
            and levenshtein_distance(candidate, target) <= limit
        )
        or (len(target) >= 4 and target in candidate)
    )


def load_brands(brands_path: Path | None = None) -> dict[str, list[str]]:
    """Compatibility accessor returning reviewed domain sets, never legacy claims."""
    return {entry.brand: sorted(entry.official_domains) for entry in load_catalog(brands_path)}


def _entry(brand: str, brands: dict[str, Any] | None) -> CatalogEntry | None:
    if brands is None:
        return reviewed_entry(brand)
    entries = entries_from_data(brands if "entries" in brands else {"entries": brands})
    return next((entry for entry in entries if entry.brand == brand.strip().casefold()), None)


def check_local_brand_list(
    brand_token: str, sender_domain: str, brands: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    entry = _entry(brand_token, brands)
    domain = extract_registrable_domain(sender_domain)
    if entry is None or not domain:
        return None
    official = domain in entry.official_domains
    return {
        "status": "confirmed_official" if official else "lookalike",
        "origin": "local_brand_list",
        "facts": {
            "official_candidates": sorted(entry.official_domains),
            "lookalike_of": None if official else extract_registrable_domain(entry.source_url),
            "report_hits": 0,
            "domain_in_results": False,
            "catalog_brand": entry.brand,
            "catalog_version": entry.version,
            "catalog_source_url": entry.source_url,
            "catalog_verified_at": entry.verified_at,
            "evidence_availability": "reviewed_catalog",
        },
        "sources": [
            {"title": f"Reviewed official domains for {entry.brand}", "url": entry.source_url}
        ],
    }


def _safe_result(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    from probation.links.sanitise import sanitise_url

    url, reason = sanitise_url(str(item.get("url", "")))
    if reason is not None or not extract_registrable_domain(url):
        return None
    return {
        "url": url,
        "title": str(item.get("title", ""))[:300],
        "content": str(item.get("content") or item.get("snippet") or "")[:4000],
    }


def derive_entity_facts(
    domain: str,
    search_results: dict[str, Any],
    brand_token: str | None = None,
    report_results: dict[str, Any] | None = None,
    brands: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A catalog establishes identity; independent search sources supply cautions."""
    clean = extract_registrable_domain(domain)
    brand = (brand_token or extract_domain_label(clean)).strip().casefold()
    local = check_local_brand_list(brand, clean, brands=brands)
    if local is not None:
        return local
    facts: dict[str, Any] = {
        "official_candidates": [],
        "lookalike_of": None,
        "report_hits": 0,
        "domain_in_results": False,
        "evidence_availability": "unavailable_in_this_check",
    }
    result: dict[str, Any] = {
        "status": "not_checked",
        "origin": "tavily",
        "facts": facts,
        "sources": [],
    }
    if not clean or search_results.get("status") != "ok":
        return result
    results = [safe for raw in search_results.get("results", []) if (safe := _safe_result(raw))]
    result["status"] = "no_web_presence" if not results else "unverified"
    facts["domain_in_results"] = any(extract_registrable_domain(r["url"]) == clean for r in results)
    facts["evidence_availability"] = "search_results" if results else "unavailable_in_this_check"
    result["sources"] = [{"title": r["title"], "url": r["url"]} for r in results[:3]]
    independent: dict[str, dict[str, str]] = {}
    reports = (
        report_results.get("results", [])
        if report_results and report_results.get("status") == "ok"
        else []
    )
    for raw in [*results, *reports]:
        safe = _safe_result(raw)
        if safe is None:
            continue
        text = (safe["title"] + " " + safe["content"]).casefold()
        if re.search(r"(?<![\w.-])" + re.escape(clean) + r"(?![\w.-])", text) and any(
            re.search(r"\b" + term + r"\b", text) for term in SCAM_TERMS
        ):
            independent.setdefault(extract_registrable_domain(safe["url"]), safe)
    facts["report_hits"] = len(independent)
    if len(independent) >= settings.report_hits_min:
        result["status"] = "reports_found"
        result["sources"] = [
            {"title": r["title"], "url": r["url"]} for r in list(independent.values())[:3]
        ]
    return result
