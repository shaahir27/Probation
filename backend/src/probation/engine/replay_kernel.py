"""Shared incremental replay kernel: one total-ordered event stream, one time projection.

Authority: docs/ENGINE_SPEC.md section 1, docs/CONTRACT.md I-6, I-7, I-8, I-9 and
docs/wp9/D6_API_CONTRACT.md.

The same stream is consumed two ways, which is the point of this module:

* the batch backtest loop (``engine/replay.py``) drains it in one process;
* the durable Examiner replay run (``workers/replay_controller.py``) advances it in
  simulated-time windows, so a resumed run and an uninterrupted run reach the same results.

The kernel owns event ordering, the monotonic cursor, the durable position and the projection
that turns a saved checkpoint plus operational time into the simulated instant the engine reads.
It deliberately owns no gate, licence or exam policy: those stay in the engine, so projecting a
replay can never quietly change a decision.

Time domains stay separate here: ``operational_at`` is real process time (leases, receipts,
liveness); ``simulated_at`` is the historical instant the engine reasons at and is only ever
derived from the durable checkpoint, never from a client.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from probation.core.clock import format_timestamp, parse_timestamp, timestamp_key
from probation.core.replay_controls import REPLAY_SPEEDS
from probation.db.guards import ReadConnection

PRIORITY_OUTCOME_KNOWN = 0
PRIORITY_LICENCE_REVIEW = 1
PRIORITY_RETRAIN = 2
PRIORITY_SITUATION = 3

_DEFAULT_SPEED = 1


@dataclass(slots=True)
class ReplayEvent:
    """An atomic point of occurrence on the merged replay timeline."""

    timestamp: str
    priority: int
    kind: str
    payload: Any = None
    tie_id: str = ""

    def sort_key(self) -> tuple[datetime, int, str]:
        """Compute sort key guaranteeing non-decreasing time and tie-break ordering.

        `tie_id` makes the order total. Without it, two events at the same instant and
        priority fall back to list position, which is whatever the producing SQL query
        returned; SQLite does not guarantee that order for equal keys, so an index or
        planner change could silently reorder a replay and change its ledger head.
        """
        return (parse_utc_dt(self.timestamp), self.priority, self.tie_id)

    def instant_key(self) -> tuple[int, int, str]:
        """Lossless integer ordering key for the same event."""
        return (timestamp_key(self.timestamp), self.priority, self.tie_id)


def parse_utc_dt(ts_str: str) -> datetime:
    """Parse timestamp into UTC datetime."""
    return parse_timestamp(ts_str)


@dataclass(frozen=True, slots=True)
class ReplayPosition:
    """The last event whose effect is durable, so a resume never re-applies one."""

    timestamp: str
    priority: int
    tie_id: str

    def key(self) -> tuple[int, int, str]:
        return (timestamp_key(self.timestamp), self.priority, self.tie_id)

    def covers(self, event: ReplayEvent) -> bool:
        return event.instant_key() <= self.key()

    def as_json(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "priority": self.priority, "tie_id": self.tie_id}

    @classmethod
    def from_json(cls, value: Any) -> ReplayPosition | None:
        """Best-effort read of a persisted cursor; malformed input yields no cursor."""
        if not isinstance(value, dict):
            return None
        timestamp = value.get("timestamp")
        priority = value.get("priority")
        tie_id = value.get("tie_id")
        if not isinstance(timestamp, str) or not isinstance(priority, int):
            return None
        try:
            timestamp_key(timestamp)
        except Exception:
            return None
        return cls(timestamp=timestamp, priority=priority, tie_id=str(tie_id or ""))


@dataclass(slots=True)
class ReplayTimeline:
    """Total-ordered event stream with a monotonic cursor and a durable position."""

    events: list[ReplayEvent]
    index: int = 0
    position: ReplayPosition | None = None

    @classmethod
    def build(cls, events: Iterable[ReplayEvent]) -> ReplayTimeline:
        return cls(events=sorted(events, key=lambda ev: ev.sort_key()))

    def __len__(self) -> int:
        return len(self.events)

    @property
    def remaining(self) -> int:
        return len(self.events) - self.index

    def events_until(self, horizon: str | None) -> list[ReplayEvent]:
        """Take the next run of events whose simulated instant is at or before `horizon`.

        A `None` horizon drains the whole stream, which is what a batch backtest does.
        """
        taken: list[ReplayEvent] = []
        while self.index < len(self.events):
            event = self.events[self.index]
            if horizon is not None and timestamp_key(event.timestamp) > timestamp_key(horizon):
                break
            taken.append(event)
            self.index += 1
        return taken

    def mark_applied(self, event: ReplayEvent) -> ReplayPosition:
        self.position = ReplayPosition(event.timestamp, event.priority, event.tie_id)
        return self.position

    def resume_after(self, position: ReplayPosition | None) -> None:
        """Move the cursor past `position`; its event and everything before it is durable."""
        self.position = position
        if position is None:
            self.index = 0
            return
        first = 0
        while first < len(self.events) and position.covers(self.events[first]):
            first += 1
        self.index = first


def daily_tick_events(
    first: datetime, last: datetime, retrain_interval_days: int
) -> list[ReplayEvent]:
    """Daily licence-review ticks plus a retrain tick every `retrain_interval_days` days."""
    if retrain_interval_days <= 0:
        raise ValueError("retrain interval must be positive")
    events: list[ReplayEvent] = []
    current_day = first.replace(hour=0, minute=0, second=0, microsecond=0)
    day_idx = 0
    while current_day <= last:
        day_iso = current_day.strftime("%Y-%m-%dT00:00:00Z")
        events.append(
            ReplayEvent(timestamp=day_iso, priority=PRIORITY_LICENCE_REVIEW, kind="LICENCE_REVIEW")
        )
        if day_idx % retrain_interval_days == 0:
            events.append(ReplayEvent(timestamp=day_iso, priority=PRIORITY_RETRAIN, kind="RETRAIN"))
        current_day += timedelta(days=1)
        day_idx += 1
    return events


def _supported_speed(value: Any) -> int | None:
    """Only the frozen multiplier set is a speed; anything else is no speed at all."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value not in REPLAY_SPEEDS:
        return None
    return int(value)


