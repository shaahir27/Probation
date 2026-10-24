"""Bounded role orchestration with injected capabilities, Clock and stop signal.

Callers supply role functions and explicitly provisioned snapshot closures. This
module holds no credentials, opens no accounts and constructs no live providers.
"""

import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event

from probation.core.clock import Clock, timestamp_key, use_clock
from probation.core.lifecycle import LifecycleError

Step = Callable[[sqlite3.Connection, str, int], int]


@dataclass(frozen=True, slots=True)
class RoleConnections:
    resolver: sqlite3.Connection
    examiner: sqlite3.Connection
    executor: sqlite3.Connection
    brain: sqlite3.Connection

    def all(self) -> tuple[sqlite3.Connection, ...]:
        return self.resolver, self.examiner, self.executor, self.brain


@dataclass(frozen=True, slots=True)
class WorkerSteps:
    resolver: Step
    examiner: Step
    consume: Step
    effects: Step
    followups: Step | None = None


@dataclass(frozen=True, slots=True)
class TickResult:
    as_of: str
    counts: dict[str, int] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    stopped: bool = False


class LifecycleCoordinator:
    def __init__(
        self,
        connections: RoleConnections,
        steps: WorkerSteps,
        *,
        clock: Clock,
        batch_size: int = 32,
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("Positive worker batch size required")
        if len({id(conn) for conn in connections.all()}) != 4:
            raise ValueError("Workers require separate role connections")
        for role, conn in zip(
            ("resolver", "examiner", "executor", "brain"), connections.all(), strict=True
        ):
            if getattr(conn, "bound_role", None) != role:
                raise ValueError("Workers require permanently bound role connections")
        self.connections = connections
        self.steps = steps
        self.clock = clock
        self.batch_size = batch_size
        self._last_cut: str | None = None

    def tick(self, stop: Event) -> TickResult:
        now = self.clock.now_iso()
        counts: dict[str, int] = {}
        if self._last_cut is not None and timestamp_key(now) < timestamp_key(self._last_cut):
            return TickResult(now, counts, ("clock:inconsistent_clock",))
        self._last_cut = now
        stages: list[tuple[str, sqlite3.Connection, Step | None]] = [
            ("resolver", self.connections.resolver, self.steps.resolver),
            ("examiner", self.connections.examiner, self.steps.examiner),
            ("consume", self.connections.executor, self.steps.consume),
            ("effects", self.connections.executor, self.steps.effects),
            ("examiner_after", self.connections.examiner, self.steps.examiner),
            ("followups", self.connections.brain, self.steps.followups),
        ]
        with use_clock(self.clock):
            for name, conn, step in stages:
                if stop.is_set():
                    return TickResult(now, counts, stopped=True)
                if step is None:
                    counts[name] = 0  # Missing snapshots leave durable follow-up work pending.
                    continue
                try:
                    if conn.in_transaction:
                        return TickResult(now, counts, (f"{name}:uncommitted_worker_state",))
                    count = step(conn, now, self.batch_size)
                    if type(count) is not int or count < 0 or conn.in_transaction:
                        return TickResult(now, counts, (f"{name}:invalid_worker_result",))
                    counts[name] = count
                except LifecycleError as exc:
                    return TickResult(now, counts, (f"{name}:{exc.code}",))
                except (sqlite3.Error, ValueError, TypeError):
                    return TickResult(now, counts, (f"{name}:worker_failed",))
        return TickResult(now, counts)

    def run(
        self,
        stop: Event,
        *,
        poll_seconds: float = 1.0,
        max_ticks: int | None = None,
        on_result: Callable[[TickResult], None] | None = None,
    ) -> int:
        """Wait at most one second; an Event interrupts waiting and later stages."""
        if not math.isfinite(poll_seconds) or not 0 < poll_seconds <= 1:
            raise ValueError("Polling interval must be in (0,1] seconds")
        if max_ticks is not None and (type(max_ticks) is not int or max_ticks < 0):
            raise ValueError("Nonnegative tick count required")
        completed = 0
        while not stop.is_set() and (max_ticks is None or completed < max_ticks):
            result = self.tick(stop)
            completed += 1
            if on_result is not None:
                on_result(result)
            if max_ticks is not None and completed >= max_ticks:
                break
            if stop.wait(poll_seconds):
                break
        return completed
