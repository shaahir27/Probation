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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.config import settings
from probation.core.clock import get_clock, timestamp_key
from probation.core.enums import GateDecision
from probation.core.permission_history import permission_records
from probation.db.access import Role, RoleAccess
from probation.db.commands import DenyHabit, RunExam, command_record, enqueue_command
from probation.engine.report import rate

router = APIRouter(prefix="/api", tags=["insights"], dependencies=[Depends(require_owner)])


RunExamBody = RunExam


def _get_db() -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise HTTPException(status_code=503, detail="Database not initialized")
    return get_connection(settings.db_path)


@router.get("/metrics/summary")
def get_metrics_summary(
    owner: Annotated[OwnerContext, Depends(require_owner)],
    family: Annotated[str | None, Query(max_length=64)] = None,
    class_key: Annotated[str | None, Query(max_length=160)] = None,
    action: Annotated[str | None, Query(max_length=48)] = None,
    as_of: Annotated[str | None, Query(max_length=32)] = None,
) -> dict[str, Any]:
    """Scorecard numbers per CONTRACT.md section 9, bounded by cutoff, filter and owner scope.

    Intended decisions and confirmed effects are counted separately: a proposal to act is
    never reported as an action that happened.
    """
    empty: dict[str, Any] = {
        "proposals_total": 0,
        "asks": 0,
        "suggestions": 0,
        "intended_actions": 0,
        "confirmed_effects": 0,
        "unconfirmed_effects": 0,
        "agreement": None,
        "weekly_series": [],
        "alarms": [],
        "scope": {
            "family": family,
            "class_key": class_key,
            "action": action,
            "sources": len(owner.grants),
        },
    }
    if not settings.db_path.exists():
        return empty
    cutoff = get_clock().now_iso() if as_of is None else as_of
    if timestamp_key(cutoff) > timestamp_key(get_clock().now_iso()):
        raise HTTPException(status_code=400, detail="cutoff_in_future")
    allowed_sources = tuple(grant.source_id for grant in owner.grants)
    if not allowed_sources:
        return empty

    conn = _get_db()
    try:
        pair = ",".join("?" for _ in allowed_sources)
        filters = (
            " AND (? IS NULL OR p.family=?) AND (? IS NULL OR p.class_key=?)"
            " AND (? IS NULL OR p.action=?)"
        )
        filter_params: tuple[Any, ...] = (
            family,
            family,
            class_key,
            class_key,
            action,
            action,
        )
        scope_params = (cutoff, cutoff, cutoff, *allowed_sources, *filter_params)
        cursor = conn.cursor()
        cursor.execute(
            f"""SELECT p.gate, COUNT(*) AS cnt FROM proposals p
                JOIN situations s ON s.id=p.situation_id
                JOIN raw_items r ON r.id=s.raw_item_id
                WHERE p.proposed_at COLLATE UTC_TIMESTAMP <= ?
                  AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
                  AND r.known_at COLLATE UTC_TIMESTAMP <= ?
                  AND r.source_id IN ({pair}){filters}
                GROUP BY p.gate;""",
            scope_params,
        )
        gate_counts = {str(r["gate"]): int(r["cnt"]) for r in cursor.fetchall()}
        asks = gate_counts.get(GateDecision.ASK.value, 0)
        suggestions = gate_counts.get(GateDecision.SUGGEST.value, 0)
        intended = sum(
            gate_counts.get(g.value, 0)
            for g in (
                GateDecision.HOLD_THEN_EXECUTE,
                GateDecision.EXECUTE_UNDO,
                GateDecision.EXECUTE_SILENT,
            )
        )
        total_props = sum(gate_counts.values())

        # Agreement uses the same append-only, cutoff-bounded evidence the licence maths uses:
        # one genuine vote per situation, never the mutable final-state table.
        records = permission_records(conn, cutoff, family, source_ids=allowed_sources)
        evaluated = [
            record
            for record in records
            if class_key in (None, record["class_key"]) and action in (None, record["action"])
        ]
        same = sum(
            1
            for record in evaluated
            if record["decision"].get("observed_action") == record["action"]
        )
        agreement = rate(same, len(evaluated))

        cursor.execute(
            f"""SELECT COUNT(*) AS cnt FROM actions a
                JOIN proposals p ON p.id=a.proposal_id
                JOIN situations s ON s.id=p.situation_id
                JOIN raw_items r ON r.id=s.raw_item_id
                WHERE a.status IN ('DONE','UNDONE')
                  AND COALESCE(a.executed_at, a.created_at) COLLATE UTC_TIMESTAMP <= ?
                  AND r.source_id IN ({pair}){filters}""",
            (cutoff, *allowed_sources, *filter_params),
        )
        confirmed = int(cursor.fetchone()["cnt"] or 0)
        cursor.execute(
            """SELECT COUNT(*) AS cnt FROM execution_attempts
               WHERE state IN ('unknown','dispatched')
                 AND updated_at COLLATE UTC_TIMESTAMP <= ?""",
            (cutoff,),
        )
        unconfirmed = int(cursor.fetchone()["cnt"] or 0)

        cursor.execute(
            f"""SELECT strftime('%Y-W%W', p.proposed_at) AS week,
                       SUM(CASE WHEN p.gate='ASK' THEN 1 ELSE 0 END) AS asks,
                       SUM(CASE WHEN p.gate='SUGGEST' THEN 1 ELSE 0 END) AS suggestions,
                       SUM(CASE WHEN p.gate IN ('HOLD_THEN_EXECUTE','EXECUTE_UNDO','EXECUTE_SILENT')
                           THEN 1 ELSE 0 END) AS intended_actions,
                       COUNT(*) AS total
                FROM proposals p
                JOIN situations s ON s.id=p.situation_id
                JOIN raw_items r ON r.id=s.raw_item_id
                WHERE p.proposed_at COLLATE UTC_TIMESTAMP <= ?
                  AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
                  AND r.known_at COLLATE UTC_TIMESTAMP <= ?
                  AND r.source_id IN ({pair}){filters}
                GROUP BY week ORDER BY week ASC;""",
            scope_params,
        )
        weekly_series = [
            {
                "week": str(r["week"]),
                "asks": int(r["asks"] or 0),
                "suggestions": int(r["suggestions"] or 0),
                "intended_actions": int(r["intended_actions"] or 0),
                "total": int(r["total"] or 0),
            }
            for r in cursor.fetchall()
        ]

        cursor.execute(
            """SELECT seq,kind,ref_id,payload_json,created_at FROM ledger
               WHERE kind IN ('drift_alarm','family_shift')
                 AND created_at COLLATE UTC_TIMESTAMP <= ?
               ORDER BY seq DESC LIMIT 20;""",
            (cutoff,),
        )
        alarms = [
            {
                "seq": int(r["seq"]),
                "kind": str(r["kind"]),
                "ref_id": str(r["ref_id"]),
                "payload": json.loads(r["payload_json"]) if r["payload_json"] else {},
                "created_at": str(r["created_at"]),
            }
            for r in cursor.fetchall()
        ]

        return {
            "proposals_total": total_props,
            "asks": asks,
            "suggestions": suggestions,
            "intended_actions": intended,
            "confirmed_effects": confirmed,
            "unconfirmed_effects": unconfirmed,
            "agreement": agreement,
            "weekly_series": weekly_series,
            "alarms": alarms,
            "scope": {
                "family": family,
                "class_key": class_key,
                "action": action,
                "as_of": cutoff,
                "sources": len(allowed_sources),
                "evaluated_pairs": len(evaluated),
            },
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
            ORDER BY created_at COLLATE UTC_TIMESTAMP DESC;
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


@router.post("/habits/{habit_id}/deny", status_code=202)
def deny_habit(habit_id: str) -> dict[str, Any]:
    """Accept an immutable request; only Examiner changes the habit."""
    conn = _get_db()
    try:
        command = enqueue_command(
            RoleAccess(conn, Role.API), DenyHabit(habit_id=habit_id), get_clock().now_iso()
        )
        return {"ok": True, "command": command}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Habit not found") from exc
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
            ORDER BY created_at COLLATE UTC_TIMESTAMP DESC;
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
            ORDER BY started_at COLLATE UTC_TIMESTAMP DESC;
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


@router.post("/exams/run", status_code=202)
def run_exam(body: RunExamBody) -> dict[str, Any]:
    """Queue the exact requested pair; never silently substitute another class."""
    conn = _get_db()
    try:
        command = enqueue_command(RoleAccess(conn, Role.API), body, get_clock().now_iso())
        return {"ok": True, "command": command}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Exact exam pair not found") from exc
    finally:
        conn.close()


@router.get("/commands/{command_id}")
def get_command(
    command_id: str, owner: Annotated[OwnerContext, Depends(require_owner)]
) -> dict[str, Any]:
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM admin_commands WHERE id=?", (command_id,)).fetchone()
        if row is None:
            from probation.api.routes.controls import control_status

            if conn.execute("SELECT id FROM command_requests WHERE id=?", (command_id,)).fetchone():
                return control_status(conn, command_id, owner)
            raise HTTPException(status_code=404, detail="Command not found")
        # Legacy admin_commands lack owner_id. This app supports one configured private owner,
        # so bind their status to that credential; absent/mismatched configuration fails closed.
        if (
            not settings.probation_gmail_owner_id
            or owner.owner_id != settings.probation_gmail_owner_id
        ):
            raise HTTPException(status_code=404, detail="Command not found")
        return {"command": command_record(row)}
    finally:
        conn.close()