def open_decision_count(
    conn: sqlite3.Connection | ReadConnection, *, simulated_at: str, limit: int = 50
) -> int:
    """Bounded read of decisions whose answer only exists at a later simulated instant.

    A situation at or before the simulated horizon without a durable outcome, and a held action
    whose cancel window has not passed in simulated time, can only be resolved by advancing the
    replay. While replay is paused this is reported honestly as "replay must briefly resume";
    it is never fixed by inventing a later `known_at` (docs/CONTRACT.md I-7).
    """
    if limit <= 0:
        raise ValueError("decision scan limit must be positive")
    rows = conn.execute(
        """SELECT 1 FROM situations s
        WHERE s.occurred_at COLLATE UTC_TIMESTAMP <= ?
          AND EXISTS(SELECT 1 FROM proposals p WHERE p.situation_id = s.id)
          AND NOT EXISTS(SELECT 1 FROM outcomes o WHERE o.situation_id = s.id)
        LIMIT ?""",
        (simulated_at, limit),
    ).fetchall()
    held = conn.execute(
        """SELECT 1 FROM actions WHERE status = 'HELD' AND hold_until IS NOT NULL
          AND hold_until COLLATE UTC_TIMESTAMP > ?
        LIMIT ?""",
        (simulated_at, limit),
    ).fetchall()
    return len(rows) + len(held)


@dataclass(frozen=True, slots=True)
class ReplayProjection:
    """What the replay surface can honestly claim right now."""

    running: bool = False
    speed: int = _DEFAULT_SPEED
    simulated_at: str | None = None
    available: bool = True
    resumable: bool = False
    must_resume: bool = False
    last_request_id: str | None = None
    position: ReplayPosition | None = None
    reason: str | None = None
    mode: str = "live"

    def as_state_document(self) -> dict[str, Any]:
        """The documented read shape; `last_request_id` is present only when known."""
        document: dict[str, Any] = {
            "running": self.running,
            "speed": self.speed,
            "simulated_date": self.simulated_at,
            "mode": self.mode,
            "available": self.available,
            "resumable": self.resumable,
            "must_resume": self.must_resume,
        }
        if self.last_request_id is not None:
            document["last_request_id"] = self.last_request_id
        if self.reason is not None:
            document["reason"] = self.reason
        if self.position is not None:
            document["position"] = self.position.as_json()
        return document


