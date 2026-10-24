"""Immutable, scoped owner-control requests; Examiner owns consumption."""

from probation.core.lifecycle import CommandIntent, LifecycleConflict, Submission
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import digest, require_role, unpack, write


class CommandStore:
    def __init__(self, access: RoleAccess) -> None:
        self.access = access

    def get(self, request_id: str) -> CommandIntent | None:
        row = self.access.conn.execute(
            "SELECT * FROM command_requests WHERE id=?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return CommandIntent(
            request_id=row["id"],
            owner_id=row["owner_id"],
            type=row["type"],
            scope=unpack(row["scope_json"]),
            created_at=row["created_at"],
        )

    def submit(self, intent: CommandIntent) -> Submission:
        require_role(self.access, "api")
        semantic = intent.model_dump(exclude={"created_at"})
        with self.access.transaction():
            old = self.get(intent.request_id)
            if old is not None:
                if old.model_dump(exclude={"created_at"}) != semantic:
                    raise LifecycleConflict("request_payload_conflict")
                return Submission(request_id=old.request_id, existing=True)
            write(
                self.access,
                "command_requests",
                """INSERT INTO command_requests
                (id,schema_version,owner_id,request_key,type,scope_json,payload_hash,created_at)
                VALUES (?,1,?,?,?,?,?,?)""",
                (
                    intent.request_id,
                    intent.owner_id,
                    intent.request_id,
                    intent.type,
                    intent.scope.model_dump_json(),
                    digest(semantic),
                    intent.created_at,
                ),
            )
        return Submission(request_id=intent.request_id, existing=False)

    def known(self, as_of: str) -> list[CommandIntent]:
        rows = self.access.conn.execute(
            """SELECT id FROM command_requests
            WHERE created_at COLLATE UTC_TIMESTAMP <= ? ORDER BY created_at COLLATE UTC_TIMESTAMP,id""",
            (as_of,),
        ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]

    def pending(self, as_of: str, limit: int = 100) -> list[CommandIntent]:
        require_role(self.access, "examiner")
        rows = self.access.conn.execute(
            """SELECT c.id FROM command_requests c
            WHERE c.created_at COLLATE UTC_TIMESTAMP <= ? AND NOT EXISTS(
            SELECT 1 FROM command_receipts r WHERE r.command_id=c.id AND r.consumer='examiner'
            AND r.state IN('succeeded','failed')) ORDER BY c.created_at COLLATE UTC_TIMESTAMP,c.id LIMIT ?""",
            (as_of, limit),
        ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]
