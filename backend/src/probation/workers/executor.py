"""Executor worker: Sole execution boundary holding write credentials and executing side-effects.

Authority: docs/CONTRACT.md section 3, section 8, and invariants I-2, I-10, I-20.
CRITICAL: Only the Executor performs side-effects and holds write credentials.
"""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from probation.core.actions import PARAMETER_ACTIONS, InvalidAction, parse_action
from probation.core.clock import Clock, format_timestamp, get_clock
from probation.core.enums import ActionStatus, GateDecision, LedgerKind
from probation.core.hashing import canonical_json
from probation.core.lifecycle import HOLD_MINUTES, ApprovalBinding, SourceGrant
from probation.core.types import Action, ExecResult
from probation.db.access import Role, RoleAccess
from probation.db.actions import persist_action
from probation.engine.licence import derive_licences
from probation.packs.base import ExecutorIO
from probation.packs.registry import registry
from probation.workers.drift import has_pending_drift

HOLD_MINUTES_DEFAULT: Final[int] = HOLD_MINUTES


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
        clock: Clock | None = None,
        *,
        grant_resolver: Callable[[ApprovalBinding], SourceGrant | None] | None = None,
        allowed_forward_recipients: tuple[str, ...] = (),
        worker_id: str = "executor",
        undo_days: int = 7,
    ) -> None:
        self.conn = conn
        self.world = world
        self.clock = clock or get_clock()
        self.role_access = RoleAccess(conn, Role.EXECUTOR)
        self.grant_resolver = grant_resolver
        self.allowed_forward_recipients = allowed_forward_recipients
        self.worker_id = worker_id
        self.undo_days = undo_days

        # Cached permission is never authority for the newly reachable dispatch path.
        if licence_checker is not None:
            self.licence_checker = licence_checker
        else:
            self.licence_checker = self._default_licence_checker

    def _default_licence_checker(self, class_key: str, action: str, as_of: str) -> int:
        """Re-derive from bounded evidence without examiner writes or cache authority."""
        try:
            if has_pending_drift(self.conn, class_key, action, as_of):
                return 0
            reader = self.role_access.conn
            view = derive_licences(reader, as_of, pair=(class_key, action)).get((class_key, action))
            return int(view.level) if view else 0
        except (sqlite3.Error, ValueError, TypeError):
            return 0

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
        *,
        binding: ApprovalBinding | None = None,
        approval_response_id: str | None = None,
    ) -> Action:
        """Create and record an action resulting from a gated proposal."""
        parsed = parse_action(action_type)
        catalog = registry.get_descriptor(pack).action_catalog()
        if parsed.is_noop or parsed.type not in {spec.type for spec in catalog}:
            raise InvalidAction("Action is not an executable member of this pack's catalog")
        if parsed.type in PARAMETER_ACTIONS and parsed.parameter is None:
            raise InvalidAction("Executable action requires a nonempty parameter")
        action_type = parsed.label
        gate_str = (
            gate_decision.value if isinstance(gate_decision, GateDecision) else str(gate_decision)
        )
        as_of_dt = _parse_ts(as_of)

        if gate_str == GateDecision.HOLD_THEN_EXECUTE.value:
            status = ActionStatus.HELD
            hold_until: str | None = format_timestamp(
                as_of_dt + timedelta(minutes=HOLD_MINUTES_DEFAULT)
            )
        else:
            status = ActionStatus.PENDING
            hold_until = None

        act_id = (
            f"act-{proposal_id}"
            if approval_response_id is None
            else f"act-approved-{approval_response_id}"
        )
        if binding is not None:
            if (
                binding.action != action_type
                or binding.pack != pack
                or not 1 <= level_required <= 3
            ):
                raise InvalidAction("Action binding does not match executable intent")
            if approval_response_id is not None:
                status, hold_until = ActionStatus.PENDING, None
            elif not recallable:
                status = ActionStatus.HELD
                hold_until = format_timestamp(as_of_dt + timedelta(minutes=HOLD_MINUTES_DEFAULT))
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

        if binding is not None:
            from probation.db.lifecycle_actions import ActionStore

            return ActionStore(self.role_access).create_if_absent(
                action,
                binding,
                "explicit_user" if approval_response_id else "autonomous",
                approval_response_id=approval_response_id,
            )
        return persist_action(self.role_access, action)

    def process_responses(self, as_of: str | None = None, limit: int = 32) -> int:
        """Consume immutable approved requests; completed consumption is not an effect."""
        from probation.workers.mail_responses import consume_responses

        return consume_responses(self, as_of or self.clock.now_iso(), limit)

    def process_queue(self, as_of: str | None = None) -> list[ExecResult]:
        """Poll and execute pending and expired held actions.

        Authority: docs/CONTRACT.md section 8:
        - Re-derives licence level at execution time.
        - If licence is lost during hold, action is marked CANCELLED and falls back to SUGGEST.
        - Calls pack execute() in SimWorld / Live.
        - Stores undo_json and marks action DONE.
        """
        if self.conn.in_transaction:
            raise ValueError(
                "Executor consumption requires committed intent and a clean transaction"
            )
        now_iso = as_of or self.clock.now_iso()
        cur = self.role_access.conn.cursor()

        cur.execute(
            """
            SELECT a.*, p.class_key
            FROM actions a
            LEFT JOIN proposals p ON a.proposal_id = p.id
            WHERE a.status IN ('PENDING', 'HELD')
              AND (a.hold_until IS NULL OR a.hold_until COLLATE UTC_TIMESTAMP <= ?)
            ORDER BY a.created_at COLLATE UTC_TIMESTAMP ASC LIMIT 32;
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
            if pack_name == "mail":
                from probation.workers.mail_execution import MailLifecycle

                if has_pending_drift(self.conn, str(row["class_key"]), act_type, now_iso):
                    authority = row["authority_kind"]
                    if authority != "explicit_user":
                        results.append(
                            ExecResult(
                                success=False, action_id=act_id, error="Drift review pending"
                            )
                        )
                        continue
                results.append(MailLifecycle(self).execute(act_id, now_iso))
                continue
            level_req = int(row["level_required"])
            recallable = bool(row["recallable"])
            params = json.loads(row["params_json"])
            class_key = str(row["class_key"] or f"{pack_name}|unknown")

            # 1. Re-check licence at execution time (CONTRACT section 8)
            if has_pending_drift(self.conn, class_key, act_type, now_iso):
                results.append(
                    ExecResult(success=False, action_id=act_id, error="Drift review pending")
                )
                continue

            current_licence = self.licence_checker(class_key, act_type, now_iso)
            if current_licence < level_req:
                # Licence dropped below requirement -> cancel action
                self.role_access.execute_write(
                    "actions",
                    "UPDATE actions SET status = ?, updated_at = ? WHERE id = ?;",
                    (ActionStatus.CANCELLED.value, now_iso, act_id),
                )
                self.role_access.append_ledger(
                    kind=LedgerKind.ACTION,
                    ref_id=act_id,
                    payload={
                        "action_id": act_id,
                        "type": act_type,
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
                if pack_name == "mail" and parse_action(act_type).type == "REPLY":
                    from probation.db.reply_payload import load_reply_params

                    action_obj = action_obj.model_copy(
                        update={
                            "params": load_reply_params(self.role_access, prop_id, as_of=now_iso)
                        }
                    )
                pack_obj = registry.get(pack_name)
                exec_res = pack_obj.execute(action_obj, self.world)
            except Exception as e:
                exec_res = ExecResult(success=False, action_id=act_id, error=str(e))

            if exec_res.success:
                undo_str = canonical_json(exec_res.undo_data) if exec_res.undo_data else None
                self.role_access.execute_write(
                    "actions",
                    """
                    UPDATE actions
                    SET status = ?, executed_at = ?, undo_json = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (ActionStatus.DONE.value, now_iso, undo_str, now_iso, act_id),
                )
                self.role_access.append_ledger(
                    kind=LedgerKind.ACTION,
                    ref_id=act_id,
                    payload={
                        "action_id": act_id,
                        "type": act_type,
                        "level_required": level_req,
                        "status": ActionStatus.DONE.value,
                        "executed_at": now_iso,
                    },
                    created_at=now_iso,
                )
            else:
                self.role_access.execute_write(
                    "actions",
                    "UPDATE actions SET status = ?, updated_at = ? WHERE id = ?;",
                    (ActionStatus.FAILED.value, now_iso, act_id),
                )

            self.conn.commit()
            results.append(exec_res)

        from probation.workers.mail_responses import consume_undo_effects

        results.extend(consume_undo_effects(self, now_iso))
        return results

    def process_undo(self, action_id: str, as_of: str | None = None) -> ExecResult:
        """Reverse an executed action and emit strong disagreement outcome for drift tracking.

        Authority: docs/CONTRACT.md section 8 and docs/ENGINE_SPEC.md section 10.
        """
        if self.conn.in_transaction:
            raise ValueError("Executor undo requires committed intent and a clean transaction")
        now_iso = as_of or self.clock.now_iso()
        cur = self.role_access.conn.cursor()

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

        if row["pack"] == "mail":
            from probation.workers.mail_execution import MailLifecycle

            return MailLifecycle(self).undo(action_id, now_iso)

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
        self.role_access.execute_write(
            "actions",
            "UPDATE actions SET status = ?, updated_at = ? WHERE id = ?;",
            (ActionStatus.UNDONE.value, now_iso, action_id),
        )

        # 2. Append action event to ledger
        self.role_access.append_ledger(
            kind=LedgerKind.ACTION,
            ref_id=action_id,
            payload={
                "action_id": action_id,
                "type": act_type,
                "level_required": int(row["level_required"]),
                "status": ActionStatus.UNDONE.value,
                "undone_at": now_iso,
            },
            created_at=now_iso,
        )

        # 3. Record strong disagreement outcome in outcomes table (ENGINE_SPEC.md section 10)
        seq = self.role_access.append_ledger(
            kind=LedgerKind.OUTCOME,
            ref_id=f"undo-{action_id}",
            payload={
                "situation_id": sit_id,
                "observed_action": "UNDO",
                "strength": "STRONG",
                "source": "undo",
                "known_at": now_iso,
                "action_id": action_id,
                "undone_at": now_iso,
            },
            created_at=now_iso,
        )

        self.role_access.store_undo_outcome(action_id, now_iso, seq)

        # Examiner consumes the immutable outcome ledger event before later execution.

        self.conn.commit()
        return undo_res
