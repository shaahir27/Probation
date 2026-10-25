"""Reviewed public entity provenance; legacy unreviewed mappings have no authority."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from probation.core.clock import parse_timestamp
from probation.core.hashing import canonical_json, det_id


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    brand: str
    official_domains: frozenset[str]
    version: str
    source_url: str
    verified_at: str


def catalog_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config/brands.json"
        if candidate.is_file():
            return candidate
    return Path("config/brands.json")


def entries_from_data(data: dict[str, Any]) -> tuple[CatalogEntry, ...]:
    """Only explicit reviewed domain sets can establish catalog authority."""
    entries = []
    raw_entries = data.get("entries", {})
    if not isinstance(raw_entries, dict):
        return ()
    for brand, raw in raw_entries.items():
        if not isinstance(raw, dict) or raw.get("active") is not True:
            continue
        domains = raw.get("official_domains")
        source = raw.get("source_url")
        verified = raw.get("verified_at")
        if not isinstance(brand, str) or not re.fullmatch(r"[a-z0-9][a-z0-9 &'\-]{0,59}", brand):
            continue
        if (
            not isinstance(domains, list)
            or not domains
            or not all(isinstance(d, str) for d in domains)
        ):
            continue
        if not isinstance(source, str) or not isinstance(verified, str):
            continue
        try:
            parse_timestamp(verified)
            parsed = urlsplit(source)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or not parsed.hostname
            ):
                continue
            from probation.web.derive import extract_registrable_domain

            normalized = frozenset(extract_registrable_domain(d) for d in domains)
            if "" in normalized or normalized != frozenset(domains):
                continue
            if extract_registrable_domain(source) not in normalized:
                continue
        except (ValueError, TypeError):
            continue
        version = det_id(
            "reviewed-catalog-v1", str(data.get("version", "")), brand, canonical_json(raw)
        )
        entries.append(CatalogEntry(brand, normalized, version, source, verified))
    return tuple(entries)


def load_catalog(path: Path | None = None) -> tuple[CatalogEntry, ...]:
    try:
        data = json.loads((path or catalog_path()).read_text(encoding="utf-8"))
        return entries_from_data(data) if isinstance(data, dict) else ()
    except (OSError, ValueError, TypeError):
        return ()


def reviewed_entry(
    brand: str, *, as_of: str | None = None, path: Path | None = None
) -> CatalogEntry | None:
    key = " ".join(brand.casefold().split())
    for entry in load_catalog(path):
        if entry.brand == key:
            if as_of is not None and parse_timestamp(entry.verified_at) > parse_timestamp(as_of):
                return None
            return entry
    return None
