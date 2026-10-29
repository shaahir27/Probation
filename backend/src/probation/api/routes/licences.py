"""Licences endpoint per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /licences: Current derived licences with evidence, plus the last 5 changes of each
(from the ledger licence_change entries).
"""

import json
import math
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.api.labels import task_title
from probation.config import settings
from probation.core.actions import InvalidAction, parse_action
from probation.core.clock import get_clock
from probation.engine.caps import get_action_cap, is_recallable
from probation.engine.licence import derive_licences, family_for_class

router = APIRouter(prefix="/api", tags=["licences"], dependencies=[Depends(require_owner)])


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


def _is_noop(action: str) -> bool:
    try:
        return parse_action(action).is_noop
    except InvalidAction:
        return True


def _checklist(
    level: int,
    action: str,
    n_strong: int,
    n_recent: int,
    n_all: int,
    lb_all: float,
    exam_ok: bool,
    exam_run_id: str | None,
    drift: dict[str, Any] | None,
    cap: int,
) -> dict[str, Any]:
    """The gates that still stand between this pair and its next level, plus a forecast.

    Level 0 is watching; its next gate is level 1 and is measured on all decisions, not
    strong ones. The forecast inverts the same Beta lower bound the engine uses, so it
    cannot promise a volume the licence would refuse.
    """
    from probation.engine.evidence import lower_bound

    noop = _is_noop(action)
    target: tuple[int, float, int, str] | None = None
    if not noop and cap >= 1:
        if level < 1:
            target = (1, settings.l1_min_lb, n_all, "all")
        elif level < 2:
            target = (2, settings.l2_min_lb, n_strong, "strong")
        elif level == 2 and is_recallable(action) and cap >= 3:
            target = (3, settings.l3_min_lb, n_strong, "strong")

    forecast = None
    if target is not None:
        target_level, target_lb, current_n, basis = target
        minimum = settings.l1_min_n if target_level == 1 else settings.strong_min_raw_n
        need = max(minimum, current_n)
        while (
            need < 10_000
            and lower_bound(k=need, n=need, kappa=settings.pooling_kappa, q=settings.lb_quantile)
            < target_lb
        ):
            need += 1
        remaining = max(0, need - current_n)
        pace = n_recent / 30.0
        forecast = {
            "level": target_level,
            "clean_agreements_needed": need,
            "remaining_clean": remaining,
            "estimated_days": math.ceil(remaining / pace) if pace > 0 and remaining else 0,
            "basis": basis,
            "exam_required": target_level >= 2,
        }

    return {
        "evidence": {
            "have": n_strong,
            "need": settings.strong_min_raw_n,
            "met": n_strong >= settings.strong_min_raw_n,
        },
        "history": {
            "have": n_all,
            "need": settings.l1_min_n,
            "met": n_all >= settings.l1_min_n and lb_all >= settings.l1_min_lb,
            "lower_bound": lb_all,
        },
        "recent": {
            "have": n_recent,
            "need": settings.licence_min_recent_n,
            "met": n_recent >= settings.licence_min_recent_n,
        },
        "exam": {"met": exam_ok, "run_id": exam_run_id},
        "alarm": {
            "met": not (drift and drift.get("last_alarm_at")),
            "last_alarm_at": drift.get("last_alarm_at") if drift else None,
        },
        "next": forecast,
    }


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

            # Query last 5 ledger licence changes for this (class_key, action). The
            # pair is owner-scoped by this payload; the changes are task-level evidence.
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

            # Check for drift state / alarms. Drift is workspace-level state for the pair.
            cursor.execute(
                "SELECT cusum, baseline_err, last_alarm_at FROM drift_state WHERE class_key = ? AND action = ? AND (last_alarm_at IS NULL OR last_alarm_at COLLATE UTC_TIMESTAMP <= ?);",
                (ck, act, as_of),
            )
            d_row = cursor.fetchone()
            drift_info = None
            if d_row:
                drift_info = {
                    "cusum": d_row["cusum"],
                    "baseline_err": d_row["baseline_err"],
                    "last_alarm_at": d_row["last_alarm_at"],
                    "scope": "workspace",
                }

            family = family_for_class(ck)
            cap = get_action_cap(
                act,
                family=family,
                sender_tier=ck.split("|")[-1] if family == "email_action" else None,
                organizer_tier=ck.split("|")[1] if family == "invite_rsvp" and "|" in ck else None,
            )
            checklist = _checklist(
                level,
                act,
                n_strong,
                n_recent,
                n_all,
                view.lb_all,
                view.exam_ok,
                exam_run_id,
                drift_info,
                cap,
            )
            licences.append(
                {
                    "class_key": ck,
                    "title": task_title(ck),
                    "action": act,
                    "level": level,
                    "lower_bound": lb,
                    "exam_ok": view.exam_ok,
                    "checklist": checklist,
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
                    "history_scope": "task",
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
