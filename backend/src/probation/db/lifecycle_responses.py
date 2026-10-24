"""Atomic first-decision-wins, immutable reviewed response intents."""

from probation.core.clock import timestamp_key
from probation.core.hashing import canonical_json
from probation.core.lifecycle import (
    LifecycleConflict,
    LifecycleDenied,
    ResponseIntent,
    Submission,
    binding_hash,
)
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import digest, require_role, unpack, write


class ResponseStore:
    def __init__(self, access: RoleAccess) -> None:
        self.access = access

    def get(self, request_id: str) -> ResponseIntent | None:
        row = self.access.conn.execute(
            "SELECT * FROM user_responses WHERE id=? AND schema_version=2", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return ResponseIntent(
            request_id=row["id"],
            proposal_id=row["proposal_id"],
            response=row["response"],
            owner_id=row["owner_id"],
            responded_at=row["responded_at"],
            reviewed_payload=unpack(row["reviewed_payload_json"]),
            reviewed_payload_hash=row["reviewed_payload_hash"],
            action_id=row["action_id"],
            edited_action=row["edited_action"],
        )

    def submit(self, intent: ResponseIntent) -> Submission:
        require_role(self.access, "api")
        if self.access._connection.in_transaction:
            raise LifecycleDenied("response_requires_clean_transaction")
        semantic = intent.model_dump(exclude={"responded_at"})
        with self.access.transaction():
            row = self.access.conn.execute(
                "SELECT * FROM user_responses WHERE id=?", (intent.request_id,)
            ).fetchone()
            if row is not None:
                if row["schema_version"] != 2 or row["intent_hash"] != digest(semantic):
                    raise LifecycleConflict("request_payload_conflict")
                return Submission(request_id=intent.request_id, existing=True)
            self._validate(intent)
            if intent.response != "undo":
                old = self.access.conn.execute(
                    "SELECT id FROM user_responses WHERE proposal_id=? AND response IN('accept','reject','edit') LIMIT 1",
                    (intent.proposal_id,),
                ).fetchone()
                if old is not None:
                    raise LifecycleConflict("initial_decision_already_recorded")
            write(
                self.access,
                "user_responses",
                """INSERT INTO user_responses
                (id,proposal_id,action_id,response,edited_action,responded_at,schema_version,request_key,owner_id,reviewed_payload_json,reviewed_payload_hash,intent_hash)
                VALUES (?,?,?,?,?,?,2,?,?,?,?,?)""",
                (
                    intent.request_id,
                    intent.proposal_id,
                    intent.action_id,
                    intent.response,
                    intent.edited_action,
                    intent.responded_at,
                    intent.request_id,
                    intent.owner_id,
                    canonical_json(intent.reviewed_payload.model_dump()),
                    intent.reviewed_payload_hash,
                    digest(semantic),
                ),
            )
        return Submission(request_id=intent.request_id, existing=False)

    def _validate(self, intent: ResponseIntent) -> None:
        binding = intent.reviewed_payload
        if (
            binding.owner_id != intent.owner_id
            or binding_hash(binding) != intent.reviewed_payload_hash
        ):
            raise LifecycleDenied("review_binding_mismatch")
        if not all(
            (
                intent.request_id,
                intent.owner_id,
                binding.connection_id,
                binding.account_id,
                binding.resource_id,
                binding.source_hash,
            )
        ):
            raise LifecycleDenied("incomplete_binding")
        row = self.access.conn.execute(
            """SELECT p.*,r.content_hash AS raw_hash,r.payload_json,r.source_ref FROM proposals p JOIN situations s ON s.id=p.situation_id JOIN raw_items r ON r.id=s.raw_item_id WHERE p.id=?""",
            (intent.proposal_id,),
        ).fetchone()
        if row is None:
            raise LifecycleDenied("missing_proposal")
        if timestamp_key(intent.responded_at) <= timestamp_key(row["proposed_at"]):
            raise LifecycleDenied("inconsistent_response_clock")
        source_hash = digest(
            {
                "payload": unpack(row["payload_json"]),
                "source_ref": row["source_ref"],
                "content_hash": row["raw_hash"],
            }
        )
        if binding.source_hash != source_hash or binding.resource_id != row["source_ref"]:
            raise LifecycleDenied("source_binding_mismatch")
        if intent.response == "undo":
            action = self.access.conn.execute(
                "SELECT * FROM actions WHERE id=? AND proposal_id=?",
                (intent.action_id, intent.proposal_id),
            ).fetchone()
            if action is None or action["binding_hash"] != intent.reviewed_payload_hash:
                raise LifecycleDenied("undo_binding_mismatch")
        elif intent.action_id is not None:
            raise LifecycleDenied("unexpected_action_reference")
        elif intent.response == "accept" and binding.action != row["action"]:
            raise LifecycleDenied("action_binding_mismatch")
        elif intent.response == "edit" and (
            not intent.edited_action or intent.edited_action != binding.action
        ):
            raise LifecycleDenied("edited_action_binding_mismatch")

    def pending(self, as_of: str, limit: int = 100) -> list[ResponseIntent]:
        require_role(self.access, "resolver", "executor")
        consumer = self.access.role.value
        selected = (
            "('accept','reject','edit')" if consumer == "resolver" else "('accept','edit','undo')"
        )
        rows = self.access.conn.execute(
            f"""SELECT u.id FROM user_responses u WHERE u.schema_version=2 AND u.responded_at COLLATE UTC_TIMESTAMP <= ? AND u.response IN {selected} AND NOT EXISTS(SELECT 1 FROM command_receipts r WHERE r.response_id=u.id AND r.consumer=? AND r.state IN('succeeded','failed')) ORDER BY u.responded_at COLLATE UTC_TIMESTAMP,u.id LIMIT ?""",
            (as_of, consumer, limit),
        ).fetchall()
        return [item for row in rows if (item := self.get(row["id"])) is not None]