def project_replay_state(
    checkpoint: Mapping[str, Any] | None,
    *,
    operational_at: str,
    default_simulated_at: str,
    mode: str,
    open_decisions: int = 0,
) -> ReplayProjection:
    """Project the durable checkpoint to the simulated instant at `operational_at`.

    The single projection shared by the API read surface and the Examiner controller: they can
    no longer disagree, because there is only one function. It never counts simulated time that
    no lease authorises, and it never reports `running` for a command that already reached a
    terminal receipt state.
    """
    if checkpoint is None:
        return ReplayProjection(
            simulated_at=default_simulated_at, mode=mode, reason="no_replay_command"
        )
    speed = _supported_speed(checkpoint.get("speed", _DEFAULT_SPEED))
    if speed is None:
        return ReplayProjection(mode=mode, available=False, reason="unsupported_replay_speed")

    position = ReplayPosition.from_json(checkpoint.get("position"))
    request = checkpoint.get("last_request_id")
    last_request_id = str(request) if request else None
    stored_simulated = checkpoint.get("simulated_at")
    anchor_operational = checkpoint.get("operational_at")
    state = str(checkpoint.get("receipt_state") or "")

    def stopped(
        simulated_at: str | None,
        reason: str,
        *,
        available: bool = True,
        resumable: bool = True,
    ) -> ReplayProjection:
        return ReplayProjection(
            running=False,
            speed=speed,
            simulated_at=simulated_at,
            available=available,
            resumable=resumable,
            must_resume=open_decisions > 0,
            last_request_id=last_request_id,
            position=position,
            reason=reason,
            mode=mode,
        )

    if not isinstance(stored_simulated, str):
        return stopped(default_simulated_at, "no_checkpoint_position", resumable=False)
    try:
        simulated = parse_timestamp(stored_simulated)
        anchor = parse_timestamp(str(anchor_operational or operational_at))
        now = parse_timestamp(operational_at)
    except Exception:
        return stopped(None, "unreadable_checkpoint", available=False, resumable=False)
    durable = format_timestamp(simulated)
    if now < anchor:
        return stopped(durable, "operational_clock_reversed", available=False, resumable=False)

    running = bool(checkpoint.get("running", False))
    if not running:
        terminal = state in {"succeeded", "failed"}
        reason = str(
            checkpoint.get("stopped_reason")
            or ("command_finalized" if terminal else "replay_paused")
        )
        return stopped(durable, reason)
    if state != "claimed":
        return stopped(durable, "command_finalized" if state else "no_live_claim")

    valid_until = checkpoint.get("valid_until")
    if not isinstance(valid_until, str):
        return stopped(durable, "claim_without_lease", available=False, resumable=False)
    epoch, fence = checkpoint.get("controller_epoch"), checkpoint.get("receipt_fence")
    if isinstance(fence, int) and epoch != fence:
        return stopped(durable, "stale_controller_epoch", available=False, resumable=False)
    try:
        lease_end = parse_timestamp(valid_until)
    except Exception:
        return stopped(durable, "unreadable_lease", available=False, resumable=False)
    if now > lease_end:
        # Nothing owns the run any more. Report the durable instant exactly: the time the last
        # checkpoint actually covered, never the lease it might still have had left.
        return stopped(durable, "lease_expired")

    elapsed = (min(now, lease_end) - anchor).total_seconds()
    if elapsed < 0:
        return stopped(durable, "operational_clock_reversed", available=False, resumable=False)
    return ReplayProjection(
        running=True,
        speed=speed,
        simulated_at=format_timestamp(simulated + timedelta(seconds=elapsed * speed)),
        available=True,
        resumable=True,
        last_request_id=last_request_id,
        position=position,
        mode=mode,
    )
