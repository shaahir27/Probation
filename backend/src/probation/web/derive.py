"""Entity facts derivation rules.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 5 and docs/CONTRACT.md section 2.
Deterministic derivation of EntityFacts from Tavily search results and local brand lists.
Zero LLM calls. Facts may ONLY restrict or inform (Invariant I-21).
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOOKALIKE_MAX_EDIT_DISTANCE = 2
REPORT_HITS_MIN = 2
SCAM_TERMS = frozenset({"scam", "phishing", "fraud", "fake", "complaint", "warning", "beware"})

# Known multi-part public suffixes
TWO_PART_TLDS = frozenset(
    {
        "co.uk",
        "ac.in",
        "gov.in",
        "org.in",
        "edu.in",
        "res.in",
        "com.au",
        "co.nz",
        "co.jp",
        "com.br",
        "org.uk",
        "gov.uk",
        "co.in",
        "net.in",
    }
)


def extract_registrable_domain(url_or_domain: str) -> str:
    """Extract registrable domain (SLD + TLD) from a URL, hostname, or email address."""
    raw = url_or_domain.strip().lower()
    if "@" in raw:
        raw = raw.split("@")[-1]
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.netloc.split(":")[0]
    else:
        host = raw.split("/")[0].split(":")[0]

    parts = host.split(".")
    if len(parts) <= 2:
        return host

    last_two = ".".join(parts[-2:])
    if last_two in TWO_PART_TLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def extract_domain_label(registrable_domain: str) -> str:
    """Extract the second-level domain label (e.g. 'google' from 'google.com')."""
    reg = extract_registrable_domain(registrable_domain)
    parts = reg.split(".")
    return parts[0] if parts else reg


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if len(s1) == 0:
        return len(s2)
    if len(s2) == 0:
        return len(s1)

    v0 = list(range(len(s2) + 1))
    v1 = [0] * (len(s2) + 1)

    for i in range(len(s1)):
        v1[0] = i + 1
        for j in range(len(s2)):
            cost = 0 if s1[i] == s2[j] else 1
            v1[j + 1] = min(v1[j] + 1, v0[j + 1] + 1, v0[j] + cost)
        v0, v1 = v1, [0] * (len(s2) + 1)

    return v0[len(s2)]


def fold_label(label: str) -> str:
    """Normalize domain label with homoglyphs and separator stripping."""
    s = label.lower().replace("-", "").replace("_", "")
    s = s.replace("0", "o")
    s = s.replace("1", "l")
    s = s.replace("rn", "m")
    s = s.replace("vv", "w")
    return s


def is_lookalike(
    candidate_label: str,
    target_label: str,
    candidate_domain: str,
    target_domain: str,
    max_edit_distance: int = LOOKALIKE_MAX_EDIT_DISTANCE,
) -> bool:
    """Check if candidate is a lookalike/spoof of target official domain label."""
    c_label = candidate_label.lower()
    t_label = target_label.lower()

    if candidate_domain.lower() == target_domain.lower():
        return False

    # 1. Homoglyph / separator equality
    folded_c = fold_label(c_label)
    folded_t = fold_label(t_label)
    if folded_c == folded_t and c_label != t_label:
        return True

    # 2. Levenshtein edit distance (on labels >= 4 chars to avoid false positives)
    if min(len(c_label), len(t_label)) >= 3:
        if levenshtein_distance(c_label, t_label) <= max_edit_distance:
            return True

    # 3. Label containment (e.g. brand-login, brand-verify vs brand)
    if len(t_label) >= 4 and t_label in c_label:
        return True

    return False


_BRANDS_CACHE: dict[str, str] | None = None


def load_brands(brands_path: Path | None = None) -> dict[str, str]:
    """Load brand token to official domain mapping from config/brands.json."""
    global _BRANDS_CACHE
    if _BRANDS_CACHE is not None and brands_path is None:
        return _BRANDS_CACHE

    target_path = brands_path or Path("config/brands.json")
    if not target_path.exists():
        # Fallback to search relative to parent directories
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "config" / "brands.json"
            if candidate.exists():
                target_path = candidate
                break

    if target_path.exists():
        with open(target_path, encoding="utf-8") as f:
            data = json.load(f)
            # Filter out comment keys
            brands = {k.lower(): v.lower() for k, v in data.items() if not k.startswith("_")}
            if brands_path is None:
                _BRANDS_CACHE = brands
            return brands

    return {}


def check_local_brand_list(
    brand_token: str,
    sender_domain: str,
    brands: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Perform free local pre-check against verified brands list (TAVILY_AND_NEW_PACKS 5.3).

    Returns:
        dict with status, origin='local_brand_list', facts, and sources,
        or None if brand token not in local list.
    """
    brand_map = brands if brands is not None else load_brands()
    clean_token = brand_token.strip().lower()

    if not clean_token or clean_token not in brand_map:
        return None

    official_domain = extract_registrable_domain(brand_map[clean_token])
    sender_reg = extract_registrable_domain(sender_domain)

    if sender_reg == official_domain:
        return {
            "status": "confirmed_official",
            "origin": "local_brand_list",
            "facts": {
                "official_candidates": [official_domain],
                "lookalike_of": None,
                "report_hits": 0,
                "domain_in_results": True,
            },
            "sources": [
                {
                    "title": f"Verified Brand Registry: {clean_token}",
                    "url": f"https://{official_domain}",
                }
            ],
        }

    # Brand matched but domain differs -> immediate lookalike
    return {
        "status": "lookalike",
        "origin": "local_brand_list",
        "facts": {
            "official_candidates": [official_domain],
            "lookalike_of": official_domain,
            "report_hits": 0,
            "domain_in_results": False,
        },
        "sources": [
            {
                "title": f"Official domain for {clean_token} is {official_domain}",
                "url": f"https://{official_domain}",
            }
        ],
    }


