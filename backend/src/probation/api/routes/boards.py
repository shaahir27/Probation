"""Pack boards endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /boards/{pack}: Board view for packs with one (radar tracker, reading library):
entries with status, sources and the item behind each.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from probation.config import settings
from probation.synth.world import SimWorld

router = APIRouter(prefix="/api", tags=["boards"])


@router.get("/boards/{pack}")
def get_pack_board(pack: str) -> dict[str, Any]:
    """Retrieve board entries for designated packs (e.g. 'radar', 'reading').

    Reads live state from SimWorld.tracker or SimWorld.library.
    """
    valid_packs = ("radar", "reading")
    if pack not in valid_packs:
        raise HTTPException(status_code=404, detail=f"No board view for pack '{pack}'")

    if not settings.world_db_path.exists():
        # Fall back gracefully if simulated world not yet generated
        return {"pack": pack, "active": True, "entries": []}

    try:
        with SimWorld(settings.world_db_path) as world:
            entries: list[dict[str, Any]] = []

            if pack == "radar":
                raw_entries = world.get_tracker_entries()
                for r in raw_entries:
                    sources = r.get("sources", [])
                    details = r.get("details", {})
                    entries.append(
                        {
                            "id": str(r["id"]),
                            "pack": "radar",
                            "entity": str(r.get("organizer") or r.get("title") or "Opportunity"),
                            "status": str(r.get("status", "TRACKED")),
                            "sources": sources,
                            "item_id": details.get("raw_item_id") or str(r["id"]),
                            "updated_at": str(r.get("updated_at") or r.get("created_at")),
                            "title": str(r.get("title", "")),
                            "deadline_date": r.get("deadline_date"),
                            "official_url": r.get("official_url"),
                            "fee_flag": bool(r.get("fee_flag", False)),
                        }
                    )
                return {"pack": "radar", "active": True, "entries": entries}

            elif pack == "reading":
                raw_entries = world.get_library_entries()
                for r in raw_entries:
                    url = str(r.get("url", ""))
                    entries.append(
                        {
                            "id": str(r["id"]),
                            "pack": "reading",
                            "entity": str(r.get("title") or url),
                            "status": str(r.get("collection", "inbox")),
                            "sources": [{"title": str(r.get("title", "")), "url": url}],
                            "item_id": str(r["id"]),
                            "updated_at": str(r.get("updated_at") or r.get("saved_at")),
                            "collection": str(r.get("collection", "inbox")),
                            "topic": str(r.get("topic", "other")),
                            "content_type": str(r.get("content_type", "article")),
                        }
                    )
                return {"pack": "reading", "active": True, "entries": entries}

    except Exception as exc:
        return {
            "pack": pack,
            "active": False,
            "entries": [],
            "note": f"Error accessing pack '{pack}' board: {exc}",
        }

    return {"pack": pack, "active": False, "entries": []}
