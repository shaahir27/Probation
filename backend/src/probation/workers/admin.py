"""Examiner administrative command drain; no API write authority is delegated."""

import sqlite3
from dataclasses import asdict
from typing import Any

from probation.core.clock import Clock, get_clock
from probation.core.hashing import canonical_json
from probation.db.access import Role, RoleAccess
from probation.db.commands import COMMAND_ADAPTER, DenyHabit
from probation.workers.examiner import run_examiner_job


def process_admin_commands(
    conn: sqlite3.Connection, *, clock: Clock | None = None, limit: int = 32
) -> list[str]:
    if conn.in_transaction:
        raise ValueError("Command drain requires a clean Examiner connection")
    if not 1 <= limit <= 256:
        raise ValueError("Invalid Examiner command batch size")
    clk = clock or get_clock()
    access = RoleAccess(conn, Role.EXAMINER)
    rows = access.conn.execute(
        """SELECT * FROM admin_commands WHERE status='PENDING'
        AND requested_at COLLATE UTC_TIMESTAMP <= ? ORDER BY requested_at COLLATE UTC_TIMESTAMP,id
        LIMIT ?""",
        (clk.now_iso(), limit),
    ).fetchall()
    completed: list[str] = []
    for row in rows:
        try:
            command = COMMAND_ADAPTER.validate_json(row["payload_json"])
            result: dict[str, Any]
            if isinstance(command, DenyHabit):
                with access.transaction():
                    current = access.conn.execute(
                        "SELECT status FROM admin_commands WHERE id=?", (row["id"],)
                    ).fetchone()
                    if current is None or current["status"] != "PENDING":
                        continue
                    updated = access.execute_write(
                        "habits",
                        "UPDATE habits SET status='denied' WHERE id=?",
                        (command.habit_id,),
                    )
                    if updated.rowcount != 1:
                        raise LookupError("Habit unavailable")
                    _finish(
                        access,
                        row["id"],
                        "SUCCEEDED",
                        {"habit_id": command.habit_id, "denied": True},
                        clk.now_iso(),
                    )
            else:
                # Exam identity includes frozen request time and explicit attempt. A crash
                # after exam persistence is recovered by its stable existing result.
                exam = run_examiner_job(
                    conn,
                    class_key=command.class_key,
                    action=command.action,
                    level=command.level,
                    attempt_ordinal=command.attempt_ordinal,
                    as_of=row["requested_at"],
                    clock=clk,
                )
                result = asdict(exam)
                with access.transaction():
                    _finish(access, row["id"], "SUCCEEDED", result, clk.now_iso())
        except Exception:
            # No exception text/private provider body enters the response record.
            with access.transaction():
                _finish(access, row["id"], "FAILED", {"error": "COMMAND_FAILED"}, clk.now_iso())
        completed.append(str(row["id"]))
    return completed


def _finish(
    access: RoleAccess, command_id: str, status: str, result: dict[str, Any], timestamp: str
) -> None:
    access.execute_write(
        "admin_commands",
        """UPDATE admin_commands SET status=?,result_json=?,updated_at=?
        WHERE id=? AND status='PENDING'""",
        (status, canonical_json(result), timestamp, command_id),
    )
