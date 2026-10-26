"""Concrete bounded role loops used by the local Gmail runtime."""

import hashlib
import json
import logging
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock

from probation.config import settings
from probation.core.clock import Clock, elapsed_seconds, timestamp_key, use_clock
from probation.core.history import HistoryView
from probation.core.replay_controls import replay_run_id
from probation.core.types import Features, Situation
from probation.db.access import Role, RoleAccess
from probation.workers.admin import process_admin_commands
from probation.workers.d5_ipc import ByteChannel, serve_one
from probation.workers.d5_verification import WebObservation
from probation.workers.drift import review_outcome_events
from probation.workers.replay_controller import ReplayController
from probation.workers.replay_lock import ReplayLock
from probation.workers.response_resolver import resolve_responses
from probation.workers.restrictions import process_restriction_commands

logger = logging.getLogger(__name__)

_POLL_SECONDS = 1.0
_BATCH_SIZE = 32

#: A role's readiness ages out: one completed stage proves liveness only for this long.
WORK_STALENESS_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class WorkEvidence:
    """One role's own proof of work: the stages that completed, and when."""

    at: str
    stages: tuple[str, ...] = ()
    failure: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None and bool(self.stages)


@dataclass(frozen=True, slots=True)
class RoleWorkState:
    """What supervision can assert about one role: fresh, stale, failed, or never seen."""

    ready: bool
    code: str | None = None


class WorkLedger:
    """Thread-safe record of each role's most recent completed work, optionally exported.

    The ``sink`` is how a child role hands its own proof of work to the supervisor: one
    length-free JSON line per recorded tick on a channel the parent drains. Nothing here is
    trusted as readiness until it is fresh, and absence is reported as absent.
    """

    def __init__(self, sink: Callable[[str, WorkEvidence], None] | None = None) -> None:
        self._lock = Lock()
        self._latest: dict[str, WorkEvidence] = {}
        self._sink = sink

    def record(self, role: str, evidence: WorkEvidence) -> None:
        with self._lock:
            self._latest[role] = evidence
            sink = self._sink
        if sink is not None:
            try:
                sink(role, evidence)
            except OSError:
                # Losing a status line must never stop a role from doing its work, and must
                # never be mistaken for readiness: the parent sees no fresh line and reports
                # the role unavailable.
                logger.warning("role_status_export_failed", extra={"role": role})

    def success(self, role: str, at: str, stages: tuple[str, ...]) -> None:
        self.record(role, WorkEvidence(at=at, stages=stages))

    def failure(self, role: str, at: str, code: str) -> None:
        logger.warning("role_tick_failed", extra={"role": role, "code": code})
        self.record(role, WorkEvidence(at=at, failure=code))

    def evidence(self, role: str) -> WorkEvidence | None:
        with self._lock:
            return self._latest.get(role)

    def state_from(self, evidence: WorkEvidence | None, now_iso: str) -> RoleWorkState:
        """Absence of evidence is not readiness: it is reported as unavailable."""
        if evidence is None:
            return RoleWorkState(False, "work_status_absent")
        if evidence.failure is not None:
            return RoleWorkState(False, f"work_tick_failed_{evidence.failure}")
        if not is_work_fresh(evidence, now_iso):
            return RoleWorkState(False, "work_status_stale")
        return RoleWorkState(True)

    def state(self, role: str, now_iso: str) -> RoleWorkState:
        return self.state_from(self.evidence(role), now_iso)


WORK_STATUS_PREFIX = "runtime_work "


def encode_work_status(role: str, evidence: WorkEvidence) -> str:
    """One JSON line per tick: bounded, typed and free of any message body or credential."""
    return json.dumps(
        {
            "role": role,
            "at": evidence.at,
            "stages": list(evidence.stages)[:32],
            "failure": evidence.failure,
        },
        separators=(",", ":"),
    )


