"""Bounded Gmail verification and proposal work owned by the Brain role."""

import json
import logging
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Event

from probation.core.clock import Clock
from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.engine.prediction import PredictionSnapshot
from probation.engine.runtime_snapshot import build_runtime_snapshot
from probation.llm.consumers import RegisteredConsumer, offline_consumer
from probation.llm.feature_identity import semantic_feature_version
from probation.workers.brain import build_reader_client
from probation.workers.brain_followups import process_followups
from probation.workers.d5_ipc import BrainWebFactsClient, make_verifier
from probation.workers.d5_verification import (
    Verifier,
    WebObservation,
    persist_verified_email,
    predict_verified_email,
)
from probation.workers.gmail_role_loops import WorkLedger

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 32
_FOLLOWUP_LIMIT = 32
_FAMILY = "email_action"

#: Bounded read-only cohort facts. Any change here can change the fit, so the snapshot is
#: rebuilt; nothing else justifies refitting the embedding model on every tick.
_COHORT_FINGERPRINT_SQL = """
SELECT
  (SELECT COUNT(*) FROM situations s JOIN raw_items r ON r.id = s.raw_item_id
     WHERE s.pack = 'mail' AND s.family = ?
       AND s.occurred_at COLLATE UTC_TIMESTAMP <= ? AND r.known_at COLLATE UTC_TIMESTAMP <= ?),
  (SELECT COUNT(*) FROM features f WHERE f.created_at COLLATE UTC_TIMESTAMP <= ?),
  (SELECT COALESCE(MAX(l.seq), 0) FROM ledger l
     WHERE l.kind IN ('outcome', 'drift_alarm')
       AND l.created_at COLLATE UTC_TIMESTAMP <= ?)
"""


@dataclass(frozen=True, slots=True)
class BrainTick:
    """One bounded Brain pass: what completed, what refused, and which stages really ran."""

    processed: int = 0
    followups: int = 0
    failures: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failures


class _CohortSnapshots:
    """Reuse one fitted snapshot across ticks; rebuild only when the cohort changed or restarted."""

    def __init__(self, family: str = _FAMILY) -> None:
        self._family = family
        self._fingerprint: tuple[object, ...] | None = None
        self._snapshot: PredictionSnapshot | None = None

    def get(self, conn: sqlite3.Connection, cutoff: str) -> PredictionSnapshot:
        fingerprint = _cohort_fingerprint(conn, self._family, cutoff)
        if self._snapshot is None or fingerprint != self._fingerprint:
            self._snapshot = build_runtime_snapshot(conn, self._family, cutoff)
            self._fingerprint = fingerprint
        return self._snapshot


def _cohort_fingerprint(conn: sqlite3.Connection, family: str, cutoff: str) -> tuple[object, ...]:
    row = conn.execute(_COHORT_FINGERPRINT_SQL, (family, cutoff, cutoff, cutoff, cutoff)).fetchone()
    values = tuple(row) if row is not None else ()
    return (*values, semantic_feature_version())


def webfacts_verifier(
    webfacts: BrainWebFactsClient | None,
    semantic_identity: str,
) -> Verifier:
    """Fail closed when verification is unavailable: an unchecked message is restricted, never free.

    A missing or unavailable Webfacts channel must not claim "no restriction"; the cap-0 shape is
    the same one the sibling paths already use, so the gate can only land on SHADOW or ASK.
    """
    if webfacts is None:
        return _unavailable_webfacts
    return make_verifier(webfacts, semantic_identity)


def _unavailable_webfacts(*_args: object, **_kwargs: object) -> WebObservation:
    return WebObservation(cap=0, reasons=("webfacts_role_unavailable",))


def _consumer(conn: sqlite3.Connection, clock: Clock, *, allow_live: bool) -> RegisteredConsumer:
    client = build_reader_client(clock, allow_live, conn)
    if client is None:
        return offline_consumer(conn)
    from probation.llm.gateway import JobGateway, transport_authority

    return RegisteredConsumer(
        JobGateway(client, conn=conn),
        transport_authority(client, allow_live_dispatch=allow_live),
    )


