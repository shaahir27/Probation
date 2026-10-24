"""Correlate observed mail with trusted execution journals and human action streams."""

import json
import sqlite3
from typing import Any

from probation.core.clock import timestamp_key
from probation.core.hashing import det_id
from probation.core.lifecycle import OutcomeEvent
from probation.core.types import Outcome
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_events import EventStore
from probation.packs.base import WorldView


def automation_message_ids(conn: sqlite3.Connection, as_of: str) -> set[str]:
    rows = conn.execute(
        """SELECT e.before_json,e.result_json FROM execution_attempts e
        JOIN actions a ON a.id=e.action_id WHERE e.operation='execute'
        AND a.pack='mail' AND a.type IN('REPLY','FORWARD')
        AND e.state IN('dispatched','unknown','confirmed')
        AND e.created_at COLLATE UTC_TIMESTAMP<=?""",
        (as_of,),
    ).fetchall()
    result: set[str] = set()
    for row in rows:
        before = json.loads(row["before_json"])
        message = before.get("payload", {}).get("message", {})
        if message.get("message_id"):
            result.add(str(message["message_id"]))
        receipt = json.loads(row["result_json"] or "{}")
        if receipt.get("native_ref"):
            result.add(str(receipt["native_ref"]))
    return result


def is_system_footprint(conn: sqlite3.Connection, raw_item_id: str, outcome: Outcome) -> bool:
    if outcome.observed_action in {"REPLY", "FORWARD"}:
        native = outcome.details.get("reply_message_id") or outcome.details.get(
            "forward_message_id"
        )
        return native in automation_message_ids(conn, outcome.known_at)
    raw = conn.execute("SELECT source_ref FROM raw_items WHERE id=?", (raw_item_id,)).fetchone()
    if raw is None:
        return True
    rows = conn.execute(
        """SELECT a.binding_json,a.created_at FROM actions a
        JOIN execution_attempts e ON e.action_id=a.id AND e.operation='execute'
        WHERE a.pack='mail' AND a.type=? AND e.state IN('dispatched','unknown','confirmed')
        AND e.created_at COLLATE UTC_TIMESTAMP<=?""",
        (outcome.observed_action, outcome.known_at),
    ).fetchall()
    for row in rows:
        binding = json.loads(row["binding_json"] or "{}")
        if binding.get("resource_id") == raw["source_ref"]:
            return True
    return False


def observe_manual_overrides(conn: sqlite3.Connection, world: WorldView, as_of: str) -> int:
    """Only a dated, explicitly human source event can establish an override."""
    access = RoleAccess(conn, Role.RESOLVER)
    actions = access.conn.execute(
        """SELECT a.*,p.situation_id FROM actions a
        JOIN proposals p ON p.id=a.proposal_id WHERE a.pack='mail' AND a.status='DONE'
        AND a.binding_json IS NOT NULL AND a.executed_at COLLATE UTC_TIMESTAMP<=?""",
        (as_of,),
    ).fetchall()
    count = 0
    for action in actions:
        binding = json.loads(action["binding_json"])
        resources = {binding["resource_id"], binding.get("native_message_id")}
        observations: list[dict[str, Any]] = []
        for resource in sorted(str(value) for value in resources if value):
            try:
                observations.extend(
                    world.get_user_actions(item_id=resource, as_of=as_of, actor="user")
                )
            except (AttributeError, TypeError, ValueError, sqlite3.Error):
                continue
        for observed in observations:
            known = observed.get("acted_at")
            if (
                observed.get("actor") != "user"
                or not isinstance(known, str)
                or observed.get("action_type")
                not in {
                    "ARCHIVE",
                    "TRASH",
                    "REPLY",
                    "FORWARD",
                    "LEAVE",
                    "UNARCHIVE",
                    "UNTRASH",
                    "RESTORE",
                    "OVERRIDE",
                    "UNDO",
                }
                or not observed.get("id")
                or observed.get("action_type") == action["type"]
                or timestamp_key(known) <= timestamp_key(action["executed_at"])
                or timestamp_key(known) > timestamp_key(as_of)
            ):
                continue
            source_key = f"{action['id']}:{observed['id']}"
            if access.conn.execute(
                "SELECT id FROM outcome_events WHERE source='override' AND source_key=?",
                (source_key,),
            ).fetchone():
                continue
            with access.transaction():
                EventStore(access).append(
                    OutcomeEvent(
                        event_id="override-" + det_id(source_key),
                        situation_id=action["situation_id"],
                        proposal_id=action["proposal_id"],
                        action_id=action["id"],
                        kind="override",
                        source="override",
                        source_key=source_key,
                        strength="STRONG",
                        observed_at=known,
                        known_at=known,
                        actor="human",
                        details={"observation_id": observed["id"]},
                    )
                )
            count += 1
    return count
