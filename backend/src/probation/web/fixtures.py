"""Fixture loader for Entity Facts Service.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 5.7.
Populates web_facts table with recorded fixtures (origin='fixture', present_knowledge=1)
allowing completely deterministic and offline replay and testing.
"""

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

from probation.core.clock import Clock
from probation.core.hashing import canonical_json
from probation.db.access import Role, RoleAccess


def load_web_facts_fixtures(
    conn: sqlite3.Connection,
    fixtures_path: Path | None = None,
) -> int:
    """Load recorded entity facts fixtures into web_facts table."""
    path = fixtures_path
    if path is None:
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "tests" / "fixtures" / "web_facts_fixtures.json"
            if candidate.exists():
                path = candidate
                break

    if path is None or not path.exists():
        return 0

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    entities = data.get("entities", [])
    access = RoleAccess(conn, Role.WEBFACTS)

    now_iso = Clock().now_iso()
    future_iso = (Clock().now() + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0

    for ent in entities:
        domain = str(ent["entity_key"])
        status = str(ent["status"])
        facts = ent.get("facts", {})
        sources = ent.get("sources", [])
        origin = "fixture"

        access.execute_write(
            "web_facts",
            """
            INSERT OR REPLACE INTO web_facts
            (entity_key, status, facts_json, sources_json, origin, present_knowledge, fetched_at, ttl_until)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                domain,
                status,
                canonical_json(facts),
                canonical_json(sources),
                origin,
                1,
                now_iso,
                future_iso,
            ),
        )
        count += 1

    access.commit()
    return count
