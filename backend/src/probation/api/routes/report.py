"""Report card endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /report-card?family= : Backtest summary: same / different / would-ask counts.
"""

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from probation.api.authority import require_owner
from probation.api.db import connect_api as get_connection
from probation.config import settings
from probation.engine.report import generate_report_card

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(require_owner)])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/report-card")
def get_report_card(
    family: str | None = Query(
        None, description="Decision family (e.g. email_action, calendar_action)"
    ),
    class_key: str | None = Query(None, max_length=160, description="Task class key"),
    action: str | None = Query(None, max_length=48, description="Action within the task"),
    since: str | None = Query(None, max_length=32, description="Inclusive period start"),
    as_of: str | None = Query(None, max_length=32, description="Evidence cutoff"),
) -> dict[str, Any]:
    """Family/task/action-scoped backtest summary, bounded by the same cutoff the engine uses."""
    if not settings.db_path.exists():
        return {
            "family": family or "all",
            "same": 0,
            "different": 0,
            "would_ask": 0,
            "censored": 0,
            "accuracy": None,
            "scope": "empty_cohort",
            "tasks": [],
            "filters": {"family": family, "class_key": class_key, "action": action},
        }

    conn = _get_db()
    try:
        try:
            card = generate_report_card(
                conn,
                family=family,
                as_of=as_of,
                since=since,
                class_key=class_key,
                action=action,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "family": card.get("family", family or "all"),
            "as_of": card.get("as_of"),
            "total_proposals": card.get("total_proposals", 0),
            "total_evaluated": card.get("total_evaluated", 0),
            "same": card.get("same", 0),
            "different": card.get("different", 0),
            "would_ask": card.get("would_ask", 0),
            "censored": card.get("censored", 0),
            "accuracy": card.get("accuracy"),
            "scope": "filtered_cohort"
            if (class_key or action or since or as_of)
            else "family_summary",
            "tasks": card.get("tasks", []),
            "filters": {"family": family, "class_key": class_key, "action": action},
        }
    finally:
        conn.close()
