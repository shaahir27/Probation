"""Insights endpoints per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
- GET /metrics/summary: Scorecard numbers plus weekly time series (asks, suggestions, automatic actions, agreement)
  and the list of drift and family-shift alarms.
- GET /habits: Mined habits.
- POST /habits/{id}/deny: Deny disables a habit.
- GET /chains: Mined chains.
- GET /exams: Exam history with per-case verdicts.
- POST /exams/run: Run an exam (admin).
"""

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import GateDecision
from probation.db.connection import get_connection
from probation.workers.examiner import run_examiner_job

router = APIRouter(prefix="/api", tags=["insights"])


class RunExamBody(BaseModel):
    class_key: str = Field(..., description="Target class key")
    action: str = Field(..., description="Target action")
    level: int = Field(default=2, description="Target autonomy level (2 or 3)")


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/metrics/summary")
def get_metrics_summary() -> dict[str, Any]:
    """Scorecard numbers and time series per CONTRACT.md section 9."""
    if not settings.db_path.exists():
        return {
            "proposals_total": 0,
            "asks": 0,
            "suggestions": 0,
            "automatic_actions": 0,
            "agreement_rate": None,
            "weekly_series": [],
            "alarms": [],
        }

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt, gate FROM proposals GROUP BY gate;")
        gate_counts = {r["gate"]: r["cnt"] for r in cursor.fetchall()}

        asks = gate_counts.get(GateDecision.ASK.value, 0)
        suggestions = gate_counts.get(GateDecision.SUGGEST.value, 0)
        auto_exec = sum(
            gate_counts.get(g, 0)
            for g in (
                GateDecision.HOLD_THEN_EXECUTE.value,
                GateDecision.EXECUTE_UNDO.value,
                GateDecision.EXECUTE_SILENT.value,
            )
        )
        total_props = sum(gate_counts.values())

        # Outcomes agreement calculation
        cursor.execute(
            """
            SELECT p.action AS prop_act, o.observed_action
            FROM proposals p
            JOIN outcomes o ON p.situation_id = o.situation_id
            WHERE o.strength = 'STRONG';
            """
        )
        matched_rows = cursor.fetchall()
        same_count = sum(1 for r in matched_rows if r["prop_act"] == r["observed_action"])
        diff_count = len(matched_rows) - same_count
        agreement = (
            round(same_count / (same_count + diff_count), 4)
            if (same_count + diff_count) > 0
            else None
        )

        # Weekly time series
        cursor.execute(
            """
            SELECT strftime('%Y-W%W', proposed_at) AS week,
                   SUM(CASE WHEN gate = 'ASK' THEN 1 ELSE 0 END) AS asks,
                   SUM(CASE WHEN gate = 'SUGGEST' THEN 1 ELSE 0 END) AS suggestions,
                   SUM(CASE WHEN gate IN ('HOLD_THEN_EXECUTE','EXECUTE_UNDO','EXECUTE_SILENT') THEN 1 ELSE 0 END) AS auto_actions,
                   COUNT(*) AS total
            FROM proposals
            GROUP BY week
            ORDER BY week ASC;
            """
        )
        series_rows = cursor.fetchall()
        weekly_series = [
            {
                "week": r["week"],
                "asks": r["asks"],
                "suggestions": r["suggestions"],
                "auto_actions": r["auto_actions"],
                "total": r["total"],
            }
            for r in series_rows
        ]

        # Drift and family-shift alarms from ledger
        cursor.execute(
            """
            SELECT seq, kind, ref_id, payload_json, created_at
            FROM ledger
            WHERE kind IN ('drift_alarm', 'family_shift')
            ORDER BY seq DESC LIMIT 20;
            """
        )
        alarm_rows = cursor.fetchall()
        alarms = [
            {
                "seq": r["seq"],
                "kind": r["kind"],
                "ref_id": r["ref_id"],
                "payload": json.loads(r["payload_json"]) if r["payload_json"] else {},
                "created_at": r["created_at"],
            }
            for r in alarm_rows
        ]

        return {
            "proposals_total": total_props,
            "asks": asks,
            "suggestions": suggestions,
            "automatic_actions": auto_exec,
            "agreement_rate": agreement,
            "weekly_series": weekly_series,
            "alarms": alarms,
        }
    finally:
        conn.close()


