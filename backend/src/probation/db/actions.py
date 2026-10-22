"""Executor-owned local action intent persistence, independent of remote effects."""

import json

from probation.core.hashing import canonical_json
from probation.core.types import Action
from probation.db.access import AccessError, Role, RoleAccess


def persist_action(access: RoleAccess, action: Action) -> Action:
    """Persist intent and its ledger entry atomically, preserving any parent UOW.

    This performs no remote effect and makes no remote reconciliation guarantee.
    A retry cannot reset a held/completed/failed action or change its target.
    """
    if access.role != Role.EXECUTOR:
        raise AccessError("Only Executor may persist action intent")
    with access.transaction():
        row = access.conn.execute("SELECT * FROM actions WHERE id=?", (action.id,)).fetchone()
        if row is not None:
            if (
                row["proposal_id"] != action.proposal_id
                or row["pack"] != action.pack
                or row["type"] != action.type
                or json.loads(row["params_json"]) != action.params
                or row["level_required"] != action.level_required
                or bool(row["recallable"]) != action.recallable
            ):
                raise ValueError("Retry would change immutable action intent")
            return Action(
                id=row["id"],
                proposal_id=row["proposal_id"],
                pack=row["pack"],
                type=row["type"],
                params=json.loads(row["params_json"]),
                level_required=row["level_required"],
                recallable=bool(row["recallable"]),
                status=row["status"],
                hold_until=row["hold_until"],
                undo=json.loads(row["undo_json"]) if row["undo_json"] else None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        access.execute_write(
            "actions",
            """INSERT INTO actions
            (id,proposal_id,pack,type,params_json,level_required,recallable,status,hold_until,
             undo_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?)""",
            (
                action.id,
                action.proposal_id,
                action.pack,
                action.type,
                canonical_json(action.params),
                action.level_required,
                int(action.recallable),
                action.status.value,
                action.hold_until,
                action.created_at,
                action.updated_at,
            ),
        )
        access.append_ledger(
            "action",
            action.id,
            {
                "action_id": action.id,
                "type": action.type,
                "status": action.status.value,
                "level_required": action.level_required,
            },
            action.created_at,
        )
    return action
