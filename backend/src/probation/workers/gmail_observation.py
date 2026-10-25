"""Bounded, restartable Gmail observation loop for exactly one connection.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 4-7; docs/OCT29_DEMO_BUILD_PLAN.md 10.1;
docs/CONTRACT.md section 3 (ingestor: only the source, read-only). Drives the existing
``GmailSync`` engine (no sync/commit/fencing logic duplicated), reuses ``workers/restrictions.py``
as its only control path (paused/revoked/non-observing: no dispatch, no cursor advance; disconnect
stops the loop), waits are interruptible and clock-driven, and the worker holds only a read-role
provider plus a GET-only transport — structurally unable to dispatch, hence retry, any effect.
Every tick also reads the sync engine's public resync markers, so an attempt in progress, a failed
attempt and the last completed attempt are visible to an operator as safe facts, never "degraded"
with no explanation.
"""

import json
import math
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from threading import Event
from typing import Final, Literal, Protocol, cast

from probation.connectors.credentials_state import SecretMaterial
from probation.connectors.readiness import (
    ConnectionReadiness,
    ReadinessSignals,
    ResyncFreshness,
    evaluate_readiness,
)
from probation.connectors.types import (
    CapabilityManifest,
    CapabilityName,
    CapabilityState,
    ConnectionState,
    ConnectorError,
    CredentialRole,
    CursorRejected,
    HistoryStale,
    HttpResult,
    HttpTransport,
    ProviderUnavailable,
    SourceSelection,
    TransportFailure,
)
from probation.core.clock import Clock, timestamp_key, use_clock
from probation.core.enums import ClockMode
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.gmail_auth import GMAIL_READONLY_SCOPE
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_sync import POLL_INTERVAL_SECONDS, GmailSync, SyncResult
from probation.packs.mail.connectors.gmail_sync_state import (
    RESYNC_STATUS_UNAVAILABLE,
    resync_freshness,
)
from probation.workers.restrictions import ExecutionRestrictions

_WAIT_CHUNK_SECONDS: Final = 0.25
_MAX_BACKOFF_SECONDS: Final = 30.0
_RETRYABLE_STATUSES: Final = frozenset({429, 500, 502, 503, 504})
_AUTH_STATUSES: Final = frozenset({401, 403})
_OBSERVING_STATES: Final = frozenset({"AUTHORIZED", "BACKFILLING", "SHADOW", "ACTIVE"})
_LEASE_HELD: Final = "lease_held_by_active_worker"
_JOB_KEY: Final = "sync:cohort"
_READ_OWNED: Final[tuple[CapabilityName, ...]] = ("read", "attribution")
_EMPTY_MANIFEST: Final = CapabilityManifest(provider="gmail", provider_version="v1", states=())

_UPSERT_READ_CAPABILITY = """INSERT INTO gmail_capabilities
 (connection_id,account_id,name,owner_role,supported,evidence,reason,manifest_version,verified_at)
 VALUES(?,?,?,'read',?,?,?,?,?)
 ON CONFLICT(connection_id,name,owner_role) DO UPDATE SET
  supported=excluded.supported,evidence=excluded.evidence,reason=excluded.reason,
  manifest_version=excluded.manifest_version,verified_at=excluded.verified_at
 WHERE excluded.manifest_version>=gmail_capabilities.manifest_version
  AND excluded.account_id=gmail_capabilities.account_id"""


class AuthorizationFailed(ProviderUnavailable):
    """The provider refused authorization: halt the loop, degrade readiness, never spin."""


class ReadTransport(Protocol):
    """GET-only seam. A POST cannot be named here, so no effect can be dispatched or retried."""

    def get(
        self, url: str, *, params: "dict[str, object] | None" = None, access_token: str
    ) -> HttpResult: ...


class ReadGrantProvider(Protocol):
    """Read-role credential surface only: role plus access resolution, nothing writable."""

    @property
    def role(self) -> CredentialRole: ...

    def resolve_access(
        self, capability: str, required_scopes: Sequence[str] = ()
    ) -> SecretMaterial: ...


