"""Executor worker: Sole execution boundary holding write credentials and executing side-effects.

Authority: docs/CONTRACT.md section 3, section 8, and invariants I-2, I-10, I-20.
CRITICAL: Only the Executor performs side-effects and holds write credentials.
"""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from probation.core.enums import ActionStatus, GateDecision, LedgerKind
from probation.core.hashing import canonical_json
from probation.core.types import Action, ExecResult
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger
from probation.engine.drift import CUSUMTracker
from probation.packs.base import ExecutorIO
from probation.packs.registry import registry

HOLD_MINUTES_DEFAULT: Final[int] = 10


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp to UTC datetime."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class Executor:
    """The sole process authorized to perform external side-effects and undos."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        world: ExecutorIO | None = None,
        licence_checker: Callable[[str, str, str], int] | None = None,
    ) -> None:
        self.conn = conn
        self.world = world
        self.role_access = RoleAccess(conn, Role.EXECUTOR)

        # Default licence checker reads from licence_cache
        if licence_checker is not None:
            self.licence_checker = licence_checker
        else:
            self.licence_checker = self._default_licence_checker

    def _default_licence_checker(self, class_key: str, action: str, as_of: str) -> int:
        """Read derived licence level from licence_cache."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT level FROM licence_cache WHERE class_key = ? AND action = ?;",
            (class_key, action),
        )
        row = cur.fetchone()
        return int(row["level"]) if row else 0

    def create_action(
        self,
        proposal_id: str,
        pack: str,
        action_type: str,
        params: dict[str, Any],
        level_required: int,
        recallable: bool,
        gate_decision: GateDecision | str,
        as_of: str,
    ) -> Action:
        """Create and record an action resulting from a gated proposal."""
        gate_str = (
            gate_decision.value if isinstance(gate_decision, GateDecision) else str(gate_decision)
        )
        as_of_dt = _parse_ts(as_of)

        if gate_str == GateDecision.HOLD_THEN_EXECUTE.value:
            status = ActionStatus.HELD
            hold_until: str | None = (as_of_dt + timedelta(minutes=HOLD_MINUTES_DEFAULT)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        else:
            status = ActionStatus.PENDING
            hold_until = None

        act_id = f"act-{proposal_id}"
        action = Action(
            id=act_id,
            proposal_id=proposal_id,
            pack=pack,
            type=action_type,
            params=params,
            level_required=level_required,
            recallable=recallable,
            status=status,
            hold_until=hold_until,
            undo=None,
            created_at=as_of,
            updated_at=as_of,
        )

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO actions
            (id, proposal_id, pack, type, params_json, level_required, recallable, status, hold_until, undo_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?);
            """,
            (
                action.id,
                action.proposal_id,
                action.pack,
                action.type,
                canonical_json(action.params),
                action.level_required,
                1 if action.recallable else 0,
                action.status.value,
                action.hold_until,
                action.created_at,
                action.updated_at,
            ),
        )

        append_ledger(
            self.conn,
            kind=LedgerKind.ACTION,
            ref_id=action.id,
            payload={
                "action_id": action.id,
                "proposal_id": action.proposal_id,
                "pack": action.pack,
                "type": action.type,
                "status": action.status.value,
                "hold_until": action.hold_until,
                "created_at": action.created_at,
            },
            created_at=as_of,
        )
        self.conn.commit()
        return action

    def process_queue(self, as_of: str | None = None) -> list[ExecResult]:
        """Poll and execute pending and expired held actions.

        Authority: docs/CONTRACT.md section 8:
        - Re-derives licence level at execution time.
        - If licence is lost during hold, action is marked CANCELLED and falls back to SUGGEST.
        - Calls pack execute() in SimWorld / Live.
        - Stores undo_json and marks action DONE.
        """
        now_iso = as_of or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self.conn.cursor()

        cur.execute(
            """
            SELECT a.*, p.class_key
            FROM actions a
            LEFT JOIN proposals p ON a.proposal_id = p.id
            WHERE a.status IN ('PENDING', 'HELD')
              AND (a.hold_until IS NULL OR a.hold_until <= ?)
            ORDER BY a.created_at ASC;
            """,
            (now_iso,),
        )
        action_rows = cur.fetchall()
        results: list[ExecResult] = []

        for row in action_rows:
            act_id = str(row["id"])
            prop_id = str(row["proposal_id"])
            pack_name = str(row["pack"])
            act_type = str(row["type"])
            level_req = int(row["level_required"])
            recallable = bool(row["recallable"])
            params = json.loads(row["params_json"])
            class_key = str(row["class_key"] or f"{pack_name}|unknown")

            # 1. Re-check licence at execution time (CONTRACT section 8)
            current_licence = self.licence_checker(class_key, act_type, now_iso)
            if current_licence < level_req:
                # Licence dropped below requirement -> cancel action and emit SUGGEST proposal
                cur.execute(
                    "UPDATE actions SET status = ?, updated_at = ? WHERE id = ?;",
                    (ActionStatus.CANCELLED.value, now_iso, act_id),
                )
                cur.execute(
                    "UPDATE proposals SET gate = ?, licence_level = ? WHERE id = ?;",
                    (GateDecision.SUGGEST.value, current_licence, prop_id),
                )
                append_ledger(
                    self.conn,
                    kind=LedgerKind.ACTION,
                    ref_id=act_id,
                    payload={
                        "action_id": act_id,
                        "status": ActionStatus.CANCELLED.value,
                        "reason": "licence_lost",
                        "current_licence": current_licence,
                        "level_required": level_req,
                    },
                    created_at=now_iso,
                )
                self.conn.commit()
                continue

            # 2. Execute via pack
            action_obj = Action(
                id=act_id,
                proposal_id=prop_id,
                pack=pack_name,
                type=act_type,
                params=params,
                level_required=level_req,
                recallable=recallable,
                status=ActionStatus(str(row["status"])),
                hold_until=row["hold_until"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

            if self.world is None:
                continue

            try:
                pack_obj = registry.get(pack_name)
                exec_res = pack_obj.execute(action_obj, self.world)
            except Exception as e:
                exec_res = ExecResult(success=False, action_id=act_id, error=str(e))

            if exec_res.success:
                undo_str = canonical_json(exec_res.undo_data) if exec_res.undo_data else None
                cur.execute(
                    """
                    UPDATE actions
                    SET status = ?, executed_at = ?, undo_json = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (ActionStatus.DONE.value, now_iso, undo_str, now_iso, act_id),
                )
                append_ledger(
                    self.conn,
                    kind=LedgerKind.ACTION,
                    ref_id=act_id,
                    payload={
                        "action_id": act_id,
                        "status": ActionStatus.DONE.value,
                        "executed_at": now_iso,
                    },
                    created_at=now_iso,
                )
            else:
                cur.execute(
                    "UPDATE actions SET status = ?, updated_at = ? WHERE id = ?;",
                    (ActionStatus.FAILED.value, now_iso, act_id),
                )

            self.conn.commit()
            results.append(exec_res)

        return results

    def process_undo(self, action_id: str, as_of: str | None = None) -> ExecResult:
        """Reverse an executed action and emit strong disagreement outcome for drift tracking.

        Authority: docs/CONTRACT.md section 8 and docs/ENGINE_SPEC.md section 10.
        """
        now_iso = as_of or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = self.conn.cursor()

        cur.execute(
            """
            SELECT a.*, p.class_key, p.situation_id
            FROM actions a
            LEFT JOIN proposals p ON a.proposal_id = p.id
            WHERE a.id = ?;
            """,
            (action_id,),
        )
        row = cur.fetchone()

        if row is None:
            return ExecResult(
                success=False, action_id=action_id, error=f"Action '{action_id}' not found."
            )

        if row["status"] != ActionStatus.DONE.value:
            return ExecResult(
                success=False,
                action_id=action_id,
                error=f"Action '{action_id}' has status '{row['status']}', cannot undo.",
            )

        if not row["recallable"]:
            return ExecResult(
                success=False,
                action_id=action_id,
                error=f"Action '{action_id}' is not recallable.",
            )

        pack_name = str(row["pack"])
        act_type = str(row["type"])
        params = json.loads(row["params_json"])
        undo_data = json.loads(row["undo_json"]) if row["undo_json"] else None
        class_key = str(row["class_key"] or f"{pack_name}|unknown")
        sit_id = str(row["situation_id"] or f"sit-{row['proposal_id']}")

        action_obj = Action(
            id=action_id,
            proposal_id=str(row["proposal_id"]),
            pack=pack_name,
            type=act_type,
            params=params,
            level_required=int(row["level_required"]),
            recallable=bool(row["recallable"]),
            status=ActionStatus.DONE,
            undo=undo_data,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

        if self.world is None:
            return ExecResult(
                success=False,
                action_id=action_id,
                error="Executor has no world attached for undo.",
            )

        try:
            pack_obj = registry.get(pack_name)
            undo_res = pack_obj.undo(action_obj, self.world)
        except Exception as e:
            return ExecResult(success=False, action_id=action_id, error=str(e))

        if not undo_res.success:
            return undo_res

        # 1. Update action status to UNDONE
        cur.execute(
            "UPDATE actions SET status = ?, updated_at = ? WHERE id = ?;",
            (ActionStatus.UNDONE.value, now_iso, action_id),
        )

        # 2. Append action event to ledger
        append_ledger(
            self.conn,
            kind=LedgerKind.ACTION,
            ref_id=action_id,
            payload={
                "action_id": action_id,
                "status": ActionStatus.UNDONE.value,
                "undone_at": now_iso,
            },
            created_at=now_iso,
        )

        # 3. Record strong disagreement outcome in outcomes table (ENGINE_SPEC.md section 10)
        seq = append_ledger(
            self.conn,
            kind=LedgerKind.OUTCOME,
            ref_id=f"undo-{action_id}",
            payload={
                "situation_id": sit_id,
                "observed_action": "UNDO",
                "strength": "STRONG",
                "source": "undo",
                "action_id": action_id,
                "undone_at": now_iso,
            },
            created_at=now_iso,
        )

        cur.execute(
            """
            INSERT OR REPLACE INTO outcomes
            (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
            VALUES (?, 'UNDO', 'STRONG', 'undo', ?, ?, '{}', ?);
            """,
            (sit_id, now_iso, now_iso, seq),
        )

        # 4. Update CUSUM drift tracker for (class_key, action)
        cur.execute(
            "SELECT * FROM drift_state WHERE class_key = ? AND action = ?;",
            (class_key, act_type),
        )
        d_row = cur.fetchone()
        if d_row is not None:
            tracker = CUSUMTracker(
                baseline_err=float(d_row["baseline_err"]),
                initial_s=float(d_row["cusum"]),
                last_alarm_at=d_row["last_alarm_at"],
            )
        else:
            tracker = CUSUMTracker()

        alarm = tracker.update(is_error=True, is_undo=True, timestamp=now_iso)

        cur.execute(
            """
            INSERT OR REPLACE INTO drift_state
            (class_key, action, cusum, baseline_err, last_alarm_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (class_key, act_type, tracker.s, tracker.baseline_err, tracker.last_alarm_at),
        )

        if alarm:
            append_ledger(
                self.conn,
                kind=LedgerKind.DRIFT_ALARM,
                ref_id=f"alarm-{class_key}-{act_type}",
                payload={
                    "class_key": class_key,
                    "action": act_type,
                    "alarm_at": now_iso,
                    "reason": "undo_cusum_alarm",
                },
                created_at=now_iso,
            )

        self.conn.commit()
        return undo_res
