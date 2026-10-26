"""Strict, versioned replay control commands and the server-derived replay scope.

Authority: docs/CONTRACT.md sections 3 and 9, docs/wp9/D6_API_CONTRACT.md.

Two time domains meet here and must never be confused:

* **Operational time** is real process time. It stamps command intake, leases, receipts and
  liveness. It is only ever produced by ``core.clock.Clock`` in live mode.
* **Simulated time** is the historical instant the engine reasons at. It only ever comes from
  the durable replay checkpoint projected forward, never from a client.

This module freezes the *operational* command contract: who asked, for which server-derived
scope, with which bounded speed. It carries no path, run or workspace identifier supplied by a
client, and it holds no simulated time at all.
"""

import hashlib
import math
from pathlib import Path
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPLAY_COMMAND_SCHEMA_VERSION: Final = 2
REPLAY_CONTROL_TYPES: Final = ("replay_start", "replay_pause", "replay_speed")

#: The only speeds a control may request. Anything else (0, negative, NaN, infinity, a float)
#: is rejected before it reaches storage, because an unbounded multiplier would project an
#: unbounded simulated horizon.
REPLAY_SPEEDS: Final = (1, 10, 100)

#: Server-derived, stable run identity for one workspace's replay. A restart must address the
#: same run, otherwise the durable checkpoint it just wrote becomes unreachable.
REPLAY_RUN_ID: Final = "active"

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$"
_REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$"


class ReplayControlRecord(BaseModel):
    """Frozen, closed record: unknown fields are refused, never tolerated."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _reject_traversal(value: str, field: str) -> str:
    """Refuse identifiers that could be read as a path or a traversal token."""
    if ".." in value or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"{field} must not contain a path or traversal token")
    return value


class ReplayScope(ReplayControlRecord):
    """One workspace's replay run, derived only from trusted server configuration."""

    schema_version: Literal[2] = REPLAY_COMMAND_SCHEMA_VERSION
    workspace_id: str = Field(min_length=1, max_length=120, pattern=_IDENTIFIER_PATTERN)
    run_id: str = Field(min_length=1, max_length=120, pattern=_IDENTIFIER_PATTERN)

    @field_validator("workspace_id", "run_id")
    @classmethod
    def safe_identifier(cls, value: str) -> str:
        return _reject_traversal(value, "scope identifier")

    @classmethod
    def for_owner(cls, *, owner_id: str, target: str | Path) -> "ReplayScope":
        """Compatibility name for the one server-side derivation below.

        Read surfaces may build a scope this way, but must project the durable checkpoint through
        `engine.replay_kernel.project_replay_state` rather than re-deriving simulated time: lease
        and fence rules belong to that function alone.
        """
        return server_replay_scope(owner_id, target)


def replay_workspace_id(owner_id: str, target: Path | str) -> str:
    """Bounded, non-reversible workspace identity from the trusted owner and database target."""
    digest = hashlib.sha256(f"{owner_id}\0{Path(target)}".encode()).hexdigest()
    return digest[:24]


def replay_run_id(owner_id: str, target: Path | str) -> str:
    """The run identity a workspace's replay is always addressed by, owner- and db-scoped.

    A restart must find the run it just left, so this is stable rather than per-process. It is a
    function, not a literal, so the derivation stays in this one place for both the API read
    surface and the Examiner controller.
    """
    if not owner_id or not owner_id.strip() or len(owner_id) > 256:
        raise ValueError("replay scope requires a trusted owner identity")
    return REPLAY_RUN_ID


def server_replay_scope(owner_id: str, target: Path | str) -> ReplayScope:
    """The one scope derivation shared by the API and the Examiner controller.

    Both sides must land on the same ``run_id`` or the state the controller writes and the state
    the API reads would be two different runs.
    """
    return ReplayScope(
        workspace_id=replay_workspace_id(owner_id, target),
        run_id=replay_run_id(owner_id, target),
    )


class ReplayCommandIntent(ReplayControlRecord):
    """A durable, owner-scoped replay intent as stored by the API role."""

    schema_version: Literal[2] = REPLAY_COMMAND_SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=160, pattern=_REQUEST_ID_PATTERN)
    owner_id: str = Field(min_length=1, max_length=120)
    type: Literal["replay_start", "replay_pause", "replay_speed"]
    scope: ReplayScope
    speed: int | None = None
    created_at: str

    @field_validator("request_id")
    @classmethod
    def safe_request_id(cls, value: str) -> str:
        return _reject_traversal(value, "request_id")

    @field_validator("speed")
    @classmethod
    def finite_speed(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("replay speed must be a whole number")
        if not math.isfinite(float(value)) or value not in REPLAY_SPEEDS:
            raise ValueError("replay speed must be one of the supported multipliers")
        return value

    @field_validator("created_at")
    @classmethod
    def valid_instant(cls, value: str) -> str:
        from probation.core.clock import ClockError, parse_timestamp

        try:
            parse_timestamp(value)
        except (ClockError, ValueError, TypeError) as exc:
            raise ValueError("created_at must be a UTC instant") from exc
        return value

    @model_validator(mode="after")
    def speed_matches_command(self) -> Self:
        if (self.type == "replay_speed") != (self.speed is not None):
            raise ValueError("replay speed is required only for speed commands")
        return self

    @property
    def semantic_payload(self) -> dict[str, Any]:
        """Everything that defines identity for dedupe; the intake instant is excluded."""
        return self.model_dump(exclude={"created_at"})

    def same_semantics(self, other: "ReplayCommandIntent") -> bool:
        return self.semantic_payload == other.semantic_payload