def clock_wait(clock: Clock, seconds: float, stop: Event) -> bool:
    """Interruptible, clock-driven wait; never ``time.sleep`` on wall time. Replay advances the
    injected clock in bounded chunks; live waits on the stop Event until its clock-derived deadline.
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise ConnectorError("invalid_wait_interval")
    if seconds == 0:
        return stop.is_set()
    if clock.mode == ClockMode.REPLAY:
        remaining = seconds
        while remaining > 0 and not stop.is_set():
            clock.advance_seconds(min(_WAIT_CHUNK_SECONDS, remaining))
            remaining -= _WAIT_CHUNK_SECONDS
        return stop.is_set()
    deadline = timestamp_key(clock.now_iso()) + int(seconds * 1_000_000)
    while not stop.is_set():
        remaining = (deadline - timestamp_key(clock.now_iso())) / 1_000_000
        if remaining <= 0:
            return False
        if stop.wait(min(_WAIT_CHUNK_SECONDS, remaining)):
            return True
    return True


class RetryingReadTransport:
    """Bounded exponential backoff for safe GET reads only, honouring ``Retry-After``. No ``post``
    method exists, so an effectful request can neither be dispatched nor retried from here; 401/403
    raise ``AuthorizationFailed`` at once, halting the loop instead of spinning.
    """

    def __init__(
        self, inner: ReadTransport, clock: Clock, stop: Event, max_attempts: int = 3
    ) -> None:
        if max_attempts < 1:
            raise ConnectorError("invalid_retry_budget")
        self._inner, self._clock, self._stop = inner, clock, stop
        self._max_attempts, self._base = max_attempts, 0.5

    def get(
        self, url: str, *, params: "dict[str, object] | None" = None, access_token: str
    ) -> HttpResult:
        attempts = 0
        while True:
            try:
                result = self._inner.get(url, params=params, access_token=access_token)
            except TransportFailure as exc:
                # A safe GET that never reached the provider is retryable; an effectful POST
                # can never come through this seam.
                attempts += 1
                if attempts >= self._max_attempts:
                    raise ProviderUnavailable("read_retries_exhausted_transport") from exc
                if self._stop.is_set():
                    raise ProviderUnavailable("read_aborted_before_retry") from exc
                clock_wait(
                    self._clock,
                    min(self._base * (2 ** (attempts - 1)), _MAX_BACKOFF_SECONDS),
                    self._stop,
                )
                continue
            if result.status in _AUTH_STATUSES:
                raise AuthorizationFailed(f"provider_status_{result.status}")
            if result.ok or result.status not in _RETRYABLE_STATUSES:
                return result
            attempts += 1
            if attempts >= self._max_attempts:
                raise ProviderUnavailable(f"read_retries_exhausted_{result.status}")
            if self._stop.is_set():
                raise ProviderUnavailable("read_aborted_before_retry")
            delay = result.retry_after_seconds
            if delay is None:
                delay = self._base * (2 ** (attempts - 1))
            clock_wait(self._clock, max(0.0, min(delay, _MAX_BACKOFF_SECONDS)), self._stop)


@dataclass(frozen=True)
class ObservationTickResult:
    """One loop iteration, safe to log: actions, codes, counts and resync facts — never content."""

    action: Literal["observed", "blocked", "backoff", "degraded", "halted", "stopped"]
    safe_reason: str | None = None
    observations_written: int = 0
    committed_history_id: int = 0
    wait_seconds: float = POLL_INTERVAL_SECONDS
    readiness: ConnectionReadiness | None = None
    resync: ResyncFreshness = field(default_factory=ResyncFreshness)

    @property
    def stops_loop(self) -> bool:
        return self.action in ("stopped", "halted")


class GmailObservationWorker:
    """Lease, claim, sync via ``GmailSync``, persist progress, release — restartably."""

    def __init__(
        self,
        *,
        connection_id: str,
        owner: str,
        ingest: ConnectorAccess,
        capabilities: ConnectorAccess | None,
        credentials: ReadGrantProvider,
        transport: ReadTransport,
        clock: Clock,
        restrictions: Callable[[str], ExecutionRestrictions],
        poll_seconds: float = POLL_INTERVAL_SECONDS,
        page_size: int = 50,
        max_attempts: int = 3,
        readiness_version: int = 1,
        on_tick: Callable[[ObservationTickResult], None] | None = None,
    ) -> None:
        if ingest.authority != "ingestor":
            raise ConnectorError("worker_needs_ingestor_authority")
        if capabilities is not None and capabilities.authority != "read_worker":
            raise ConnectorError("readiness_rows_need_read_worker_authority")
        if credentials.role != "read":
            # Structural: a write provider is rejected at construction, before this process can
            # ever touch a transport, the store or an effect.
            raise ConnectorError("worker_requires_read_only_grant")
        if not math.isfinite(poll_seconds) or not 0 < poll_seconds <= 3600:
            raise ConnectorError("invalid_poll_interval")
        if page_size < 1 or page_size > 250 or readiness_version < 1:
            raise ConnectorError("invalid_worker_budget")
        self._connection_id, self._owner = connection_id, owner
        self._ingest, self._capabilities = ingest, capabilities
        self._credentials, self._transport = credentials, transport
        self._clock, self._restrictions = clock, restrictions
        self._poll_seconds, self._page_size = poll_seconds, page_size
        self._max_attempts, self._readiness_version = max_attempts, readiness_version
        self._on_tick = on_tick

    def tick(self, stop: Event) -> ObservationTickResult:
        with use_clock(self._clock):
            return self._tick(stop)

    def run(
        self,
        stop: Event,
        *,
        max_ticks: int | None = None,
        on_result: Callable[[ObservationTickResult], None] | None = None,
    ) -> int:
        """Poll at the clock-driven interval; a stop Event or a disconnect/halt ends the run."""
        ticks = 0
        while not stop.is_set() and (max_ticks is None or ticks < max_ticks):
            result = self.tick(stop)
            ticks += 1
            if on_result is not None:
                on_result(result)
            if self._on_tick is not None:
                self._on_tick(result)
            if result.stops_loop or (max_ticks is not None and ticks >= max_ticks):
                break
            if clock_wait(self._clock, result.wait_seconds, stop):
                break
        return ticks

    def _tick(self, stop: Event) -> ObservationTickResult:
        now = self._clock.now_iso()
        row = self._ingest.one(
            "SELECT account_id,state,selection_revision,label_ids FROM gmail_connections"
            " WHERE connection_id=?",
            (self._connection_id,),
        )
        if row is None:
            return ObservationTickResult("blocked", "connection_absent")
        state = str(row["state"])
        if state == "DISCONNECTED":
            # Disconnect stops observation entirely: no dispatch, no claim, no cursor advance.
            return ObservationTickResult("stopped", "connection_disconnected")
        if state not in _OBSERVING_STATES:
            return ObservationTickResult("blocked", f"connection_state_{state.lower()}")
        blocked = self._control_block(now)
        if blocked is not None:
            return blocked
        try:
            selection = self._selection(row)
        except (ConnectorError, ValueError, TypeError):
            return ObservationTickResult("degraded", "invalid_connection_selection")
        cursor_before = self._cursor_row(selection.selection_revision)
        try:
            token = self._credentials.resolve_access("read", (GMAIL_READONLY_SCOPE,))
        except ConnectorError as exc:
            return self._halt(f"credential_{exc.safe_code}", selection)
        retry = RetryingReadTransport(self._transport, self._clock, stop, self._max_attempts)
        connector, sync = self._engine(retry, selection, token.reveal())
        return self._drive(sync, connector, selection, cursor_before, state)

    def _halt(
        self,
        reason: str,
        selection: SourceSelection,
        resync: ResyncFreshness | None = None,
    ) -> ObservationTickResult:
        view = ResyncFreshness() if resync is None else resync
        readiness = self._assess(
            "AUTH_REQUIRED", selection, _EMPTY_MANIFEST, False, False, True, resync_freshness=view
        )
        self._persist(readiness, selection.account_id)
        return ObservationTickResult("halted", reason, readiness=readiness, resync=view)

    def _control_block(self, now: str) -> ObservationTickResult | None:
        try:  # the one control path: pending or completed pause/revoke blocks before any effect
            restrictions = self._restrictions(now)
        except Exception:  # any control-plane doubt fails closed
            restrictions = ExecutionRestrictions("unavailable", True, True)
        if restrictions.revoked:
            return ObservationTickResult("blocked", "control_revoked")
        if restrictions.paused:
            return ObservationTickResult("blocked", "control_paused")
        return None

    def _engine(
        self, retry: RetryingReadTransport, selection: SourceSelection, token: str
    ) -> tuple[GmailReadConnector, GmailSync]:
        label = _first_label(selection)
        connector = GmailReadConnector(
            cast(HttpTransport, retry),
            connection_id=self._connection_id,
            account_id=selection.account_id,
            access_token=token,
            clock=self._clock,
            owner_label=label,
        )
        return connector, GmailSync(
            access=self._ingest,
            connector=connector,
            clock=self._clock,
            connection_id=self._connection_id,
            account_id=selection.account_id,
            owner_label=label,
        )

    def _drive(
        self,
        sync: GmailSync,
        connector: GmailReadConnector,
        selection: SourceSelection,
        cursor_before: sqlite3.Row | None,
        state: str,
    ) -> ObservationTickResult:
        outcome: SyncResult | None = None
        reason: str | None = None
        resync = False
        step = sync.incremental if _mode(cursor_before) else sync.bootstrap
        try:
            outcome = step(selection, owner=self._owner, page_size=self._page_size)
        except CursorRejected as exc:
            if exc.safe_code == _LEASE_HELD:
                # The loser of a lease race returns before any provider dispatch; nothing written.
                return ObservationTickResult("backoff", exc.safe_code)
            resync = isinstance(exc, HistoryStale) or exc.safe_code == "resync_required"
            reason = exc.safe_code
        except AuthorizationFailed as exc:
            return self._halt(exc.safe_code, selection, self._resync_view(sync, selection))
        except ProviderUnavailable as exc:
            resync, reason = exc.safe_code == "provider_status_404", exc.safe_code
        view = self._resync_view(sync, selection)
        if outcome is not None:
            self._release()
            resync = outcome.resync_required
        gap = bool(
            outcome is not None
            and cursor_before is not None
            and int(str(cursor_before["catchup_complete"])) == 0
            and int(str(cursor_before["committed_history_id"])) > 0
        )
        manifest = connector.capabilities()
        readiness = self._assess(state, selection, manifest, resync, gap, resync_freshness=view)
        self._persist(readiness, selection.account_id)
        if outcome is None:
            return ObservationTickResult("degraded", reason, readiness=readiness, resync=view)
        if view.in_progress:
            # An unfinished attempt (live or crashed) means the watermark was never replaced:
            # observations may have been written, but dependence is held until it completes.
            return ObservationTickResult(
                "degraded",
                "resync_in_progress",
                observations_written=outcome.observations_written,
                committed_history_id=outcome.committed_history_id,
                readiness=readiness,
                resync=view,
            )
        action: Literal["observed", "degraded"] = "degraded" if resync else "observed"
        return ObservationTickResult(
            action,
            "resync_required" if resync else None,
            observations_written=outcome.observations_written,
            committed_history_id=outcome.committed_history_id,
            readiness=readiness,
            resync=view,
        )

    def _resync_view(self, sync: GmailSync, selection: SourceSelection) -> ResyncFreshness:
        """Resync attempt state from the engine's public marker API only.

        Unreadable marker state fails closed: it is never proof that no resync is pending.
        """
        try:
            return resync_freshness(sync.resync_markers(selection))
        except Exception:  # any doubt about resync history holds dependence, never permits it
            return ResyncFreshness(in_progress=True, last_failure_code=RESYNC_STATUS_UNAVAILABLE)

    def _selection(self, row: sqlite3.Row) -> SourceSelection:
        labels = json.loads(str(row["label_ids"]))
        if not isinstance(labels, list):
            raise ConnectorError("invalid_connection_labels")
        account = str(row["account_id"])
        revision = int(row["selection_revision"])
        return SourceSelection(
            connection_id=self._connection_id,
            account_id=account,
            selection_revision=revision,
            label_ids=tuple(str(label) for label in labels),
        )

    def _cursor_row(self, filter_revision: int) -> sqlite3.Row | None:
        return self._ingest.one(
            "SELECT committed_history_id,bootstrap_history_id,catchup_complete,watermark_at"
            " FROM gmail_sync_cursors WHERE connection_id=? AND resource_key='cohort'"
            " AND role='read' AND filter_revision=?",
            (self._connection_id, filter_revision),
        )

    def _write_states(self, account_id: str) -> tuple[CapabilityState, ...]:
        rows = self._ingest.query(
            "SELECT name,supported,evidence,reason,verified_at FROM gmail_capabilities"
            " WHERE connection_id=? AND account_id=? AND owner_role='write'",
            (self._connection_id, account_id),
        )
        return tuple(
            CapabilityState(
                name=str(row["name"]),  # type: ignore[arg-type]
                supported=bool(row["supported"]),
                verified_at=str(row["verified_at"]),
                evidence=str(row["evidence"]),
                reason=None if row["reason"] is None else str(row["reason"]),
            )
            for row in rows
        )

    def _release(self) -> None:
        """Return the lease by advancing its fence: the store forbids a same-fence update."""
        held = self._ingest.one(
            "SELECT owner FROM gmail_worker_leases WHERE connection_id=? AND job_key=?",
            (self._connection_id, _JOB_KEY),
        )
        if held is None or str(held["owner"]) != self._owner:
            return  # a takeover already fenced us out; releasing would destroy the new lease
        self._ingest.write(
            "gmail_worker_leases",
            "UPDATE gmail_worker_leases SET fence=fence+1, expires_at=?"
            " WHERE connection_id=? AND job_key=?",
            (self._clock.now_iso(), self._connection_id, _JOB_KEY),
        )

    def _assess(
        self,
        state: str,
        selection: SourceSelection,
        manifest: CapabilityManifest,
        resync: bool,
        gap: bool,
        auth: bool = False,
        *,
        resync_freshness: ResyncFreshness | None = None,
    ) -> ConnectionReadiness:
        row = self._cursor_row(selection.selection_revision)
        watermark = None if row is None else row["watermark_at"]
        committed = 0 if row is None else int(str(row["committed_history_id"]))
        complete = False if row is None else bool(int(str(row["catchup_complete"])))
        signals = ReadinessSignals(
            connection_state=cast(ConnectionState, state),
            authorization_failed=auth,
            resync_required=resync,
            cursor_gap=gap,
        )
        now = self._clock.now_iso()
        return evaluate_readiness(
            connection_id=self._connection_id,
            manifest=manifest,
            write_states=self._write_states(selection.account_id),
            signals=signals,
            now=now,
            watermark_at=None if watermark is None else str(watermark),
            committed_history_id=committed,
            catchup_complete=complete,
            resync=resync_freshness,
        )

    def _persist(self, readiness: ConnectionReadiness, account_id: str) -> None:
        """Sync committed progress inside its own transaction; this is the readiness ack."""
        if self._capabilities is None or not account_id:
            return
        for name in sorted(_READ_OWNED):
            item = readiness.state(name)
            if item is None:
                continue
            flag = 1 if item.supported else 0
            reason = None if item.supported else item.reason
            head = (self._connection_id, account_id, item.name, flag, item.evidence, reason)
            tail = (self._readiness_version, item.verified_at)
            self._capabilities.write("gmail_capabilities", _UPSERT_READ_CAPABILITY, head + tail)


def _mode(cursor_row: sqlite3.Row | None) -> bool:
    """True only when a committed, complete bootstrap may be continued incrementally."""
    if cursor_row is None or cursor_row["bootstrap_history_id"] is None:
        return False
    return int(str(cursor_row["catchup_complete"])) == 1


def _first_label(selection: SourceSelection) -> str | None:
    return selection.label_ids[0] if selection.label_ids else None
