"""Clock abstraction for deterministic replay and live execution.

Authority: docs/CONTRACT.md invariant I-9.
All system time queries MUST go through this module.
Direct calls to datetime.now() or time.time() outside this module are forbidden.
"""

from datetime import UTC, datetime

from probation.core.enums import ClockMode


class Clock:
    """Monotonic timekeeper supporting settable replay mode and live system time."""

    def __init__(
        self, mode: ClockMode = ClockMode.REPLAY, initial_time: datetime | None = None
    ) -> None:
        self.mode = mode
        if initial_time is not None:
            self._current_time: datetime = (
                initial_time if initial_time.tzinfo else initial_time.replace(tzinfo=UTC)
            )
        else:
            self._current_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        """Return the current clock time as a UTC datetime."""
        if self.mode == ClockMode.LIVE:
            return datetime.now(UTC)
        return self._current_time

    def now_iso(self) -> str:
        """Return current time as an ISO-8601 UTC string ending in 'Z'."""
        dt = self.now()
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def set_time(self, new_time: datetime) -> None:
        """Advance the simulated replay time. Replay time must be monotonic."""
        if self.mode != ClockMode.REPLAY:
            raise RuntimeError("Cannot manually set clock time in live mode.")
        utc_time = new_time if new_time.tzinfo else new_time.replace(tzinfo=UTC)
        if utc_time < self._current_time:
            raise ValueError(
                f"Clock time cannot move backwards in replay mode: {utc_time} < {self._current_time}"
            )
        self._current_time = utc_time

    def advance_seconds(self, seconds: float) -> None:
        """Advance simulated replay time by specified seconds."""
        if seconds < 0:
            raise ValueError("Cannot advance clock by negative seconds.")
        if self.mode != ClockMode.REPLAY:
            raise RuntimeError("Cannot manually advance clock time in live mode.")
        from datetime import timedelta

        self._current_time += timedelta(seconds=seconds)
