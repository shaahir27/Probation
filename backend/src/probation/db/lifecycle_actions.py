"""Executor-only action creation and validated state transitions."""

from datetime import timedelta
from typing import Any, Literal

from probation.core.clock import parse_timestamp, timestamp_key
from probation.core.enums import ActionStatus
from probation.core.hashing import canonical_json
from probation.core.lifecycle import (
    HOLD_MINUTES,
    ActionAuthority,
    ApprovalBinding,
    AttemptClaim,
    LifecycleConflict,
    LifecycleDenied,
    binding_hash,
)
from probation.core.types import Action
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import require_role, unpack, write


class ActionStore:
    def __init__(self, access: RoleAccess) -> None:
        self.access = access

    def get(self, action_id: str) -> Action | None:
        row = self.access.conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            return None
        return Action(
            id=row["id"],
            proposal_id=row["proposal_id"],
            pack=row["pack"],
            type=row["type"],
            params=unpack(row["params_json"]),
            level_required=row["level_required"],
            recallable=bool(row["recallable"]),
            status=row["status"],
            hold_until=row["hold_until"],
            undo=unpack(row["undo_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            executed_at=row["executed_at"],
        )

    def get_binding(self, action_id: str) -> ApprovalBinding:
        row = self.access.conn.execute(
            "SELECT binding_json FROM actions WHERE id=?", (action_id,)
        ).fetchone()
        if row is None or row["binding_json"] is None:
            raise LifecycleDenied("missing_action_binding")
        return ApprovalBinding.model_validate_json(row["binding_json"])

    def get_authority(self, action_id: str) -> ActionAuthority:
        row = self.access.conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None or row["authority_kind"] is None or row["binding_hash"] is None:
            raise LifecycleDenied("legacy_action_unbound")
        return ActionAuthority(
            kind=row["authority_kind"],
            approval_response_id=row["approval_response_id"],
            binding_hash=row["binding_hash"],
            undo_deadline=row["undo_deadline"],
        )

    def validate_autonomous(self, action: Action) -> None:
        """A caller cannot promote a saved audit/suggestion into an executing gate."""
        row = self.access.conn.execute(
            "SELECT gate,audit_holdout,licence_level,cap,action FROM proposals WHERE id=?",
            (action.proposal_id,),
        ).fetchone()
        if (
            row is None
            or row["audit_holdout"]
            or row["gate"] not in {"EXECUTE_UNDO", "HOLD_THEN_EXECUTE", "EXECUTE_SILENT"}
        ):
            raise LifecycleDenied("proposal_not_executable")
        expected = 3 if row["gate"] == "EXECUTE_SILENT" else 2
        if (
            row["action"] != action.type
            or action.level_required != expected
            or min(row["licence_level"], row["cap"]) < expected
        ):
            raise LifecycleDenied("proposal_execution_level_mismatch")
        from probation.engine.caps import is_recallable

        if action.recallable != is_recallable(action.type):
            raise LifecycleDenied("action_recallability_mismatch")
        if row["gate"] == "HOLD_THEN_EXECUTE":
            deadline = parse_timestamp(action.created_at) + timedelta(minutes=HOLD_MINUTES)
            if (
                action.recallable
                or action.status != ActionStatus.HELD
                or not action.hold_until
                or parse_timestamp(action.hold_until) != deadline
            ):
                raise LifecycleDenied("autonomous_hold_required")
        elif (
            not action.recallable
            or action.status != ActionStatus.PENDING
            or action.hold_until is not None
        ):
            raise LifecycleDenied("autonomous_gate_binding_mismatch")

    def create_if_absent(
        self,
        action: Action,
        binding: ApprovalBinding,
        authority_kind: Literal["autonomous", "explicit_user"],
        approval_response_id: str | None = None,
        undo_deadline: str | None = None,
    ) -> Action:
        require_role(self.access, "executor")
        hashed = binding_hash(binding)
        with self.access.transaction():
            old = self.get(action.id)
            if old is not None:
                old_auth = self.get_authority(action.id)
                identity = ("proposal_id", "pack", "type", "params", "level_required", "recallable")
                if (
                    any(getattr(old, k) != getattr(action, k) for k in identity)
                    or old_auth.kind != authority_kind
                    or old_auth.approval_response_id != approval_response_id
                    or old_auth.binding_hash != hashed
                ):
                    raise LifecycleConflict("action_identity_conflict")
                return old
            if (
                action.type != binding.action
                or action.pack != binding.pack
                or action.params != binding.params
                or action.type in {"LEAVE", "ABSTAIN"}
            ):
                raise LifecycleDenied("action_binding_mismatch")
            if action.status not in {ActionStatus.PENDING, ActionStatus.HELD}:
                raise LifecycleDenied("invalid_initial_action_status")
            proposal = self.access.conn.execute(
                "SELECT p.action,p.proposed_at,s.pack FROM proposals p JOIN situations s ON s.id=p.situation_id WHERE p.id=?",
                (action.proposal_id,),
            ).fetchone()
            if (
                proposal is None
                or action.pack != proposal["pack"]
                or timestamp_key(action.created_at) < timestamp_key(proposal["proposed_at"])
            ):
                raise LifecycleDenied("action_proposal_mismatch")
            if authority_kind == "autonomous" and (
                action.type != proposal["action"] or action.type == "FORWARD"
            ):
                raise LifecycleDenied("autonomous_action_mismatch")
            if authority_kind == "explicit_user":
                row = self.access.conn.execute(
                    "SELECT * FROM user_responses WHERE id=? AND proposal_id=? AND response IN('accept','edit') AND schema_version=2",
                    (approval_response_id, action.proposal_id),
                ).fetchone()
                if (
                    row is None
                    or row["reviewed_payload_hash"] != hashed
                    or action.status == ActionStatus.HELD
                ):
                    raise LifecycleDenied("invalid_explicit_authority")
            elif approval_response_id is not None:
                raise LifecycleDenied("unexpected_approval")
            else:
                self.validate_autonomous(action)
            unresolved = self.access.conn.execute(
                """SELECT id FROM actions WHERE binding_json IS NOT NULL
                AND json_extract(binding_json,'$.connection_id')=? AND json_extract(binding_json,'$.account_id')=?
                AND json_extract(binding_json,'$.resource_id')=? AND status IN('PENDING','HELD') LIMIT 1""",
                (binding.connection_id, binding.account_id, binding.resource_id),
            ).fetchone()
            if unresolved is not None:
                raise LifecycleConflict("resource_action_already_pending")
            write(
                self.access,
                "actions",
                """INSERT INTO actions(id,proposal_id,pack,type,params_json,level_required,recallable,status,hold_until,undo_json,created_at,updated_at,executed_at,authority_kind,approval_response_id,binding_json,binding_hash,undo_deadline) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    action.id,
                    action.proposal_id,
                    action.pack,
                    action.type,
                    canonical_json(action.params),
                    action.level_required,
                    int(action.recallable),
                    action.status,
                    action.hold_until,
                    canonical_json(action.undo) if action.undo is not None else None,
                    action.created_at,
                    action.updated_at,
                    action.executed_at,
                    authority_kind,
                    approval_response_id,
                    canonical_json(binding.model_dump()),
                    hashed,
                    undo_deadline,
                ),
            )
        return action

    def transition(
        self,
        action_id: str,
        expected_status: ActionStatus | set[ActionStatus],
        new_status: ActionStatus,
        now: str,
        *,
        executed_at: str | None = None,
        undo_data: dict[str, Any] | None = None,
        undo_deadline: str | None = None,
        claim: AttemptClaim | None = None,
    ) -> Action:
        require_role(self.access, "executor")
        expected = expected_status if isinstance(expected_status, set) else {expected_status}
        with self.access.transaction():
            action = self.get(action_id)
            if action is None or action.status not in expected:
                raise LifecycleConflict("action_state_conflict")
            if timestamp_key(now) < timestamp_key(action.updated_at) or (
                executed_at is not None and timestamp_key(executed_at) > timestamp_key(now)
            ):
                raise LifecycleDenied("inconsistent_action_clock")
            if (
                new_status == ActionStatus.HELD
                and self.get_authority(action_id).kind == "explicit_user"
            ):
                raise LifecycleDenied("explicit_action_cannot_hold")
            allowed = {
                ActionStatus.PENDING: {
                    ActionStatus.DONE,
                    ActionStatus.FAILED,
                    ActionStatus.CANCELLED,
                    ActionStatus.HELD,
                },
                ActionStatus.HELD: {ActionStatus.DONE, ActionStatus.FAILED, ActionStatus.CANCELLED},
                ActionStatus.DONE: {ActionStatus.UNDONE},
            }
            if new_status not in allowed.get(action.status, set()):
                raise LifecycleDenied("invalid_action_transition")
            if new_status in {ActionStatus.DONE, ActionStatus.UNDONE, ActionStatus.FAILED}:
                operation = "undo" if new_status == ActionStatus.UNDONE else "execute"
                attempt = self.access.conn.execute(
                    "SELECT * FROM execution_attempts WHERE action_id=? AND operation=?",
                    (action_id, operation),
                ).fetchone()
                needed = "failed" if new_status == ActionStatus.FAILED else "confirmed"
                if (
                    attempt is None
                    or attempt["state"] != needed
                    or claim is None
                    or claim.action_id != action_id
                    or claim.operation != operation
                    or claim.fence != attempt["fence"]
                    or claim.owner != attempt["claim_owner"]
                ):
                    raise LifecycleDenied("unconfirmed_action_transition")
            if new_status == ActionStatus.CANCELLED:
                attempt = self.access.conn.execute(
                    "SELECT state FROM execution_attempts WHERE action_id=? AND operation='execute'",
                    (action_id,),
                ).fetchone()
                if attempt is not None and attempt["state"] in {
                    "dispatched",
                    "unknown",
                    "confirmed",
                }:
                    raise LifecycleDenied("effect_may_have_occurred")
            write(
                self.access,
                "actions",
                """UPDATE actions SET status=?,updated_at=?,executed_at=COALESCE(?,executed_at),undo_json=COALESCE(?,undo_json),undo_deadline=COALESCE(?,undo_deadline) WHERE id=?""",
                (
                    new_status,
                    now,
                    executed_at,
                    canonical_json(undo_data) if undo_data is not None else None,
                    undo_deadline,
                    action_id,
                ),
            )
            updated = self.get(action_id)
            assert updated is not None
            return updated
