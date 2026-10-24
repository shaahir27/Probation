"""Append-only human decisions and Executor-owned corrections with ledger parity."""

from probation.core.clock import timestamp_key
from probation.core.hashing import canonical_json
from probation.core.lifecycle import LifecycleConflict, LifecycleDenied, OutcomeEvent, StoredEvent
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import require_role, write


class EventStore:
    def __init__(self, access: RoleAccess) -> None:
        self.access = access

    def append(self, event: OutcomeEvent) -> StoredEvent:
        require_role(
            self.access,
            "resolver" if event.kind in {"decision", "footprint", "override"} else "executor",
        )
        if not self.access._connection.in_transaction:
            raise LifecycleDenied("event_requires_caller_transaction")
        old = self.access.conn.execute(
            "SELECT * FROM outcome_events WHERE id=? OR(source=? AND source_key=?)",
            (event.event_id, event.source, event.source_key),
        ).fetchone()
        data = canonical_json(event.model_dump())
        if old is not None:
            if old["event_json"] != data:
                raise LifecycleConflict("event_identity_conflict")
            return StoredEvent(event_id=old["id"], ledger_seq=old["ledger_seq"])
        self._validate(event)
        payload = event.model_dump(exclude={"details"})
        payload["situation_id"] = event.situation_id
        payload["observed_action"] = event.observed_action or (
            "REJECT" if event.decision == "reject" else event.kind.upper()
        )
        # Ledger summaries never contain bodies/addresses or arbitrary detail payloads.
        payload["details"] = {"event_id": event.event_id, "schema_version": 2}
        seq = self.access.append_ledger("outcome", event.event_id, payload, event.known_at)
        write(
            self.access,
            "outcome_events",
            """INSERT INTO outcome_events(id,situation_id,proposal_id,response_id,action_id,kind,source,actor,writer_role,decision,observed_action,strength,observed_at,known_at,source_key,correction_of,details_json,event_json,ledger_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event.event_id,
                event.situation_id,
                event.proposal_id,
                event.response_id,
                event.action_id,
                event.kind,
                event.source,
                event.actor,
                self.access.role.value,
                event.decision,
                event.observed_action,
                event.strength,
                event.observed_at,
                event.known_at,
                event.source_key,
                event.correction_of,
                canonical_json(event.details),
                data,
                seq,
            ),
        )
        return StoredEvent(event_id=event.event_id, ledger_seq=seq)

    def _validate(self, event: OutcomeEvent) -> None:
        proposal = self.access.conn.execute(
            "SELECT * FROM proposals WHERE id=? AND situation_id=?",
            (event.proposal_id, event.situation_id),
        ).fetchone()
        if (
            proposal is None
            or timestamp_key(event.known_at) <= timestamp_key(proposal["proposed_at"])
            or timestamp_key(event.observed_at) > timestamp_key(event.known_at)
        ):
            raise LifecycleDenied("invalid_event_identity_or_clock")
        if event.kind == "decision":
            request = self.access.conn.execute(
                "SELECT * FROM user_responses WHERE id=? AND proposal_id=? AND schema_version=2",
                (event.response_id, event.proposal_id),
            ).fetchone()
            if (
                request is None
                or request["response"] != event.decision
                or event.source != "user_response"
                or event.strength != "STRONG"
                or event.actor != "human"
            ):
                raise LifecycleDenied("invalid_decision_event")
            expected = (
                request["edited_action"]
                if event.decision == "edit"
                else proposal["action"]
                if event.decision == "accept"
                else None
            )
            if event.observed_action != expected or timestamp_key(
                request["responded_at"]
            ) > timestamp_key(event.known_at):
                raise LifecycleDenied("decision_payload_mismatch")
        elif event.kind in {"undo", "cancel"}:
            expected_status = "UNDONE" if event.kind == "undo" else "CANCELLED"
            action = self.access.conn.execute(
                "SELECT * FROM actions WHERE id=? AND proposal_id=? AND status=?",
                (event.action_id, event.proposal_id, expected_status),
            ).fetchone()
            request = self.access.conn.execute(
                "SELECT * FROM user_responses WHERE id=? AND action_id=? AND response='undo'",
                (event.response_id, event.action_id),
            ).fetchone()
            if (
                action is None
                or request is None
                or event.source != "undo"
                or event.strength != "STRONG"
                or event.actor != "human"
                or event.observed_action is not None
            ):
                raise LifecycleDenied("invalid_executor_correction")
            if timestamp_key(request["responded_at"]) > timestamp_key(event.known_at):
                raise LifecycleDenied("future_correction_request")
            if timestamp_key(event.known_at) < timestamp_key(action["updated_at"]):
                raise LifecycleDenied("correction_precedes_effect")
        elif event.kind == "override" and event.source != "override":
            raise LifecycleDenied("override_source_mismatch")
        elif event.kind == "footprint" and event.source not in {"footprint", "window_close"}:
            raise LifecycleDenied("footprint_source_mismatch")
