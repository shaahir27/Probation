"""One durable operation journal per action: uncertainty never becomes a resend."""

from typing import Any, Literal

from probation.core.clock import timestamp_key
from probation.core.hashing import canonical_json, det_id
from probation.core.lifecycle import AttemptClaim, AttemptRecord, LifecycleDenied, StaleClaim
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import lease_end, require_role, unpack, write


class AttemptStore:
    def __init__(self, access: RoleAccess) -> None:
        self.access = access

    def get(self, action_id: str, operation: str) -> AttemptRecord | None:
        row = self.access.conn.execute(
            "SELECT * FROM execution_attempts WHERE action_id=? AND operation=?",
            (action_id, operation),
        ).fetchone()
        if row is None:
            return None
        return AttemptRecord(
            attempt_id=row["id"],
            action_id=action_id,
            operation=row["operation"],
            state=row["state"],
            binding_hash=row["binding_hash"],
            before_state=unpack(row["before_json"]),
            result=unpack(row["result_json"]),
            safe_code=row["safe_code"],
        )

    def has_unresolved(self, action_id: str) -> bool:
        return (
            self.access.conn.execute(
                "SELECT 1 FROM execution_attempts WHERE action_id=? AND state IN('prepared','dispatched','unknown')",
                (action_id,),
            ).fetchone()
            is not None
        )

    def prepare(
        self,
        action_id: str,
        operation: Literal["execute", "undo"],
        binding_hash: str,
        before_state: dict[str, Any],
        now: str,
        owner: str,
        lease_seconds: int = 30,
    ) -> AttemptClaim | None:
        require_role(self.access, "executor")
        if not owner:
            raise LifecycleDenied("missing_claim_owner")
        if self.access._connection.in_transaction:
            raise LifecycleDenied("dispatch_marker_requires_clean_transaction")
        attempt_id = det_id("operation-v1", action_id, operation)
        with self.access.transaction():
            action = self.access.conn.execute(
                "SELECT * FROM actions WHERE id=? AND binding_hash=?", (action_id, binding_hash)
            ).fetchone()
            if action is None:
                raise LifecycleDenied("attempt_action_binding_mismatch")
            row = self.access.conn.execute(
                "SELECT * FROM execution_attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if row is not None:
                if timestamp_key(now) < timestamp_key(row["updated_at"]):
                    raise StaleClaim("attempt_clock_reversed")
                if row["state"] in {"confirmed", "failed"} or timestamp_key(
                    row["lease_until"]
                ) > timestamp_key(now):
                    return None
                fence = int(row["fence"]) + 1
                stage = row["state"]
                before = unpack(row["before_json"])
                write(
                    self.access,
                    "execution_attempts",
                    "UPDATE execution_attempts SET claim_owner=?,fence=?,lease_until=?,updated_at=? WHERE id=?",
                    (owner, fence, lease_end(now, lease_seconds), now, attempt_id),
                )
            else:
                if (operation == "execute" and action["status"] not in {"PENDING", "HELD"}) or (
                    operation == "undo" and action["status"] != "DONE"
                ):
                    raise LifecycleDenied("invalid_attempt_action_state")
                fence = 1
                stage = "prepared"
                before = before_state
                write(
                    self.access,
                    "execution_attempts",
                    """INSERT INTO execution_attempts(id,action_id,operation,binding_hash,state,claim_owner,fence,lease_until,before_json,created_at,updated_at) VALUES (?,?,?,?,'prepared',?,?,?,?,?,?)""",
                    (
                        attempt_id,
                        action_id,
                        operation,
                        binding_hash,
                        owner,
                        fence,
                        lease_end(now, lease_seconds),
                        canonical_json(before),
                        now,
                        now,
                    ),
                )
        return AttemptClaim(
            attempt_id=attempt_id,
            action_id=action_id,
            operation=operation,
            owner=owner,
            fence=fence,
            mode="execute" if stage == "prepared" else "reconcile",
            stage=stage,
            before_state=before,
            binding_hash=binding_hash,
        )

    def _owned(self, claim: AttemptClaim, now: str) -> Any:
        require_role(self.access, "executor")
        row = self.access.conn.execute(
            """SELECT * FROM execution_attempts WHERE id=? AND action_id=? AND operation=? AND binding_hash=? AND claim_owner=? AND fence=? AND lease_until COLLATE UTC_TIMESTAMP > ?""",
            (
                claim.attempt_id,
                claim.action_id,
                claim.operation,
                claim.binding_hash,
                claim.owner,
                claim.fence,
                now,
            ),
        ).fetchone()
        if row is None:
            raise StaleClaim("attempt_claim_expired")
        if timestamp_key(now) < timestamp_key(row["updated_at"]):
            raise StaleClaim("attempt_clock_reversed")
        return row

    def mark_dispatched(self, claim: AttemptClaim, now: str) -> None:
        if self.access._connection.in_transaction:
            raise LifecycleDenied("dispatch_marker_requires_clean_transaction")
        with self.access.transaction():
            row = self._owned(claim, now)
            if claim.mode != "execute" or row["state"] != "prepared":
                raise LifecycleDenied("reconciliation_cannot_dispatch")
            write(
                self.access,
                "execution_attempts",
                "UPDATE execution_attempts SET state='dispatched',updated_at=? WHERE id=?",
                (now, claim.attempt_id),
            )

    def finish(
        self,
        claim: AttemptClaim,
        now: str,
        result_state: Literal["confirmed", "failed"],
        result: dict[str, Any],
        safe_code: str | None = None,
        non_effect_proof: dict[str, Any] | None = None,
    ) -> None:
        with self.access.transaction():
            row = self._owned(claim, now)
            if row["state"] not in {"prepared", "dispatched", "unknown"}:
                raise StaleClaim("attempt_already_completed")
            if (
                result_state == "failed"
                and row["state"] != "prepared"
                and not (non_effect_proof and non_effect_proof.get("confirmed_no_effect") is True)
            ):
                raise LifecycleDenied("definitive_non_effect_required")
            if result_state == "confirmed" and row["state"] == "prepared":
                raise LifecycleDenied("undispatched_effect_cannot_confirm")
            write(
                self.access,
                "execution_attempts",
                "UPDATE execution_attempts SET state=?,result_json=?,safe_code=?,updated_at=? WHERE id=?",
                (result_state, canonical_json(result), safe_code, now, claim.attempt_id),
            )

    def mark_unknown(self, claim: AttemptClaim, now: str, code: str) -> None:
        with self.access.transaction():
            row = self._owned(claim, now)
            if row["state"] not in {"dispatched", "unknown"}:
                raise LifecycleDenied("unknown_requires_dispatch")
            write(
                self.access,
                "execution_attempts",
                "UPDATE execution_attempts SET state='unknown',safe_code=?,updated_at=? WHERE id=?",
                (code, now, claim.attempt_id),
            )

    def cancel_prepared(self, claim: AttemptClaim, now: str, reason: str) -> None:
        with self.access.transaction():
            row = self._owned(claim, now)
            if row["state"] != "prepared":
                raise LifecycleDenied("dispatched_operation_cannot_cancel")
            write(
                self.access,
                "execution_attempts",
                "UPDATE execution_attempts SET state='failed',result_json=?,safe_code=?,updated_at=? WHERE id=?",
                (
                    canonical_json({"confirmed_no_effect": True, "cancelled": True}),
                    reason,
                    now,
                    claim.attempt_id,
                ),
            )
