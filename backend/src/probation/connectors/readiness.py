"""Versioned, truthful capability/readiness results for one Gmail connection. Pure: no I/O.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 4, 5 and 7; docs/OCT29_DEMO_BUILD_PLAN.md
section 10.1. The truth rules this module enforces: a connection badge is never proof of sending or
undo readiness; ``conditional_write`` is unsupported for Gmail (C1, ``modify`` has no precondition);
``undo_history_proof`` stays unverified or unsupported whenever the anchor is unresolved, outside
the retained history window, or separated from the watermark by a cursor gap (C2/C3); an
observation gap, a resync or a stale source-freshness signal blocks dependent autonomy; and every
input — provider status, manifests, grants — may only lower a verdict, never raise one. A resync is
published as a clock time, an in-progress flag and one safe code, so an operator can see freshness
recover without any resync ever raising authority. Payloads carry hashes and safe codes only: never
a raw account identifier, token or message content.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from probation.connectors.types import (
    CapabilityManifest,
    CapabilityName,
    CapabilityState,
    ConnectionState,
    ConnectorError,
)
from probation.core.clock import timestamp_key

READINESS_VERSION: Final = 1
DEFAULT_FRESHNESS_MAX_AGE_SECONDS: Final = 120.0

_OBSERVING_STATES: Final[frozenset[str]] = frozenset(
    {"AUTHORIZED", "BACKFILLING", "SHADOW", "ACTIVE"}
)
_UNSAFE_STATES: Final[frozenset[str]] = frozenset(
    {"UNCONFIGURED", "AUTHORIZING", "PAUSED", "DEGRADED", "AUTH_REQUIRED", "DISCONNECTED"}
)
_REQUIRED_NAMES: Final[tuple[CapabilityName, ...]] = (
    "read",
    "archive",
    "trash",
    "send",
    "reconciliation",
    "undo_history_proof",
    "conditional_write",
    "attribution",
)
_WRITE_OWNED_NAMES: Final[frozenset[str]] = frozenset(
    {"archive", "trash", "send", "reconciliation", "undo_history_proof", "conditional_write"}
)

_C1_REASON: Final = "modify_has_no_precondition_c1"
_C9_REASON: Final = "history_has_no_actor_identity_c9"
_ROW_ABSENT: Final = "capability_row_absent"
_MAX_SAFE_CODE_LENGTH: Final = 64
_UNRECOGNIZED_RESYNC_CODE: Final = "unrecognized_resync_code"
_SAFE_CODE_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class SyncFreshness:
    """Source-freshness of the durable watermark. Absent or aged watermarks are stale.

    The resync fields are attempt metadata and can only hold a clock time and a safe code: a
    completed attempt is never proof of sending, undo readiness or any other authority.
    """

    committed_history_id: int
    watermark_at: str | None
    catchup_complete: bool
    resync_required: bool
    cursor_gap: bool
    age_seconds: float | None
    stale: bool
    fresh: bool
    last_successful_resync_at: str | None
    resync_in_progress: bool
    last_resync_failure_code: str | None


@dataclass(frozen=True)
class ResyncFreshness:
    """Safe facts about the last recorded resync attempts.

    An attempt that started and never reached a terminal state (live or crashed) counts as in
    progress; only a later completed attempt clears that. The failure code is the last failed
    attempt's, and is cleared once a completed attempt supersedes it. Every other value collapses
    to one opaque token, so no account id, message id, label or payload text can ride along.
    """

    in_progress: bool = False
    last_successful_at: str | None = None
    last_failure_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "last_successful_at", _published_time(self.last_successful_at))
        object.__setattr__(self, "last_failure_code", _safe_resync_code(self.last_failure_code))


@dataclass(frozen=True)
class ReadinessSignals:
    """Safe control-plane facts for one assessment. Every signal can only lower readiness."""

    connection_state: ConnectionState
    paused: bool = False
    revoked: bool = False
    authorization_failed: bool = False
    write_grant_failed: bool = False
    resync_required: bool = False
    cursor_gap: bool = False
    anchor_history_id: int | None = None
    retained_from: int | None = None
    undo_evidence_continuous: bool = False

    def __post_init__(self) -> None:
        if self.connection_state not in _OBSERVING_STATES | _UNSAFE_STATES:
            raise ConnectorError("invalid_connection_state")
        for column in ("anchor_history_id", "retained_from"):
            value = getattr(self, column)
            if value is not None and value < 0:
                raise ConnectorError("invalid_history_id")


@dataclass(frozen=True)
class ConnectionReadiness:
    """One versioned readiness result. Identifiers appear only as opaque reference hashes."""

    version: int
    connection_ref_hash: str
    states: tuple[CapabilityState, ...]
    freshness: SyncFreshness
    blocking_reason: str | None
    observation_allowed: bool
    dependent_autonomy_permitted: bool

    def __post_init__(self) -> None:
        if self.version != READINESS_VERSION:
            raise ConnectorError("readiness_version_mismatch")
        if not self.connection_ref_hash.startswith("sha256:"):
            raise ConnectorError("readiness_needs_hashed_reference")
        missing = [name for name in _REQUIRED_NAMES if self.state(name) is None]
        if missing:
            raise ConnectorError("readiness_incomplete")

    def state(self, name: CapabilityName) -> CapabilityState | None:
        for state in self.states:
            if state.name == name:
                return state
        return None

    def supports(self, name: CapabilityName) -> bool:
        state = self.state(name)
        return bool(state and state.supported)

    def reason_for(self, name: CapabilityName) -> str | None:
        state = self.state(name)
        return None if state is None else state.reason


def connection_ref_hash(connection_id: str) -> str:
    """The only publishable form of a connection identifier: a salted one-way hash."""
    if not connection_id or any(ord(char) < 32 for char in connection_id):
        raise ConnectorError("invalid_connection_reference")
    digest = hashlib.sha256(f"gmail-connection:{connection_id}".encode()).hexdigest()
    return f"sha256:{digest[:32]}"


def evaluate_readiness(
    *,
    connection_id: str,
    manifest: CapabilityManifest,
    write_states: Sequence[CapabilityState],
    signals: ReadinessSignals,
    now: str,
    watermark_at: str | None,
    committed_history_id: int,
    catchup_complete: bool,
    resync: ResyncFreshness | None = None,
    freshness_max_age_seconds: float = DEFAULT_FRESHNESS_MAX_AGE_SECONDS,
) -> ConnectionReadiness:
    """Compose one truthful readiness result from provider truth and safe control signals."""
    if freshness_max_age_seconds <= 0:
        raise ConnectorError("invalid_freshness_horizon")
    resync_state = ResyncFreshness() if resync is None else resync
    by_name: dict[CapabilityName, CapabilityState] = {
        state.name: state for state in manifest.states
    }
    for state in write_states:
        if state.name in _WRITE_OWNED_NAMES:  # only Executor-owned rows can speak for writes
            by_name[state.name] = state
    age_seconds = _watermark_age(now, watermark_at)
    stale = age_seconds is None or age_seconds > freshness_max_age_seconds
    fresh = bool(
        not stale
        and catchup_complete
        and not signals.resync_required
        and not signals.cursor_gap
        and not resync_state.in_progress
    )
    observing = signals.connection_state in _OBSERVING_STATES
    states = tuple(
        _assess_state(
            name,
            by_name=by_name,
            provider=manifest.provider,
            signals=signals,
            fresh=fresh,
            observing=observing,
            resync=resync_state,
            now=now,
        )
        for name in _REQUIRED_NAMES
    )
    freshness = SyncFreshness(
        committed_history_id=committed_history_id,
        watermark_at=watermark_at,
        catchup_complete=catchup_complete,
        resync_required=signals.resync_required,
        cursor_gap=signals.cursor_gap,
        age_seconds=age_seconds,
        stale=stale,
        fresh=fresh,
        last_successful_resync_at=resync_state.last_successful_at,
        resync_in_progress=resync_state.in_progress,
        last_resync_failure_code=resync_state.last_failure_code,
    )
    blocked = _blocking_reason(
        signals,
        observing=observing,
        stale=stale,
        gap=signals.cursor_gap,
        resync_in_progress=resync_state.in_progress,
    )
    return ConnectionReadiness(
        version=READINESS_VERSION,
        connection_ref_hash=connection_ref_hash(connection_id),
        states=states,
        freshness=freshness,
        blocking_reason=blocked,
        observation_allowed=bool(observing and not signals.paused and not signals.revoked),
        dependent_autonomy_permitted=bool(
            fresh
            and observing
            and not signals.paused
            and not signals.revoked
            and not signals.authorization_failed
            and not signals.write_grant_failed
        ),
    )


def _assess_state(
    name: CapabilityName,
    *,
    by_name: dict[CapabilityName, CapabilityState],
    provider: str,
    signals: ReadinessSignals,
    fresh: bool,
    observing: bool,
    resync: ResyncFreshness,
    now: str,
) -> CapabilityState:
    base = by_name.get(name)
    if name == "conditional_write":
        # C1 is a provider fact: no Gmail result, badge or local lock may raise this verdict.
        return _fail(name, _C1_REASON, now, evidence="unsupported")
    if name == "attribution":
        if provider == "gmail":  # C9: history records carry no actor identity.
            return _fail(name, _C9_REASON, now, evidence="unsupported")
        return _pass_through(name, base, now)
    if name == "read":
        if signals.connection_state == "DISCONNECTED":
            return _fail(name, "connection_disconnected", now)
        if signals.authorization_failed:
            return _fail(name, "authorization_denied", now)
        if not observing:
            return _fail(name, "connection_state_blocks_observation", now)
        return _pass_through(name, base, now)
    if name == "undo_history_proof":
        return _assess_undo(base, signals=signals, fresh=fresh, resync=resync, now=now)
    if signals.write_grant_failed:
        # A failed write grant degrades write readiness explicitly, never silently.
        return _fail(name, "write_grant_unavailable", now)
    if name == "reconciliation" and not fresh:
        return _fail(name, "source_freshness_blocks_dependence", now, evidence="unverified")
    return _pass_through(name, base, now)


def _assess_undo(
    base: CapabilityState | None,
    *,
    signals: ReadinessSignals,
    fresh: bool,
    resync: ResyncFreshness,
    now: str,
) -> CapabilityState:
    if signals.cursor_gap:
        return _fail("undo_history_proof", "cursor_gap_blocks_undo_proof", now)
    if resync.in_progress:
        return _fail("undo_history_proof", "resync_in_progress_blocks_undo_proof", now)
    if signals.resync_required:
        return _fail("undo_history_proof", "resync_blocks_undo_proof", now)
    if signals.anchor_history_id is None:
        return _fail(
            "undo_history_proof", "undo_history_anchor_unresolved", now, evidence="unverified"
        )
    if signals.retained_from is not None and signals.anchor_history_id < signals.retained_from:
        return _fail(
            "undo_history_proof",
            "undo_history_anchor_outside_retained_window",
            now,
            evidence="unverified",
        )
    if not signals.undo_evidence_continuous:
        return _fail(
            "undo_history_proof", "undo_evidence_not_continuous", now, evidence="unverified"
        )
    if not fresh:
        return _fail("undo_history_proof", "source_freshness_stale", now)
    if signals.write_grant_failed:
        return _fail("undo_history_proof", "write_grant_unavailable", now)
    return _pass_through("undo_history_proof", base, now)


def _pass_through(name: CapabilityName, base: CapabilityState | None, now: str) -> CapabilityState:
    if base is None:
        return _fail(name, _ROW_ABSENT, now)
    if not base.supported:
        return _fail(name, base.reason or _ROW_ABSENT, now, evidence=base.evidence)
    return base


def _fail(
    name: CapabilityName, reason: str, now: str, *, evidence: str = "unsupported"
) -> CapabilityState:
    return CapabilityState(
        name=name, supported=False, verified_at=now, evidence=evidence, reason=reason
    )


def _watermark_age(now: str, watermark_at: str | None) -> float | None:
    """Age in seconds from injected-clock values only. Absent or backwards marks are unusable."""
    if watermark_at is None:
        return None
    delta = (timestamp_key(now) - timestamp_key(watermark_at)) / 1_000_000
    return delta if delta >= 0 else None


def _published_time(value: str | None) -> str | None:
    """Only a parseable clock instant proves a completed resync; anything else stays absent."""
    if value is None:
        return None
    try:
        timestamp_key(value)
    except (TypeError, ValueError):
        return None
    return value


def _safe_resync_code(code: str | None) -> str | None:
    """Keep allow-shaped codes (``provider_status_404``); collapse everything else to one token."""
    if code is None:
        return None
    lowered = code.strip().lower()
    if len(lowered) <= _MAX_SAFE_CODE_LENGTH and _SAFE_CODE_PATTERN.fullmatch(lowered):
        return lowered
    return _UNRECOGNIZED_RESYNC_CODE


def _blocking_reason(
    signals: ReadinessSignals,
    *,
    observing: bool,
    stale: bool,
    gap: bool,
    resync_in_progress: bool,
) -> str | None:
    """The single safest reason the loop must hold dependent work, in fail-closed priority order."""
    checks: tuple[tuple[bool, str], ...] = (
        (signals.connection_state == "DISCONNECTED", "connection_disconnected"),
        (signals.revoked, "control_revoked"),
        (signals.paused, "control_paused"),
        (signals.authorization_failed, "authorization_denied"),
        (resync_in_progress, "resync_in_progress"),
        (signals.resync_required, "resync_required"),
        (gap, "observation_gap"),
        (stale, "source_freshness_stale"),
        (not observing, "connection_state_blocks_observation"),
        (signals.write_grant_failed, "write_grant_unavailable"),
    )
    for triggered, reason in checks:
        if triggered:
            return reason
    return None


__all__ = [
    "DEFAULT_FRESHNESS_MAX_AGE_SECONDS",
    "READINESS_VERSION",
    "ConnectionReadiness",
    "ReadinessSignals",
    "ResyncFreshness",
    "SyncFreshness",
    "connection_ref_hash",
    "evaluate_readiness",
]