def process_pending_mail(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    consumer: RegisteredConsumer | None = None,
    webfacts: BrainWebFactsClient | None = None,
    allow_live_llm: bool = False,
    limit: int = _BATCH_LIMIT,
    snapshots: _CohortSnapshots | None = None,
) -> BrainTick:
    """Process at most 32 eligible incoming Gmail situations, then the bounded follow-up batch."""
    if conn.in_transaction:
        raise ValueError("Brain processing requires a clean connection")
    if not 1 <= limit <= _BATCH_LIMIT:
        raise ValueError("Invalid Gmail Brain batch size")
    cutoff = clock.now_iso()
    history = HistoryView(conn, cutoff)
    situations = history.pending_gmail_situations(limit)
    reader = consumer or _consumer(conn, clock, allow_live=allow_live_llm)
    cache = snapshots if snapshots is not None else _CohortSnapshots()
    snapshot = cache.get(conn, cutoff)
    verify = webfacts_verifier(webfacts, semantic_feature_version())
    failures: list[str] = []
    processed = 0
    for row in situations:
        situation = Situation.model_validate(dict(row))
        raw = history.get_raw_item(situation.raw_item_id)
        if raw is None:
            continue
        try:
            payload = json.loads(str(raw["payload_json"]))
            if not isinstance(payload, dict) or payload.get("is_sent") is True:
                continue
            result = predict_verified_email(
                conn,
                situation,
                snapshot,
                clock=clock,
                verify=verify,
                licence_level=0,
                consumer=reader,
            )
            persist_verified_email(conn, situation, snapshot, result, clock=clock, consumer=reader)
        except Exception as exc:  # one situation must not stop the batch, but never goes unheard
            failures.append(f"verification:{type(exc).__name__}")
            logger.warning(
                "brain_situation_failed",
                extra={"situation_id": situation.id, "error": type(exc).__name__},
            )
            continue
        processed += 1
    followups, followup_failures = _run_followups(
        conn, cutoff=cutoff, snapshot=snapshot, reader=reader
    )
    return BrainTick(
        processed=processed,
        followups=followups,
        failures=(*failures, *followup_failures),
        stages=("gmail_verification", "authority_followups"),
    )


def _run_followups(
    conn: sqlite3.Connection,
    *,
    cutoff: str,
    snapshot: PredictionSnapshot,
    reader: RegisteredConsumer,
) -> tuple[int, tuple[str, ...]]:
    """Fresh Brain-owned predictions for cancelled authority, on the same batch discipline."""
    if conn.in_transaction:
        return 0, ("followups:uncommitted_connection",)
    snapshots: Mapping[str, PredictionSnapshot] = {_FAMILY: snapshot}
    try:
        saved = process_followups(
            conn,
            as_of=cutoff,
            snapshots=snapshots,
            consumer=reader,
            limit=_FOLLOWUP_LIMIT,
        )
    except Exception as exc:  # a follow-up failure leaves the request pending, never silent
        logger.warning("brain_followups_failed", extra={"error": type(exc).__name__})
        return 0, (f"followups:{type(exc).__name__}",)
    return len(saved), ()


def run_brain(
    conn: sqlite3.Connection,
    *,
    clock: Clock,
    stop: Event,
    webfacts: BrainWebFactsClient | None = None,
    allow_live_llm: bool = False,
    poll_seconds: float = 1.0,
    work: WorkLedger | None = None,
) -> int:
    """Tick until stopped; a failed batch is never counted as a successful tick."""
    if not 0 < poll_seconds <= 1:
        raise ValueError("Brain polling interval must be at most one second")
    ticks = 0
    consumer = _consumer(conn, clock, allow_live=allow_live_llm)
    snapshots = _CohortSnapshots()
    while not stop.is_set():
        at = clock.now_iso()
        try:
            tick = process_pending_mail(
                conn,
                clock=clock,
                consumer=consumer,
                webfacts=webfacts,
                snapshots=snapshots,
            )
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            # A failed fit or provider dependency leaves the cohort pending and says so.
            if work is not None:
                work.failure("brain", at, type(exc).__name__)
            if stop.wait(poll_seconds):
                break
            continue
        if tick.ok:
            ticks += 1
            if work is not None:
                work.success("brain", at, tick.stages)
        elif work is not None:
            work.failure("brain", at, tick.failures[0].split(":", 1)[-1])
        if stop.wait(poll_seconds):
            break
    return ticks