@router.get("/habits")
def get_habits() -> dict[str, Any]:
    """Retrieve mined habits."""
    if not settings.db_path.exists():
        return {"habits": []}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, family, clue, clue_value, action, k, n, lift, q_value, statement, examples_json, status, created_at
            FROM habits
            ORDER BY created_at DESC;
            """
        )
        rows = cursor.fetchall()
        habits = [
            {
                "id": r["id"],
                "family": r["family"],
                "clue": r["clue"],
                "clue_value": r["clue_value"],
                "action": r["action"],
                "k": r["k"],
                "n": r["n"],
                "lift": r["lift"],
                "q_value": r["q_value"],
                "statement": r["statement"],
                "examples": json.loads(r["examples_json"]) if r["examples_json"] else [],
                "status": r["status"],
                "denied": r["status"] == "denied",
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return {"habits": habits}
    finally:
        conn.close()


@router.post("/habits/{habit_id}/deny")
def deny_habit(habit_id: str) -> dict[str, Any]:
    """Deny / disable a mined habit."""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM habits WHERE id = ?;", (habit_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Habit '{habit_id}' not found")

        cursor.execute("UPDATE habits SET status = 'denied' WHERE id = ?;", (habit_id,))
        conn.commit()
        return {"ok": True, "habit_id": habit_id, "denied": True}
    finally:
        conn.close()


@router.get("/chains")
def get_chains() -> dict[str, Any]:
    """Retrieve mined chains."""
    if not settings.db_path.exists():
        return {"chains": []}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, trigger_class_key, follow_action, k, n, base_rate, lift, status, created_at
            FROM chains
            ORDER BY created_at DESC;
            """
        )
        rows = cursor.fetchall()
        chains = [
            {
                "id": r["id"],
                "trigger_class_key": r["trigger_class_key"],
                "follow_action": r["follow_action"],
                "k": r["k"],
                "n": r["n"],
                "base_rate": r["base_rate"],
                "lift": r["lift"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return {"chains": chains}
    finally:
        conn.close()


@router.get("/exams")
def get_exams() -> dict[str, Any]:
    """Exam history with per-case verdicts."""
    if not settings.db_path.exists():
        return {"runs": []}

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, class_key, action, level_tested, started_at, finished_at,
                   n_cases, invariance_flip_rate, directional_violations_critical,
                   passed, details_json
            FROM exam_runs
            ORDER BY started_at DESC;
            """
        )
        runs = []
        for r in cursor.fetchall():
            run_id = r["id"]
            cursor.execute(
                """
                SELECT id, base_situation_id, operator, expectation, edit_valid,
                       decision_before, decision_after, violated, critical
                FROM exam_cases
                WHERE exam_run_id = ?;
                """,
                (run_id,),
            )
            cases = [
                {
                    "id": c["id"],
                    "situation_id": c["base_situation_id"],
                    "operator": c["operator"],
                    "expectation": c["expectation"],
                    "edit_valid": bool(c["edit_valid"]),
                    "decision_before": c["decision_before"],
                    "decision_after": c["decision_after"],
                    "violated": bool(c["violated"]) if c["violated"] is not None else False,
                    "critical": bool(c["critical"]),
                }
                for c in cursor.fetchall()
            ]
            runs.append(
                {
                    "id": run_id,
                    "class_key": r["class_key"],
                    "action": r["action"],
                    "level_tested": r["level_tested"],
                    "started_at": r["started_at"],
                    "finished_at": r["finished_at"],
                    "n_cases": r["n_cases"],
                    "invariance_flip_rate": r["invariance_flip_rate"],
                    "critical_violations": r["directional_violations_critical"],
                    "passed": bool(r["passed"]) if r["passed"] is not None else None,
                    "details": json.loads(r["details_json"]) if r["details_json"] else {},
                    "cases": cases,
                }
            )
        return {"runs": runs}
    finally:
        conn.close()


@router.post("/exams/run")
def run_exam(body: RunExamBody) -> dict[str, Any]:
    """Trigger an exam run for an authorized (class_key, action) pair."""
    conn = _get_db()
    try:
        class_key = body.class_key
        action = body.action
        level = body.level

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM proposals WHERE class_key = ?;", (class_key,))
        cnt_row = cursor.fetchone()
        if not cnt_row or cnt_row[0] == 0:
            cursor.execute(
                "SELECT class_key, action FROM licence_cache ORDER BY level DESC, lower_bound DESC LIMIT 1;"
            )
            cand = cursor.fetchone()
            if cand:
                class_key = str(cand["class_key"])
                action = str(cand["action"])

        res = run_examiner_job(
            conn=conn,
            class_key=class_key,
            action=action,
            level=level,
        )
        return {
            "ok": True,
            "run_id": res.run_id,
            "class_key": res.class_key,
            "action": res.action,
            "level_tested": res.level_tested,
            "passed": res.passed,
            "n_cases": res.n_cases,
            "invariance_flip_rate": res.invariance_flip_rate,
            "critical_violations": res.critical_violations,
            "other_violation_rate": res.other_violation_rate,
            "ran_at": Clock().now_iso(),
        }
    finally:
        conn.close()
