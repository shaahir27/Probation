"""Pack boards endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /boards/{pack}: Board view for packs with one (radar tracker, reading library):
entries with status, sources and the item behind each.
"""

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from probation.config import settings
from probation.db.connection import get_connection

router = APIRouter(prefix="/api", tags=["boards"])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/boards/{pack}")
def get_pack_board(pack: str) -> dict[str, Any]:
    """Retrieve board entries for designated packs (e.g. 'radar', 'reading').

    If the pack is not yet registered or has no active board table,
    returns empty items list with active=False, respecting fail-closed UI rules.
    """
    valid_packs = ("radar", "reading")
    if pack not in valid_packs:
        raise HTTPException(status_code=404, detail=f"No board view for pack '{pack}'")

    if not settings.db_path.exists():
        return {"pack": pack, "active": False, "entries": []}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        # Check if radar / reading tables exist in SQLite schema
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?;",
            (f"{pack}_board",),
        )
        has_table = cursor.fetchone() is not None

        if not has_table:
            # Table does not exist in schema yet (e.g. radar/reading planned for Phase 8b)
            return {
                "pack": pack,
                "active": False,
                "entries": [],
                "note": f"Pack '{pack}' board is planned and not currently active.",
            }

        cursor.execute(f"SELECT * FROM {pack}_board ORDER BY updated_at DESC;")
        rows = cursor.fetchall()
        entries = []
        for r in rows:
            entries.append(dict(r))

        return {"pack": pack, "active": True, "entries": entries}
    finally:
        conn.close()
