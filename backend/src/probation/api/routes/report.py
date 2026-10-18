"""Report card endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /report-card?family= : Backtest summary: same / different / would-ask counts.
"""

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from probation.config import settings
from probation.db.connection import get_connection
from probation.engine.report import generate_report_card

router = APIRouter(prefix="/api", tags=["report"])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/report-card")
def get_report_card(
    family: str = Query(..., description="Decision family (e.g. email_action, calendar_action)"),
) -> dict[str, Any]:
    """Retrieve family-scoped backtest summary."""
    if not settings.db_path.exists():
        return {
            "family": family,
            "same": 0,
            "different": 0,
            "would_ask": 0,
            "censored": 0,
            "accuracy": None,
            "scope": "family_summary",
        }

    conn = _get_db()
    try:
        card = generate_report_card(conn, family=family)
        return {
            "family": card.get("family", family),
            "as_of": card.get("as_of"),
            "total_proposals": card.get("total_proposals", 0),
            "total_evaluated": card.get("total_evaluated", 0),
            "same": card.get("same", 0),
            "different": card.get("different", 0),
            "would_ask": card.get("would_ask", 0),
            "censored": card.get("censored", 0),
            "accuracy": card.get("accuracy"),
            "scope": "family_summary",
        }
    finally:
        conn.close()
