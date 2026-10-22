"""Strict administrative intents; the API enqueues and Examiner applies results."""

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from probation.core.actions import parse_action
from probation.core.clock import format_timestamp
from probation.core.hashing import canonical_json, det_id
from probation.db.access import AccessError, Role, RoleAccess


class CommandModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class DenyHabit(CommandModel):
    kind: Literal["deny_habit"] = "deny_habit"
    habit_id: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")


class RunExam(CommandModel):
    kind: Literal["run_exam"] = "run_exam"
    class_key: str = Field(min_length=3, max_length=256, pattern=r"^[^\s|]+(?:\|[^\s|]+)+$")
    action: str = Field(min_length=1, max_length=4096)
    level: Literal[2, 3] = 2
    attempt_ordinal: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("level", mode="before")
    @classmethod
    def strict_level(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Level must be an integer")
        return value

    @field_validator("action")
    @classmethod
    def valid_action(cls, value: str) -> str:
        parsed = parse_action(value)
        if parsed.is_noop:
            raise ValueError("No-op actions cannot be examined for autonomy")
        return parsed.label


AdminCommand = Annotated[DenyHabit | RunExam, Field(discriminator="kind")]
COMMAND_ADAPTER: TypeAdapter[DenyHabit | RunExam] = TypeAdapter(AdminCommand)


def command_record(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "requested_at": row["requested_at"],
        "updated_at": row["updated_at"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
    }


def enqueue_command(
    access: RoleAccess, command: DenyHabit | RunExam, requested_at: str
) -> dict[str, Any]:
    if access.role != Role.API:
        raise AccessError("Only API may enqueue an administrative intent")
    payload = canonical_json(command.model_dump())
    command_id = det_id("admin-command-v1", payload)
    with access.transaction():
        existing = access.conn.execute(
            "SELECT * FROM admin_commands WHERE id=?", (command_id,)
        ).fetchone()
        if existing is not None:
            if existing["payload_json"] != payload:
                raise ValueError("Command identity collision")
            return command_record(existing)
        if isinstance(command, DenyHabit):
            exists = access.conn.execute(
                "SELECT 1 FROM habits WHERE id=?", (command.habit_id,)
            ).fetchone()
        else:
            exists = access.conn.execute(
                "SELECT 1 FROM proposals WHERE class_key=? AND action=? LIMIT 1",
                (command.class_key, command.action),
            ).fetchone()
        if exists is None:
            raise LookupError("Requested habit or exact exam pair does not exist")
        timestamp = format_timestamp(requested_at)
        access.execute_write(
            "admin_commands",
            """INSERT INTO admin_commands
            (id,kind,payload_json,status,requested_at,updated_at) VALUES (?,?,?,'PENDING',?,?)""",
            (command_id, command.kind, payload, timestamp, timestamp),
        )
        row = access.conn.execute(
            "SELECT * FROM admin_commands WHERE id=?", (command_id,)
        ).fetchone()
        return command_record(row)
