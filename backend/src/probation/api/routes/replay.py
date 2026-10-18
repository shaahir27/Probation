"""Replay state and control endpoints per CONTRACT.md section 9.

Authority: CONTRACT.md section 9:
GET /replay/state, POST /replay/{start|pause|speed}: Replay clock control (demo).
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import ClockMode

router = APIRouter(prefix="/api", tags=["replay"])

# Default replay clock instance
_clock = Clock(mode=ClockMode.REPLAY if settings.clock_mode == "replay" else ClockMode.LIVE)

# Global in-memory replay state for demo mode
_replay_state: dict[str, Any] = {
    "running": False,
    "speed": 1.0,
    "simulated_date": _clock.now_iso(),
    "mode": settings.clock_mode,
}


class ReplaySpeedBody(BaseModel):
    speed: float = Field(..., gt=0.0, description="Replay speed multiplier (e.g. 1.0, 10.0, 100.0)")


@router.get("/replay/state")
def get_replay_state() -> dict[str, Any]:
    """Retrieve current replay simulation state."""
    _replay_state["simulated_date"] = _clock.now_iso()
    _replay_state["mode"] = settings.clock_mode
    return _replay_state


@router.post("/replay/start")
def start_replay() -> dict[str, Any]:
    """Start replay clock progression."""
    _replay_state["running"] = True
    return {"ok": True, "state": _replay_state}


@router.post("/replay/pause")
def pause_replay() -> dict[str, Any]:
    """Pause replay clock progression."""
    _replay_state["running"] = False
    return {"ok": True, "state": _replay_state}


@router.post("/replay/speed")
def set_replay_speed(body: ReplaySpeedBody) -> dict[str, Any]:
    """Adjust replay simulation speed."""
    _replay_state["speed"] = body.speed
    return {"ok": True, "speed": body.speed, "state": _replay_state}
