"""Short-lived server-side owner session for the local dashboard.

The owner key is verified once by the API, then exchanged for an opaque random session id.
Only an HttpOnly cookie carries that id; the key itself is never stored in the browser and
never written to this store. Sessions expire after a fixed idle period and are renewed only
by an authenticated request.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Final

from probation.core.clock import Clock

SESSION_COOKIE: Final = "probation_owner_session"
SESSION_IDLE_SECONDS: Final = 1800
SESSION_COOKIE_PATH: Final = "/api"


@dataclass(frozen=True, slots=True)
class OwnerSessionRecord:
    owner_id: str
    expires_at: datetime
    email: str | None = None


class OwnerSessionManager:
    """Process-local session ids. A restart asks the owner to sign in again."""

    def __init__(self, *, clock: Clock, idle_seconds: int = SESSION_IDLE_SECONDS) -> None:
        if not 60 <= idle_seconds <= 86_400:
            raise ValueError("owner session idle must be between one minute and one day")
        self._clock = clock
        self._idle = timedelta(seconds=idle_seconds)
        self._sessions: dict[str, OwnerSessionRecord] = {}
        self._lock = Lock()

    def create(self, owner_id: str, *, email: str | None = None) -> tuple[str, OwnerSessionRecord]:
        if not owner_id.strip():
            raise ValueError("owner session needs an owner id")
        now = self._clock.now(UTC)
        token = secrets.token_urlsafe(32)
        record = OwnerSessionRecord(owner_id=owner_id, expires_at=now + self._idle, email=email)
        with self._lock:
            self._sessions[token] = record
        return token, record

    def resolve(self, token: str | None) -> OwnerSessionRecord | None:
        if not token:
            return None
        now = self._clock.now(UTC)
        with self._lock:
            record = self._sessions.get(token)
            if record is None:
                return None
            if record.expires_at <= now:
                self._sessions.pop(token, None)
                return None
            renewed = OwnerSessionRecord(
                owner_id=record.owner_id, expires_at=now + self._idle, email=record.email
            )
            self._sessions[token] = renewed
            return renewed

    def delete(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def remaining_seconds(self, record: OwnerSessionRecord) -> int:
        remaining = (record.expires_at - self._clock.now(UTC)).total_seconds()
        return max(0, int(remaining))

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