def decode_work_status(line: str) -> tuple[str, WorkEvidence] | None:
    """Parse one exported status line. Anything malformed is ignored, never trusted."""
    if not line.startswith(WORK_STATUS_PREFIX):
        return None
    try:
        value = json.loads(line.removeprefix(WORK_STATUS_PREFIX))
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    role, at = value.get("role"), value.get("at")
    stages = value.get("stages")
    failure = value.get("failure")
    if not isinstance(role, str) or not isinstance(at, str) or not isinstance(stages, list):
        return None
    if not all(isinstance(stage, str) for stage in stages):
        return None
    if failure is not None and not isinstance(failure, str):
        return None
    return role, WorkEvidence(at=at, stages=tuple(stages), failure=failure)


def write_work_status(stream: object, role: str, evidence: WorkEvidence) -> None:
    """Emit one status line; the parent's reader is the only thing that consumes it."""
    write = getattr(stream, "write", None)
    if write is None:
        raise OSError("status stream is unwritable")
    write(f"{WORK_STATUS_PREFIX}{encode_work_status(role, evidence)}\n".encode())
    flush = getattr(stream, "flush", None)
    if flush is not None:
        flush()


def is_work_fresh(evidence: WorkEvidence, now_iso: str) -> bool:
    """A real processing stage completed at or before ``now_iso`` inside the staleness window."""
    if not evidence.succeeded:
        return False
    try:
        age = timestamp_key(now_iso) - timestamp_key(evidence.at)
    except (ValueError, OverflowError):
        return False
    return 0 <= age <= WORK_STALENESS_SECONDS * 1_000_000


def run_resolver(
    conn: sqlite3.Connection, *, clock: Clock, stop: Event, work: WorkLedger | None = None
) -> int:
    """Drain only explicit owner responses through the existing Resolver-owned processor."""
    ticks = 0
    while not stop.is_set():
        if conn.in_transaction:
            return ticks
        at = clock.now_iso()
        try:
            resolve_responses(conn, as_of=at, limit=_BATCH_SIZE)
        except (sqlite3.Error, OSError, ValueError) as exc:
            if work is not None:
                work.failure("resolver", at, type(exc).__name__)
            raise
        ticks += 1
        if work is not None:
            work.success("resolver", clock.now_iso(), ("owner_responses",))
        if stop.wait(_POLL_SECONDS):
            break
    return ticks


def replay_controller_for_owner(
    conn: sqlite3.Connection, *, owner_id: str | None
) -> ReplayController | None:
    """Create replay control only when the trusted supervisor provisioned an owner identity."""
    if not owner_id or not owner_id.strip() or len(owner_id) > 256:
        return None
    target = str(settings.db_path.resolve())
    workspace_id = hashlib.sha256(f"{owner_id}\0{target}".encode()).hexdigest()[:24]
    return ReplayController(
        RoleAccess(conn, Role.EXAMINER),
        workspace_id=workspace_id,
        # One run identity, derived the same way the API derives its scope: a controller that
        # looked under a different run could advance replay the owner is not watching.
        run_id=replay_run_id(owner_id, target),
        controller_id="examiner",
    )


def run_api_server() -> int:
    """Serve the existing FastAPI application on loopback only."""
    import uvicorn

    try:
        port = int(os.environ.get("PROBATION_API_PORT", "8000"))
    except ValueError as exc:
        raise ValueError("invalid_api_port") from exc
    if not 1 <= port <= 65_535:
        raise ValueError("invalid_api_port")
    uvicorn.run("probation.api.app:app", host="127.0.0.1", port=port, reload=False)
    return 0


