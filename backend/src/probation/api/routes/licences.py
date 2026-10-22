"""Licences endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /licences: Current derived licences with evidence, plus the last 5 changes of each
(from the ledger licence_change entries).
"""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException

from probation.config import settings
from probation.db.connection import get_connection
from probation.engine.licence import derive_licence_level

router = APIRouter(prefix="/api", tags=["licences"])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/licences")
def get_licences() -> dict[str, Any]:
    """Retrieve all current derived licences with evidence and last 5 ledger licence changes."""
    if not settings.db_path.exists():
        return {"licences": [], "total_count": 0}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        # Find all distinct (class_key, action) pairs in proposals or class_stats
        cursor.execute(
            """
            SELECT DISTINCT class_key, action FROM proposals
            UNION
            SELECT DISTINCT class_key, action FROM class_stats;
            """
        )
        pairs = cursor.fetchall()

        licences = []
        for pair in pairs:
            ck = pair["class_key"]
            act = pair["action"]

            # Query class stats for this pair
            cursor.execute(
                """
                SELECT * FROM class_stats
                WHERE class_key = ? AND action = ?
                ORDER BY as_of COLLATE UTC_TIMESTAMP DESC LIMIT 1;
                """,
                (ck, act),
            )
            s_row = cursor.fetchone()

            # Query licence cache if present
            cursor.execute(
                """
                SELECT level, lower_bound, reasons_json, exam_run_id, valid_until
                FROM licence_cache
                WHERE class_key = ? AND action = ?;
                """,
                (ck, act),
            )
            c_row = cursor.fetchone()

            if s_row:
                n_strong = int(s_row["n_strong"])
                k_strong = int(s_row["k_strong"])
                n_all = int(s_row["n_all"])
                k_all = int(s_row["k_all"])
                n_recent = int(s_row["n_recent"])
                lb_strong = float(s_row["lb_strong"])
                lb_all = float(s_row["lb_all"])
                valid_until = c_row["valid_until"] if c_row else ""
                exam_run_id = c_row["exam_run_id"] if c_row else None
                reasons = (
                    json.loads(c_row["reasons_json"]) if c_row and c_row["reasons_json"] else []
                )

                level_val = derive_licence_level(
                    action=act,
                    n_all=n_all,
                    lb_all=lb_all,
                    n_strong=n_strong,
                    lb_strong=lb_strong,
                    n_recent=n_recent,
                )
                level = int(level_val.value)
                lb = lb_strong
            elif c_row:
                level = int(c_row["level"])
                lb = float(c_row["lower_bound"])
                n_strong, k_strong, n_all, k_all, n_recent = 0, 0, 0, 0, 0
                valid_until = c_row["valid_until"]
                exam_run_id = c_row["exam_run_id"]
                reasons = json.loads(c_row["reasons_json"]) if c_row["reasons_json"] else []
            else:
                level = 0
                lb = 0.0
                n_strong, k_strong, n_all, k_all, n_recent = 0, 0, 0, 0, 0
                valid_until = ""
                exam_run_id = None
                reasons = ["not_enough_history"]

            # Query last 5 ledger licence changes for this (class_key, action)
            cursor.execute(
                """
                SELECT seq, payload_json, created_at
                FROM ledger
                WHERE kind = 'licence_change'
                  AND json_extract(payload_json, '$.class_key') = ?
                  AND json_extract(payload_json, '$.action') = ?
                ORDER BY seq DESC LIMIT 5;
                """,
                (ck, act),
            )
            change_rows = cursor.fetchall()
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
                    }
                )

            # Check for drift state / alarms
            cursor.execute(
                "SELECT cusum, baseline_err, last_alarm_at FROM drift_state WHERE class_key = ? AND action = ?;",
                (ck, act),
            )
            d_row = cursor.fetchone()
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

        return {"licences": licences, "total_count": len(licences)}
    finally:
        conn.close()
