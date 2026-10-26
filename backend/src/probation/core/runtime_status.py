"""The one status document the runtime supervisor publishes and the API reads.

Authority: docs/CONTRACT.md section 9 and docs/OCT29_DEMO_BUILD_PLAN.md section 12.1
("API liveness separate from reader/model/embedding/connector/worker readiness"). It lives in
``core`` because both sides need it: the supervisor writes it, the API reads it, and neither may
import the other.

A missing, unreadable, unsupported or stale document means every role is unavailable. Readiness
is never inferred from configuration presence, and the document is the only cross-process status
channel: no role claims to be online on its own say-so.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from probation.core.clock import parse_timestamp

#: How old a supervisor document may be and still describe the running system (operational seconds).
STATUS_STALENESS_SECONDS: Final = 90.0
STATUS_DOCUMENT_NAME: Final = "probation_runtime_status.json"
STATUS_DOCUMENT_VERSION: Final = 1

#: The roles supervision must account for. A test asserts these match ``RuntimeRole`` exactly,
#: so a new role can never silently disappear from the readiness surface.
SUPERVISED_ROLES: Final[tuple[str, ...]] = (
    "observation",
    "brain",
    "resolver",
    "examiner",
    "api",
    "webfacts",
    "executor",
)


@dataclass(frozen=True, slots=True)
class RoleReadiness:
    """One role exactly as supervision observed it: liveness, work evidence, safe code."""

    role: str
    state: str
    ready: bool
    code: str | None = None
    last_tick_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "state": self.state,
            "ready": self.ready,
            "code": self.code,
            "last_tick_at": self.last_tick_at,
        }


def runtime_status_path(db_path: Path | str) -> Path:
    """The document is stored beside the engine database it describes."""
    return Path(db_path).with_name(STATUS_DOCUMENT_NAME)


def publish_runtime_status(
    path: Path | str,
    *,
    generated_at: str,
    clock_mode: str,
    roles: dict[str, RoleReadiness],
) -> bool:
    """Write one complete document atomically; a reader must never see half a tick.

    Returns whether the document was published. A supervisor that cannot publish says so instead
    of leaving the previous cycle's document to be mistaken for current state.
    """
    target = Path(path)
    payload = {
        "version": STATUS_DOCUMENT_VERSION,
        "generated_at": generated_at,
        "clock_mode": clock_mode,
        "roles": [roles[name].as_dict() for name in sorted(roles)],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=".status-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
        os.replace(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return False
    return True


def unavailable_readiness(*, clock_mode: str, reason: str) -> dict[str, Any]:
    """No usable document: report every role unavailable rather than guessing."""
    return {
        "available": False,
        "reason": reason,
        "clock_mode": clock_mode,
        "api_live": True,
        "generated_at": None,
        "stale": True,
        "age_seconds": None,
        "roles": [],
    }


def read_runtime_status(
    path: Path | str,
    *,
    now: datetime,
    clock_mode: str,
    role_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Read and validate the supervisor document. Anything doubtful is unavailable.

    ``now`` is operational time: the document ages against wall time, never against simulated
    scenario time, so a replay clock cannot freeze a stale claim of readiness.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return unavailable_readiness(clock_mode=clock_mode, reason="status_document_absent")
    try:
        document = json.loads(raw)
    except ValueError:
        return unavailable_readiness(clock_mode=clock_mode, reason="status_document_unparsable")
    if not isinstance(document, dict) or document.get("version") != STATUS_DOCUMENT_VERSION:
        return unavailable_readiness(clock_mode=clock_mode, reason="status_document_unsupported")
    generated_at = document.get("generated_at")
    rows = document.get("roles")
    if not isinstance(generated_at, str) or not isinstance(rows, list):
        return unavailable_readiness(clock_mode=clock_mode, reason="status_document_incomplete")
    try:
        age = (now - parse_timestamp(generated_at)).total_seconds()
    except (TypeError, ValueError):
        return unavailable_readiness(clock_mode=clock_mode, reason="status_document_unparsable")
    if age < 0 or age > STATUS_STALENESS_SECONDS:
        return unavailable_readiness(clock_mode=clock_mode, reason="status_document_stale")
    roles: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("role"), str):
            continue
        roles.append(
            {
                "role": str(row["role"]),
                "state": str(row.get("state", "unknown")),
                "ready": row.get("ready") is True,
                "code": row.get("code") if isinstance(row.get("code"), str) else None,
                "last_tick_at": row.get("last_tick_at")
                if isinstance(row.get("last_tick_at"), str)
                else None,
            }
        )
    known = {str(row["role"]) for row in roles}
    for missing in role_names:
        if missing not in known:
            roles.append(
                {
                    "role": missing,
                    "state": "unavailable",
                    "ready": False,
                    "code": "status_line_absent",
                    "last_tick_at": None,
                }
            )
    return {
        "available": True,
        "reason": None,
        "clock_mode": clock_mode,
        "api_live": True,
        "generated_at": generated_at,
        "stale": False,
        "age_seconds": round(age, 3),
        "roles": sorted(roles, key=lambda row: str(row["role"])),
    }
