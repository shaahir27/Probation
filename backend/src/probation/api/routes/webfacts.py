"""Web facts transparency endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9 and invariant I-23:
GET /web-facts: Tavily usage (calls, credits, cache hits) and the exact queries sent (transparency page).
CRITICAL: Reads strictly recorded activity from local sqlite tables. Zero outbound HTTP requests.
"""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from probation.config import settings
from probation.db.connection import get_connection

router = APIRouter(prefix="/api", tags=["webfacts"])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/web-facts")
def get_web_facts() -> dict[str, Any]:
    """Retrieve recorded Tavily calls, credits, and exact queries sent.

    Strict invariant: Reading this endpoint NEVER initiates any external network request.
    """
    if not settings.db_path.exists():
        return {
            "total_calls": 0,
            "total_credits": 0,
            "cache_hits": 0,
            "queries": [],
            "entities": [],
        }

    conn = _get_db()
    try:
        cursor = conn.cursor()
        # Query tavily_calls table
        cursor.execute(
            """
            SELECT id, endpoint, query_text, credits, ok, latency_ms, created_at
            FROM tavily_calls
            ORDER BY created_at DESC LIMIT 50;
            """
        )
        call_rows = cursor.fetchall()
        calls = []
        total_credits = 0.0

        for r in call_rows:
            creds = float(r["credits"] or 0.0)
            total_credits += creds
            calls.append(
                {
                    "id": r["id"],
                    "endpoint": r["endpoint"],
                    "query": r["query_text"],
                    "credits": creds,
                    "ok": bool(r["ok"]),
                    "latency_ms": r["latency_ms"],
                    "created_at": r["created_at"],
                }
            )

        # Query web_facts table (derived entity facts)
        cursor.execute(
            """
            SELECT entity_key, status, facts_json, sources_json, fetched_at
            FROM web_facts
            ORDER BY fetched_at DESC LIMIT 50;
            """
        )
        entity_rows = cursor.fetchall()
        entities = []
        for er in entity_rows:
            sources = json.loads(er["sources_json"]) if er["sources_json"] else []
            facts = json.loads(er["facts_json"]) if er["facts_json"] else {}
            entities.append(
                {
                    "domain": er["entity_key"],
                    "status": er["status"],
                    "facts": facts,
                    "sources": sources,
                    "fetched_at": er["fetched_at"],
                }
            )

        return {
            "total_calls": len(calls),
            "total_credits": round(total_credits, 2),
            "queries": calls,
            "entities": entities,
        }
    finally:
        conn.close()
