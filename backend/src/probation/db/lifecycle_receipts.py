"""Fenced, per-consumer durable consumption receipts, separate from effects."""

from typing import Any, Literal

from probation.core.hashing import canonical_json, det_id
from probation.core.lifecycle import ReceiptClaim, ReceiptRecord, StaleClaim
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import lease_end, require_role, unpack, write


class ReceiptStore:
    def __init__(self, access: RoleAccess) -> None:
        self.access = access

    def _get(
        self, request_id: str, kind: Literal["response", "command"], consumer: str
    ) -> ReceiptRecord | None:
        column = "response_id" if kind == "response" else "command_id"
        row = self.access.conn.execute(
            f"SELECT * FROM command_receipts WHERE {column}=? AND consumer=?",
            (request_id, consumer),
        ).fetchone()
        if row is None:
            return None
        return ReceiptRecord(
            receipt_id=row["id"],
            request_id=request_id,
            request_kind=kind,
            consumer=consumer,
            state=row["state"],
            result=unpack(row["result_json"]),
            safe_code=row["safe_code"],
        )

    def get_response(self, response_id: str, consumer: str) -> ReceiptRecord | None:
        return self._get(response_id, "response", consumer)

    def get_command(self, command_id: str) -> ReceiptRecord | None:
        return self._get(command_id, "command", "examiner")

    def claim_response(
        self, response_id: str, *, now: str, owner: str, lease_seconds: int = 30
    ) -> ReceiptClaim | None:
        require_role(self.access, "resolver", "executor")
        return self._claim(response_id, "response", now, owner, lease_seconds)

    def claim_command(
        self, command_id: str, *, now: str, owner: str, lease_seconds: int = 30
    ) -> ReceiptClaim | None:
        require_role(self.access, "examiner")
        return self._claim(command_id, "command", now, owner, lease_seconds)

    def _claim(
        self,
        request_id: str,
        kind: Literal["response", "command"],
        now: str,
        owner: str,
        seconds: int,
    ) -> ReceiptClaim | None:
        consumer = self.access.role.value
        column = "response_id" if kind == "response" else "command_id"
        table = "user_responses" if kind == "response" else "command_requests"
        receipt_id = det_id("receipt-v1", kind, request_id, consumer)
        with self.access.transaction():
            request = self.access.conn.execute(
                f"SELECT * FROM {table} WHERE id=?", (request_id,)
            ).fetchone()
            if request is None:
                raise StaleClaim("missing_request")
            if kind == "response":
                allowed = (
                    {"accept", "reject", "edit"}
                    if consumer == "resolver"
                    else {"accept", "edit", "undo"}
                )
                if request["schema_version"] != 2 or request["response"] not in allowed:
                    raise StaleClaim("request_consumer_mismatch")
            time_column = "responded_at" if kind == "response" else "created_at"
            from probation.core.clock import timestamp_key

            if timestamp_key(request[time_column]) > timestamp_key(now):
                raise StaleClaim("future_request")
            row = self.access.conn.execute(
                "SELECT * FROM command_receipts WHERE id=?", (receipt_id,)
            ).fetchone()
            if row is not None:
                if timestamp_key(now) < timestamp_key(row["updated_at"]):
                    raise StaleClaim("receipt_clock_reversed")
                if row["state"] in {"succeeded", "failed"} or (
                    row["lease_until"] and timestamp_key(row["lease_until"]) > timestamp_key(now)
                ):
                    return None
                fence = int(row["fence"]) + 1
                write(
                    self.access,
                    "command_receipts",
                    """UPDATE command_receipts SET state='claimed',claim_owner=?,fence=?,lease_until=?,updated_at=? WHERE id=?""",
                    (owner, fence, lease_end(now, seconds), now, receipt_id),
                )
            else:
                fence = 1
                write(
                    self.access,
                    "command_receipts",
                    f"""INSERT INTO command_receipts(id,{column},consumer,state,claim_owner,fence,lease_until,created_at,updated_at) VALUES (?,?,?,'claimed',?,?,?,?,?)""",
                    (
                        receipt_id,
                        request_id,
                        consumer,
                        owner,
                        fence,
                        lease_end(now, seconds),
                        now,
                        now,
                    ),
                )
        return ReceiptClaim(
            receipt_id=receipt_id,
            request_id=request_id,
            request_kind=kind,
            consumer=consumer,
            owner=owner,
            fence=fence,
        )

    def finish(
        self,
        claim: ReceiptClaim,
        *,
        now: str,
        status: Literal["succeeded", "failed"],
        result: dict[str, Any] | None = None,
        safe_code: str | None = None,
    ) -> None:
        require_role(self.access, claim.consumer)
        with self.access.transaction():
            row = self.access.conn.execute(
                "SELECT updated_at FROM command_receipts WHERE id=?", (claim.receipt_id,)
            ).fetchone()
            from probation.core.clock import timestamp_key

            if row is not None and timestamp_key(now) < timestamp_key(row["updated_at"]):
                raise StaleClaim("receipt_clock_reversed")
            old = self._get(claim.request_id, claim.request_kind, claim.consumer)
            if old and old.state in {"succeeded", "failed"}:
                if old.state == status and old.result == result and old.safe_code == safe_code:
                    return
                raise StaleClaim("receipt_already_completed")
            cursor = write(
                self.access,
                "command_receipts",
                """UPDATE command_receipts SET state=?,result_json=?,safe_code=?,updated_at=? WHERE id=? AND consumer=? AND claim_owner=? AND fence=? AND state='claimed' AND lease_until COLLATE UTC_TIMESTAMP > ?""",
                (
                    status,
                    canonical_json(result) if result is not None else None,
                    safe_code,
                    now,
                    claim.receipt_id,
                    claim.consumer,
                    claim.owner,
                    claim.fence,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleClaim("receipt_claim_expired")

    def checkpoint_command(
        self,
        claim: ReceiptClaim,
        *,
        now: str,
        lease_seconds: int,
        result: dict[str, Any],
    ) -> str:
        """Renew a claimed Examiner command while atomically saving its bounded checkpoint."""
        require_role(self.access, "examiner")
        if claim.request_kind != "command" or claim.consumer != "examiner":
            raise StaleClaim("checkpoint_claim_mismatch")
        until = lease_end(now, lease_seconds)
        with self.access.transaction():
            cursor = write(
                self.access,
                "command_receipts",
                """UPDATE command_receipts SET result_json=?,lease_until=?,updated_at=?
                WHERE id=? AND command_id=? AND consumer='examiner' AND claim_owner=?
                AND fence=? AND state='claimed' AND lease_until COLLATE UTC_TIMESTAMP > ?""",
                (
                    canonical_json(result),
                    until,
                    now,
                    claim.receipt_id,
                    claim.request_id,
                    claim.owner,
                    claim.fence,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleClaim("receipt_claim_expired")
        return until
