"""WebFactsView: Restriction-only view exposing web facts to workers without policy bias.

Authority: docs/CONTRACT.md invariant I-21 and docs/TAVILY_AND_NEW_PACKS.md section 5.6-5.7.
CRITICAL INVARIANT: This view NEVER includes probability, evidence, or licence fields.
Facts may ONLY restrict (lower cap to 1) or inform (sources).
"""

import json
import sqlite3

from pydantic import BaseModel, ConfigDict, Field

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

        clean_key = entity_key.strip().lower()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT status, facts_json, sources_json, origin, fetched_at, ttl_until
            FROM web_facts
            WHERE entity_key = ?;
            """,
            (clean_key,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        status = str(row["status"])
        sources_raw = json.loads(row["sources_json"]) if row["sources_json"] else []
        sources: list[dict[str, str]] = []
        for s in sources_raw:
            if isinstance(s, dict):
                sources.append({"title": str(s.get("title", "")), "url": str(s.get("url", ""))})
            elif isinstance(s, str):
                sources.append({"title": s, "url": s})

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
        )
