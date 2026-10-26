"""Web facts transparency endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9 and invariant I-23:
GET /web-facts: Tavily usage (calls, credits, cache hits) and the exact queries sent (transparency page).
CRITICAL: Reads strictly recorded activity from local sqlite tables. Zero outbound HTTP requests.
"""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probation.api.authority import require_owner
from probation.api.db import connect_api as get_connection
from probation.config import settings
from probation.web.accounting import accounting_summary

router = APIRouter(prefix="/api", tags=["webfacts"], dependencies=[Depends(require_owner)])


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
            "version": "d5.v1",
            "total_calls": 0,
            "physical_attempts": 0,
            "total_credits": 0,
            "cache_hits": 0,
            "held_credits": 0,
            "unknown_attempts": 0,
            "legacy_rows": 0,
            "rejected_queries": 0,
            "queries": [],
            "entities": [],
        }

    conn = _get_db()
    try:
        cursor = conn.cursor()
        # Query tavily_calls table
        cursor.execute(
            """
            SELECT id, endpoint, query_text, credits, ok, latency_ms, created_at,
                   accounting_version,state,reserved_units,charged_units,usage_provenance,
                   dispatched_at,reconciled_at,error_code
            FROM tavily_calls
            ORDER BY created_at COLLATE UTC_TIMESTAMP DESC LIMIT 50;
            """
        )
        call_rows = cursor.fetchall()
        calls = []

        for r in call_rows:
            creds = float(r["credits"] or 0.0)
            calls.append(
                {
                    "id": r["id"],
                    "endpoint": r["endpoint"],
                    "query": r["query_text"],
                    "credits": creds,
                    "ok": bool(r["ok"]),
                    "latency_ms": r["latency_ms"],
                    "created_at": r["created_at"],
                    "state": r["state"] or "legacy_unknown",
                    "usage_provenance": r["usage_provenance"] or "legacy_unverified",
                    "confirmed_credits": r["charged_units"] / 1000
                    if r["charged_units"] is not None
                    else None,
                    "reserved_credits": r["reserved_units"] / 1000
                    if r["reserved_units"] is not None
                    else None,
                    "dispatched_at": r["dispatched_at"],
                    "reconciled_at": r["reconciled_at"],
                    "error_code": r["error_code"],
                }
            )

        # Query web_facts table (derived entity facts)
        cursor.execute(
            """
            SELECT entity_key, status, facts_json, sources_json, fetched_at,ttl_until,
                   origin,present_knowledge
            FROM web_facts
            ORDER BY fetched_at COLLATE UTC_TIMESTAMP DESC LIMIT 50;
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
                    "ttl_until": er["ttl_until"],
                    "origin": er["origin"],
                    "present_knowledge": bool(er["present_knowledge"]),
                }
            )

        return {
            "version": "d5.v1",
            **accounting_summary(conn),
            "cache_hits": None,
            "cache_hit_availability": "not_persisted_as_attempts",
            "queries": calls,
            "entities": entities,
        }
    finally:
        conn.close()
