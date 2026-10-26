"""Typed storage for durable replay intents and append-only checkpoints.

Authority: docs/CONTRACT.md section 3 (the API writes `command_requests` intents; the Examiner
owns `command_receipts`) and docs/wp9/D6_API_CONTRACT.md. No new ledger kind, writer or table
lives here: progression is checkpointed inside the Examiner's own command receipts.
"""

from typing import Any

from probation.core.hashing import canonical_json
from probation.core.lifecycle import LifecycleConflict, Submission
from probation.core.replay_controls import (
    REPLAY_COMMAND_SCHEMA_VERSION,
    ReplayCommandIntent,
    ReplayScope,
)
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import digest, require_role, unpack, write

_CONSUMED_MARKER = "$.command_consumed"


class ReplayCommandStore:
    def __init__(self, access: RoleAccess) -> None:
        self.access = access

    def get(self, request_id: str) -> ReplayCommandIntent | None:
        row = self.access.conn.execute(
            "SELECT * FROM command_requests WHERE id=? AND schema_version=?",
            (request_id, REPLAY_COMMAND_SCHEMA_VERSION),
        ).fetchone()
        if row is None:
            return None
        payload = unpack(row["scope_json"])
        speed = payload.pop("speed", None)
        return ReplayCommandIntent(
            request_id=row["id"],
            owner_id=row["owner_id"],
            type=row["type"],
            scope=ReplayScope.model_validate(payload),
            speed=speed,
            created_at=row["created_at"],
        )

    def submit(self, intent: ReplayCommandIntent) -> Submission:
        require_role(self.access, "api")
        semantic = intent.semantic_payload
        scope = intent.scope.model_dump()
        if intent.speed is not None:
            scope["speed"] = intent.speed
        with self.access.transaction():
            any_version = self.access.conn.execute(
                "SELECT schema_version FROM command_requests WHERE id=?", (intent.request_id,)
            ).fetchone()
            if any_version is not None and int(any_version["schema_version"]) != (
                REPLAY_COMMAND_SCHEMA_VERSION
            ):
                raise LifecycleConflict("request_payload_conflict")
            old = self.get(intent.request_id)
            if old is not None:
                if not old.same_semantics(intent):
                    raise LifecycleConflict("request_payload_conflict")
                return Submission(request_id=old.request_id, existing=True)
            write(
                self.access,
                "command_requests",
                """INSERT INTO command_requests
                (id,schema_version,owner_id,request_key,type,scope_json,payload_hash,created_at)
                VALUES (?,2,?,?,?,?,?,?)""",
                (
                    intent.request_id,
                    intent.owner_id,
                    intent.request_id,
                    intent.type,
                    canonical_json(scope),
                    digest(semantic),
                    intent.created_at,
                ),
            )
        return Submission(request_id=intent.request_id, existing=False)

    def pending(self, as_of: str, limit: int = 32) -> list[ReplayCommandIntent]:
        """Intents the Examiner may still take on.

        A consumed anchor command stays out of the queue even after its lease expires: it is the
        durable handle the run re-claims to continue, not work left undone. Letting it return
        would resurrect an old start over a later pause.
        """
        require_role(self.access, "examiner")
        rows = self.access.conn.execute(
            f"""SELECT c.id FROM command_requests c
            WHERE c.schema_version=2 AND c.created_at COLLATE UTC_TIMESTAMP <= ?
            AND NOT EXISTS(SELECT 1 FROM command_receipts r
                WHERE r.command_id=c.id AND r.consumer='examiner' AND
                (r.state IN('succeeded','failed') OR
                (r.state='claimed' AND (r.lease_until COLLATE UTC_TIMESTAMP > ? OR
                json_extract(r.result_json,'{_CONSUMED_MARKER}')=1))))
            ORDER BY c.created_at COLLATE UTC_TIMESTAMP,c.id LIMIT ?""",
            (as_of, as_of, limit),
        ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]

    def checkpoint(self, *, workspace_id: str, run_id: str) -> dict[str, Any] | None:
        """The newest durable replay state for one server-derived scope, with its fence.

        `receipt_fence` and `claim_owner` come from the receipt row itself, never from the
        checkpoint body, so a reader can tell whether the epoch the state was written under is
        still the epoch that owns the lease.
        """
        row = self.access.conn.execute(
            """SELECT r.id,r.result_json,r.updated_at,r.state,r.fence,r.claim_owner,
               r.lease_until FROM command_receipts r
            JOIN command_requests c ON c.id=r.command_id
            WHERE c.schema_version=2 AND c.scope_json IS NOT NULL
            AND json_extract(c.scope_json,'$.workspace_id')=?
            AND json_extract(c.scope_json,'$.run_id')=?
            AND r.consumer='examiner' AND r.state IN('claimed','succeeded')
            AND r.result_json IS NOT NULL
            ORDER BY CASE WHEN r.state='claimed' THEN 0 ELSE 1 END,
                r.updated_at COLLATE UTC_TIMESTAMP DESC,
                c.created_at COLLATE UTC_TIMESTAMP DESC,c.id DESC LIMIT 1""",
            (workspace_id, run_id),
        ).fetchone()
        if row is None:
            return None
        checkpoint = unpack(row["result_json"])
        if not isinstance(checkpoint, dict):
            return None
        return {
            **checkpoint,
            "operational_at": checkpoint.get("operational_at", row["updated_at"]),
            "receipt_state": row["state"],
            "receipt_id": row["id"],
            "receipt_fence": int(row["fence"]),
            "claim_owner": row["claim_owner"],
            "lease_until": row["lease_until"],
            "valid_until": checkpoint.get("valid_until"),
        }

    def anchor(
        self, *, workspace_id: str, run_id: str, exclude_command_id: str | None = None
    ) -> dict[str, Any] | None:
        """The command whose receipt the run still holds, for a lease renewed after a restart.

        `exclude_command_id` keeps the intent being processed out of its own way: a claim just
        taken for it must not be read back as the run's anchor, or a pause would release itself.
        """
        clause = ""
        params: list[Any] = [workspace_id, run_id]
        if exclude_command_id is not None:
            clause = "AND r.command_id<>?"
            params.append(exclude_command_id)
        row = self.access.conn.execute(
            f"""SELECT r.command_id,r.state,r.fence,r.claim_owner,r.lease_until,
               r.updated_at FROM command_receipts r
            JOIN command_requests c ON c.id=r.command_id
            WHERE c.schema_version=2 AND r.consumer='examiner' AND r.state='claimed'
            AND json_extract(c.scope_json,'$.workspace_id')=?
            AND json_extract(c.scope_json,'$.run_id')=?
            {clause}
            ORDER BY r.updated_at COLLATE UTC_TIMESTAMP DESC LIMIT 1""",
            tuple(params),
        ).fetchone()
        if row is None:
            return None
        return {
            "command_id": str(row["command_id"]),
            "state": str(row["state"]),
            "fence": int(row["fence"]),
            "claim_owner": row["claim_owner"],
            "lease_until": row["lease_until"],
            "updated_at": row["updated_at"],
        }
