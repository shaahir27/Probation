"""Narrow SQL capability shared only by typed lifecycle repositories."""

import hashlib
import json
from datetime import timedelta
from typing import Any

from probation.core.clock import format_timestamp, parse_timestamp
from probation.core.hashing import canonical_json
from probation.db.access import AccessError, RoleAccess
from probation.db.guards import ReadCursor

TYPED_TABLES = frozenset(
    {"outcome_events", "command_receipts", "execution_attempts", "command_requests"}
)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def unpack(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def lease_end(now: str, seconds: int) -> str:
    if seconds <= 0:
        raise ValueError("lease duration must be positive")
    return format_timestamp(parse_timestamp(now) + timedelta(seconds=seconds))


def write(access: RoleAccess, table: str, sql: str, params: tuple[Any, ...] = ()) -> ReadCursor:
    """Private scoped writer; each public store validates row ownership first."""
    return access._execute_write(table, sql, params)


def require_role(access: RoleAccess, *roles: str) -> None:
    if access.role.value not in roles:
        raise AccessError("Lifecycle operation exceeds role authority")
