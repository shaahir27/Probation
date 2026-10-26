"""Read-only views over the locally persisted radar and reading boards."""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probation.api.authority import require_owner
from probation.config import settings

router = APIRouter(prefix="/api", tags=["boards"], dependencies=[Depends(require_owner)])


def _unavailable(pack: str, reason: str) -> dict[str, Any]:
    return {
        "pack": pack,
        "active": False,
        "availability": "unavailable",
        "reason": reason,
        "entries": [],
    }


def _json(value: object, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


@router.get("/boards/{pack}")
def get_pack_board(pack: str) -> dict[str, Any]:
    """Read existing board rows without constructing a world or creating schema."""
    if pack not in {"radar", "reading"}:
        raise HTTPException(status_code=404, detail="board_not_found")
    path = settings.world_db_path
    if not path.is_file():
        return _unavailable(pack, "not_initialized")

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        table = "tracker" if pack == "radar" else "library"
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists is None:
            return _unavailable(pack, "not_initialized")

        rows = conn.execute(f"SELECT * FROM {table} ORDER BY updated_at DESC").fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            if pack == "radar":
                sources = _json(row["sources_json"], [])
                details = _json(row["details_json"], {})
                entries.append(
                    {
                        "id": str(row["id"]),
                        "pack": "radar",
                        "entity": str(row["organizer"] or row["title"] or "Opportunity"),
                        "status": str(row["status"]),
                        "sources": sources if isinstance(sources, list) else [],
                        "item_id": details.get("raw_item_id") or str(row["id"])
                        if isinstance(details, dict)
                        else str(row["id"]),
                        "updated_at": str(row["updated_at"] or row["created_at"]),
                        "title": str(row["title"] or ""),
                        "deadline_date": row["deadline_date"],
                        "official_url": row["official_url"],
                        "fee_flag": bool(row["fee_flag"]),
                    }
                )
            else:
                url = str(row["url"] or "")
                title = str(row["title"] or "")
                entries.append(
                    {
                        "id": str(row["id"]),
                        "pack": "reading",
                        "entity": title or url,
                        "status": str(row["collection"]),
                        "sources": [{"title": title, "url": url}],
                        "item_id": str(row["id"]),
                        "updated_at": str(row["updated_at"] or row["saved_at"]),
                        "collection": str(row["collection"]),
                        "topic": str(row["topic"] or "other"),
                        "content_type": str(row["content_type"] or "article"),
                    }
                )
        return {"pack": pack, "active": True, "availability": "available", "entries": entries}
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError):
        return _unavailable(pack, "board_unavailable")
    finally:
        if conn is not None:
            conn.close()
