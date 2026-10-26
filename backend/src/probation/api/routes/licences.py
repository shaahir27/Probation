"""Licences endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /licences: Current derived licences with evidence, plus the last 5 changes of each
(from the ledger licence_change entries).
"""

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.config import settings
from probation.core.clock import get_clock
from probation.engine.licence import derive_licences

router = APIRouter(prefix="/api", tags=["licences"], dependencies=[Depends(require_owner)])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


def _licence_payload(source_ids: tuple[str, ...] | None) -> dict[str, Any]:
    if not settings.db_path.exists():
        return {"licences": [], "total_count": 0}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        as_of = get_clock().now_iso()
        views = derive_licences(conn, as_of, source_ids=source_ids)
        licences = []
        for (ck, act), view in views.items():
            n_strong, k_strong = view.n_strong, view.k_strong
            n_all, k_all, n_recent = view.n_all, view.k_all, view.n_recent
            valid_until, exam_run_id = view.valid_until, view.exam_run_id
            reasons, level, lb = view.reasons, int(view.level), view.lower_bound

            # Query last 5 ledger licence changes for this (class_key, action)
            if source_ids is None:
                cursor.execute(
                    """
                    SELECT seq, payload_json, created_at
                    FROM ledger
                    WHERE kind = 'licence_change'
                      AND json_extract(payload_json, '$.class_key') = ?
                      AND json_extract(payload_json, '$.action') = ?
                      AND created_at COLLATE UTC_TIMESTAMP <= ?
                    ORDER BY seq DESC LIMIT 5;
                    """,
                    (ck, act, as_of),
                )
                change_rows = cursor.fetchall()
            else:
                change_rows = []
            history = []
            for cr in change_rows:
                p = json.loads(cr["payload_json"]) if cr["payload_json"] else {}
                history.append(
                    {
                        "seq": cr["seq"],
                        "created_at": cr["created_at"],
                        "old_level": p.get("old_level", p.get("prev_level")),
                        "new_level": p.get("new_level"),
                        "reason": p.get("reason"),
                        "reasons": p.get("reasons", [p["reason"]] if p.get("reason") else []),
                    }
                )

            # Check for drift state / alarms
            if source_ids is None:
                cursor.execute(
                    "SELECT cusum, baseline_err, last_alarm_at FROM drift_state WHERE class_key = ? AND action = ? AND (last_alarm_at IS NULL OR last_alarm_at COLLATE UTC_TIMESTAMP <= ?);",
                    (ck, act, as_of),
                )
                d_row = cursor.fetchone()
            else:
                d_row = None
            drift_info = None
            if d_row:
                drift_info = {
                    "cusum": d_row["cusum"],
                    "baseline_err": d_row["baseline_err"],
                    "last_alarm_at": d_row["last_alarm_at"],
                }

            licences.append(
                {
                    "class_key": ck,
                    "action": act,
                    "level": level,
                    "lower_bound": lb,
                    "exam_ok": view.exam_ok,
                    "lb_strong": view.lb_strong,
                    "lb_all": view.lb_all,
                    "agreement_strong": k_strong / n_strong if n_strong else None,
                    "as_of": as_of,
                    "n_strong": n_strong,
                    "k_strong": k_strong,
                    "n_all": n_all,
                    "k_all": k_all,
                    "n_recent": n_recent,
                    "exam_run_id": exam_run_id,
                    "valid_until": valid_until,
                    "reasons": reasons,
                    "drift": drift_info,
                    "history": history,
                }
            )

        result: dict[str, Any] = {"licences": licences, "total_count": len(licences)}
        if source_ids is not None:
            result["source_cutoff"] = as_of
        return result
    finally:
        conn.close()


@router.get("/licences")
def get_licences() -> dict[str, Any]:
    """Legacy licence view, retaining its existing response and history semantics."""
    return _licence_payload(None)


@router.get("/permissions")
def get_permissions(
    owner: Annotated[OwnerContext, Depends(require_owner)],
) -> dict[str, Any]:
    """Derived permissions restricted to the authenticated owner's registered sources."""
    return _licence_payload(tuple(grant.source_id for grant in owner.grants))