def derive_entity_facts(
    domain: str,
    search_results: dict[str, Any],
    brand_token: str | None = None,
    report_results: dict[str, Any] | None = None,
    brands: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Derive deterministic EntityFacts per docs/TAVILY_AND_NEW_PACKS.md section 5.5.

    Status precedence:
    lookalike > reports_found >= 2 > confirmed_official > no_web_presence > unverified.
    not_checked when call was not made or failed.
    """
    clean_domain = extract_registrable_domain(domain)
    domain_label = extract_domain_label(clean_domain)
    effective_brand = (brand_token or domain_label).strip().lower()

    # 1. Local brand pre-check
    local_check = check_local_brand_list(effective_brand, clean_domain, brands=brands)
    if local_check is not None:
        return local_check

    # 2. Check search call status
    if search_results.get("status") in ("not_checked", "failed", "no_api_key", "budget_exhausted"):
        return {
            "status": "not_checked",
            "origin": "tavily",
            "facts": {
                "official_candidates": [],
                "lookalike_of": None,
                "report_hits": 0,
                "domain_in_results": False,
            },
            "sources": [],
        }

    raw_results = search_results.get("results", [])

    # If completely empty results
    if not raw_results:
        return {
            "status": "no_web_presence",
            "origin": "tavily",
            "facts": {
                "official_candidates": [],
                "lookalike_of": None,
                "report_hits": 0,
                "domain_in_results": False,
            },
            "sources": [],
        }

    # Extract result domains
    result_domains: list[str] = []
    official_candidates: list[str] = []
    sources: list[dict[str, str]] = []

    has_domain_mention = False

    for idx, item in enumerate(raw_results):
        url = item.get("url", "")
        title = item.get("title", "")
        snippet = item.get("content", "") or item.get("snippet", "")
        item_reg = extract_registrable_domain(url)

        if item_reg and item_reg not in result_domains:
            result_domains.append(item_reg)

        # Sources (up to 3)
        if len(sources) < 3 and url:
            sources.append({"title": title or item_reg, "url": url})

        # Check mention of domain or brand
        text_corpus = f"{title} {url} {snippet}".lower()
        if clean_domain in text_corpus or effective_brand in text_corpus:
            has_domain_mention = True

        # Official candidates from top 3
        if idx < 3 and item_reg not in official_candidates:
            item_label = extract_domain_label(item_reg).lower()
            title_lower = title.lower()
            if effective_brand in item_label or title_lower.startswith(effective_brand):
                official_candidates.append(item_reg)

    domain_in_results = clean_domain in result_domains

    # 3. Lookalike detection
    lookalike_of: str | None = None
    brand_map = brands if brands is not None else load_brands()

    # Check against local brand dictionary targets
    for _b_tok, b_dom in brand_map.items():
        b_reg = extract_registrable_domain(b_dom)
        b_label = extract_domain_label(b_reg)
        if is_lookalike(domain_label, b_label, clean_domain, b_reg):
            lookalike_of = b_reg
            break

    # Check against discovered official candidates
    if lookalike_of is None:
        for cand in official_candidates:
            cand_label = extract_domain_label(cand)
            if is_lookalike(domain_label, cand_label, clean_domain, cand):
                lookalike_of = cand
                break

    # 4. Report hits (from vet_report results if provided, or search snippets)
    report_hits = 0
    report_sources: list[dict[str, str]] = []
    all_report_items = []
    if report_results and "results" in report_results:
        all_report_items.extend(report_results["results"])
    all_report_items.extend(raw_results)

    for r_item in all_report_items:
        r_title = r_item.get("title", "")
        r_snip = r_item.get("content", "") or r_item.get("snippet", "")
        r_text = f"{r_title} {r_snip}".lower()

        if clean_domain in r_text:
            if any(term in r_text for term in SCAM_TERMS):
                report_hits += 1
                if len(report_sources) < 3 and r_item.get("url"):
                    report_sources.append(
                        {"title": r_title or clean_domain, "url": r_item.get("url", "")}
                    )

    # 5. Status precedence resolution
    # lookalike > reports_found (>= REPORT_HITS_MIN) > confirmed_official > no_web_presence > unverified
    final_status = "unverified"

    if lookalike_of is not None:
        final_status = "lookalike"
    elif report_hits >= REPORT_HITS_MIN:
        final_status = "reports_found"
        if report_sources:
            sources = report_sources
    elif clean_domain in official_candidates:
        final_status = "confirmed_official"
    elif not has_domain_mention and not domain_in_results:
        final_status = "no_web_presence"
    else:
        final_status = "unverified"

    return {
        "status": final_status,
        "origin": "tavily",
        "facts": {
            "official_candidates": official_candidates,
            "lookalike_of": lookalike_of,
            "report_hits": report_hits,
            "domain_in_results": domain_in_results,
        },
        "sources": sources,
    }
