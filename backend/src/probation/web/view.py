"""WebFactsView: Restriction-only view exposing web facts to workers without policy bias.

Authority: docs/CONTRACT.md invariant I-21 and docs/TAVILY_AND_NEW_PACKS.md section 5.6-5.7.
CRITICAL INVARIANT: This view NEVER includes probability, evidence, or licence fields.
Facts may ONLY restrict (lower cap to 1) or inform (sources).
"""

import json
import sqlite3

from pydantic import BaseModel, ConfigDict, Field

from probation.core.clock import format_timestamp, get_clock, parse_timestamp
from probation.web.catalog import reviewed_entry
from probation.web.derive import extract_registrable_domain

VETO_STATUSES = frozenset({"lookalike", "reports_found", "no_web_presence"})


class RestrictionOnly(BaseModel):
    """Restriction-only view of entity facts for consumption by caps/gate.

    Authority: docs/CONTRACT.md invariant I-21.
    Strictly contains NO probability, weight, or evidence fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_key: str
    status: str
    web_cap: int = Field(ge=0, le=3)
    sources: list[dict[str, str]] = Field(default_factory=list)
    origin: str
    reasons: list[str] = Field(default_factory=list)
    present_knowledge: bool = False
    fetched_at: str | None = None
    ttl_until: str | None = None


class WebFactsView:
    """Read-only view into web_facts table providing restriction-only data."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_entity_facts(
        self,
        entity_key: str,
        as_of: str | None = None,
    ) -> RestrictionOnly | None:
        """Fetch entity facts for a domain.

        Returns only restriction-relevant fields: status, web_cap, origin, sources, reasons.
        Never returns probabilities, model weights, or evidence counts.
        """
        if not entity_key:
            return None

        clean_key = extract_registrable_domain(entity_key)
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT status, facts_json, sources_json, origin, fetched_at, ttl_until,
                   present_knowledge
            FROM web_facts
            WHERE entity_key = ?;
            """,
            (clean_key,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        present = row["origin"] == "fixture" and row["present_knowledge"] == 1
        try:
            cutoff = parse_timestamp(as_of or get_clock().now_iso())
            fetched = parse_timestamp(str(row["fetched_at"]))
            expires = parse_timestamp(str(row["ttl_until"]))
            if expires <= fetched or (not present and not fetched <= cutoff < expires):
                return None
        except (ValueError, TypeError):
            return None

        if row["origin"] == "local_brand_list":
            try:
                facts = json.loads(row["facts_json"])
                entry = reviewed_entry(
                    str(facts.get("catalog_brand", "")), as_of=format_timestamp(cutoff)
                )
                if entry is None or entry.version != facts.get("catalog_version"):
                    return None
                expected = (
                    "confirmed_official" if clean_key in entry.official_domains else "lookalike"
                )
                if row["status"] != expected:
                    return None
            except (ValueError, TypeError, AttributeError):
                return None

        status = str(row["status"])
        try:
            sources_raw = json.loads(row["sources_json"]) if row["sources_json"] else []
        except (ValueError, TypeError):
            return None
        sources: list[dict[str, str]] = []
        for s in sources_raw:
            from probation.links.sanitise import sanitise_url

            if isinstance(s, dict):
                url, reason = sanitise_url(str(s.get("url", "")))
                if reason is None:
                    sources.append({"title": str(s.get("title", ""))[:300], "url": url})
            elif isinstance(s, str):
                url, reason = sanitise_url(s)
                if reason is None:
                    sources.append({"title": s[:300], "url": url})

        # Derive web_cap per docs/TAVILY_AND_NEW_PACKS.md section 5.6:
        # lookalike, reports_found, no_web_presence -> web_cap = 1.
        # confirmed_official, unverified, not_checked -> web_cap = 3 (no restriction).
        if status in VETO_STATUSES:
            web_cap = 1
            reasons = [f"web_veto:{status}"]
        else:
            web_cap = 3
            reasons = []

        return RestrictionOnly(
            entity_key=clean_key,
            status=status,
            web_cap=web_cap,
            sources=sources,
            origin=str(row["origin"]),
            reasons=reasons,
            present_knowledge=present,
            fetched_at=str(row["fetched_at"]),
            ttl_until=str(row["ttl_until"]),
        )