def run_examiner(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    stop: Event,
    replay_controller: ReplayController | None = None,
    lock_path: Path | None = None,
    operational_clock: Clock | None = None,
    work: WorkLedger | None = None,
) -> int:
    """Review outcomes, restrictions, admin requests, and durable replay commands.

    ``operational_clock`` is injectable so a test can assert real elapsed-time behaviour without
    sleeping; omitting it keeps the existing live operational clock the role runs against.
    """
    replay_lock = ReplayLock(lock_path) if replay_controller and lock_path else None
    if replay_lock is not None:
        try:
            if not replay_lock.acquire():
                replay_controller = None
        except OSError:
            replay_controller = None
    ticks = 0
    operational = operational_clock if operational_clock is not None else Clock.live()
    previous_elapsed = elapsed_seconds()
    try:
        while not stop.is_set():
            simulated_at = clock.now_iso()
            operational_at = operational.now_iso()
            if conn.in_transaction:
                break
            try:
                review_outcome_events(conn, as_of=simulated_at)
                process_restriction_commands(conn, as_of=operational_at, limit=_BATCH_SIZE)
                process_admin_commands(conn, clock=clock)
                stages: tuple[str, ...] = ("outcome_review", "restrictions", "admin")
                if replay_controller is not None:
                    replay_controller.process_pending(
                        operational_at=operational_at,
                        initial_simulated_at=simulated_at,
                        limit=_BATCH_SIZE,
                    )
                    current = elapsed_seconds()
                    replay_controller.advance(
                        elapsed_seconds=max(0.0, current - previous_elapsed),
                        operational_at=operational.now_iso(),
                    )
                    previous_elapsed = current
                    stages = (*stages, "durable_replay")
            except (sqlite3.Error, OSError, ValueError) as exc:
                if work is not None:
                    work.failure("examiner", simulated_at, type(exc).__name__)
                raise
            ticks += 1
            if work is not None:
                work.success("examiner", simulated_at, stages)
            if stop.wait(_POLL_SECONDS):
                break
    finally:
        if replay_controller is not None:
            replay_controller.pause_and_finish(operational.now_iso())
        if replay_lock is not None:
            replay_lock.release()
    return ticks


def run_webfacts(
    conn: sqlite3.Connection,
    *,
    channel: ByteChannel,
    clock: Clock,
    stop: Event,
    semantic_identity: Callable[[], str],
    verify: Callable[[Situation, Features, HistoryView], WebObservation],
    work: WorkLedger | None = None,
) -> int:
    """Handle one bounded Brain request at a time in the Webfacts-owned process.

    A refused request is answered with a typed unavailable reply and the loop keeps serving;
    only a framing or transport failure ends it.
    """
    ticks = 0
    while not stop.is_set():
        if not channel.poll(_POLL_SECONDS):
            continue
        with use_clock(clock):
            served = serve_one(
                channel,
                conn=conn,
                clock=clock,
                semantic_identity=semantic_identity,
                verify=verify,
            )
        if not served:
            if work is not None:
                work.failure("webfacts", clock.now_iso(), "ipc_transport_closed")
            break
        ticks += 1
        if work is not None:
            work.success("webfacts", clock.now_iso(), ("brain_ipc",))
    return ticks


def email_webfacts_verifier(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    allow_live_llm: bool,
    allow_live_tavily: bool,
) -> Callable[[Situation, Features, HistoryView], WebObservation]:
    """Build D5's existing verifier with a Webfacts-owned accounting/client role."""
    from probation.config import settings
    from probation.llm.client import LLMClient
    from probation.llm.consumers import RegisteredConsumer
    from probation.llm.gateway import JobGateway, transport_authority
    from probation.web.client import TavilyClient
    from probation.workers.d5_verification import email_verifier

    if not allow_live_tavily:
        return lambda *_args, **_kwargs: WebObservation(
            cap=0, reasons=("webfacts_live_lookup_disabled",)
        )
    consumer = None
    if settings.llm_api_key and allow_live_llm:
        from probation.db.spend import SpendStore, default_lease_owner

        client = LLMClient(
            api_key=settings.llm_api_key,
            clock=clock,
            spend_store=SpendStore(
                conn,
                role=Role.WEBFACTS.value,
                lease_owner=default_lease_owner(Role.WEBFACTS.value),
            ),
        )
        consumer = RegisteredConsumer(
            JobGateway(client, conn=conn),
            transport_authority(client, allow_live_dispatch=True),
        )
    return email_verifier(
        conn,
        client=TavilyClient(conn=conn),
        consumer=consumer,
        clock=clock,
    )
