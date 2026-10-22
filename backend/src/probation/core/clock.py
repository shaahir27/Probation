"""Clock abstraction for deterministic replay and live execution.

Authority: docs/CONTRACT.md invariant I-9.
All system time queries MUST go through this module.
Direct calls to datetime.now() or time.time() outside this module are forbidden.
"""

import math
import re
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, tzinfo
from functools import lru_cache

from probation.core.enums import ClockMode


class ClockError(ValueError):
    """An invalid/backwards time cannot authorize an action."""


def parse_timestamp(value: str | datetime) -> datetime:
    """Interpret legacy naive inputs as UTC; normalize every aware input to UTC."""
    if isinstance(value, str) and re.search(r"\.\d{7,}", value):
        raise ClockError("Timestamp precision exceeds the supported microsecond boundary")
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def format_timestamp(value: str | datetime) -> str:
    """UTC Z form, preserving all supplied microseconds and legacy whole-second form."""
    parsed = parse_timestamp(value)
    precision = "microseconds" if parsed.microsecond else "seconds"
    return parsed.isoformat(timespec=precision).replace("+00:00", "Z")


@lru_cache(maxsize=8192)
def timestamp_key(value: str) -> int:
    """Exact integer instant for comparisons; no floating point precision is lost."""
    delta = parse_timestamp(value) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def configure_clock_collation(conn: sqlite3.Connection) -> None:
    """Compare old/new ISO spellings as instants without changing ledger/data bytes."""

    def compare(left: str, right: str) -> int:
        first, second = timestamp_key(left), timestamp_key(right)
        return (first > second) - (first < second)

    conn.create_collation("UTC_TIMESTAMP", compare)


def elapsed_seconds() -> float:
    """Wall-duration instrumentation only; never a replay/event timestamp."""
    return time.perf_counter()


class Clock:
    """Monotonic timekeeper supporting settable replay mode and live system time."""

    def __init__(self, mode: ClockMode | None = None, initial_time: datetime | None = None) -> None:
        if mode is None:
            try:
                from probation.config import settings

                self.mode = (
                    ClockMode.LIVE
                    if getattr(settings, "clock_mode", "replay") == "live"
                    else ClockMode.REPLAY
                )
            except Exception:
                self.mode = ClockMode.REPLAY
        else:
            self.mode = mode

        if initial_time is not None:
            self._current_time: datetime = parse_timestamp(initial_time)
        else:
            self._current_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        self._last_read: datetime | None = None

    @classmethod
    def live(cls) -> "Clock":
        """Convenience factory returning a Clock in LIVE mode."""
        return cls(mode=ClockMode.LIVE)

    @classmethod
    def replay(cls, initial_time: datetime | None = None) -> "Clock":
        """Convenience factory returning a Clock in REPLAY mode."""
        return cls(mode=ClockMode.REPLAY, initial_time=initial_time)

    def now(self, tz: tzinfo | None = None) -> datetime:
        """Return the current clock time as a datetime (UTC by default or converted to tz)."""
        dt = datetime.now(UTC) if self.mode == ClockMode.LIVE else self._current_time
        if self.mode == ClockMode.LIVE:
            if self._last_read is not None and dt < self._last_read:
                raise ClockError("Live clock moved backwards")
            self._last_read = dt
        if tz is not None:
            return dt.astimezone(tz)
        return dt

    def now_iso(self) -> str:
        """Return current time as an ISO-8601 UTC string ending in 'Z'."""
        dt = self.now()
        return format_timestamp(dt)

    def set_time(self, new_time: datetime) -> None:
        """Advance the simulated replay time. Replay time must be monotonic."""
        if self.mode != ClockMode.REPLAY:
            raise RuntimeError("Cannot manually set clock time in live mode.")
        utc_time = parse_timestamp(new_time)
        if utc_time < self._current_time:
            raise ValueError(
                f"Clock time cannot move backwards in replay mode: {utc_time} < {self._current_time}"
            )
        self._current_time = utc_time

    def advance_seconds(self, seconds: float) -> None:
        """Advance simulated replay time by specified seconds."""
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Cannot advance clock by negative seconds.")
        if self.mode != ClockMode.REPLAY:
            raise RuntimeError("Cannot manually advance clock time in live mode.")
        from datetime import timedelta

        self._current_time += timedelta(seconds=seconds)


_context_clock: ContextVar[Clock | None] = ContextVar("probation_clock", default=None)
_default_clock: Clock | None = None


def get_clock() -> Clock:
    """Return the current runtime clock, shared by all roles in that context.

    Application entry points install their replay/live clock with ``use_clock``.
    Standalone commands share a process clock rather than inventing a new horizon
    in each repository, client or endpoint.
    """
    current = _context_clock.get()
    if current is not None:
        return current
    global _default_clock
    if _default_clock is None:
        _default_clock = Clock()
    return _default_clock


@contextmanager
def use_clock(clock: Clock) -> Generator[Clock]:
    """Scope an injected clock and restore its parent even after a failure."""
    token = _context_clock.set(clock)
    try:
        yield clock
    finally:
        _context_clock.reset(token)
