"""Resolver-owned consumption of immutable explicit owner decisions."""

import sqlite3

from probation.core.clock import get_clock
from probation.core.hashing import canonical_json, det_id
from probation.core.lifecycle import OutcomeEvent
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_events import EventStore
from probation.db.lifecycle_receipts import ReceiptStore
from probation.db.lifecycle_responses import ResponseStore


def resolve_responses(
    conn: sqlite3.Connection, *, as_of: str | None = None, limit: int = 32
) -> int:
    now = as_of or get_clock().now_iso()
    access = RoleAccess(conn, Role.RESOLVER)
    responses = ResponseStore(access)
    receipts = ReceiptStore(access)
    processed = 0
    for intent in responses.pending(now, limit=limit):
        if intent.response == "undo":
            continue
        with access.transaction():
            claim = receipts.claim_response(intent.request_id, now=now, owner="resolver")
            if claim is None:
                continue
            row = access.conn.execute(
                "SELECT situation_id FROM proposals WHERE id=?", (intent.proposal_id,)
            ).fetchone()
            if row is None:
                receipts.finish(claim, now=now, status="failed", safe_code="proposal_missing")
                continue
            event = OutcomeEvent(
                event_id="decision-" + det_id("response-v2", intent.request_id),
                situation_id=row["situation_id"],
                proposal_id=intent.proposal_id,
                kind="decision",
                source="user_response",
                source_key=intent.request_id,
                strength="STRONG",
                observed_at=intent.responded_at,
                known_at=intent.responded_at,
                response_id=intent.request_id,
                decision=intent.response,
                observed_action=None
                if intent.response == "reject"
                else intent.reviewed_payload.action,
                actor="human",
            )
            saved = EventStore(access).append(event)
            if event.observed_action is not None:
                access.execute_write(
                    "outcomes",
                    """INSERT OR IGNORE INTO outcomes
                    (situation_id,observed_action,strength,source,observed_at,known_at,details_json,ledger_seq)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        event.situation_id,
                        event.observed_action,
                        event.strength,
                        event.source,
                        event.observed_at,
                        event.known_at,
                        canonical_json({"event_id": event.event_id}),
                        saved.ledger_seq,
                    ),
                )
            receipts.finish(claim, now=now, status="succeeded", result={"event_id": saved.event_id})
            processed += 1
    return processed
