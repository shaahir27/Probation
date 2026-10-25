"""Truthfulness rules for versioned readiness results. Pure module: no store, no transport.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 4, 5 and 9; docs/OCT29_DEMO_BUILD_PLAN.md
section 10.1 ("a connection badge is not proof of sending or undo readiness"). These lock the
contract rules: conditional write is never supported for Gmail (C1), attribution is unknown (C9),
undo proof fails closed outside the retained history window or across a cursor gap, gaps/resyncs/
stale freshness block dependent autonomy, write-grant failure degrades writes but never observation,
a resync is published as a time, an in-progress flag and one safe code, and payloads carry hashes
and safe codes only.
"""

import pytest

from probation.connectors.readiness import (
    DEFAULT_FRESHNESS_MAX_AGE_SECONDS,
    READINESS_VERSION,
    ReadinessSignals,
    ResyncFreshness,
    connection_ref_hash,
    evaluate_readiness,
)
from probation.connectors.types import CapabilityManifest, CapabilityState, ConnectorError

NOW = "2026-10-24T09:00:00Z"
WATERMARK = "2026-10-24T08:59:30Z"
CONNECTION = "conn-secret-1"

_ALL_NAMES = (
    "read",
    "archive",
    "trash",
    "send",
    "reconciliation",
    "undo_history_proof",
    "conditional_write",
    "attribution",
)


def _state(
    name: str, supported: bool, *, evidence: str = "supported", reason: str | None = None
) -> CapabilityState:
    return CapabilityState(
        name=name,  # type: ignore[arg-type]
        supported=supported,
        verified_at=NOW,
        evidence=evidence,
        reason=reason,
    )


def _manifest(*extra: CapabilityState) -> CapabilityManifest:
    # Mirrors GmailReadConnector.capabilities(): the truthful read-side rows, nothing more.
    return CapabilityManifest(
        provider="gmail",
        provider_version="v1",
        states=(
            _state("read", True),
            _state("undo_history_proof", True, reason="window_bounded_history_about_one_week"),
            _state("reconciliation", True),
            _state(
                "conditional_write",
                False,
                evidence="unsupported",
                reason="modify_has_no_precondition_c1",
            ),
            *extra,
        ),
        granted_scopes=("gmail.readonly",),
    )


def _write_rows() -> tuple[CapabilityState, ...]:
    return tuple(
        _state(name, True)
        for name in ("archive", "trash", "send", "reconciliation", "undo_history_proof")
    )


def _evaluate(
    *,
    manifest: CapabilityManifest | None = None,
    write_states: tuple[CapabilityState, ...] | None = None,
    signals: ReadinessSignals | None = None,
    watermark: str | None = WATERMARK,
    catchup: bool = True,
    max_age: float = DEFAULT_FRESHNESS_MAX_AGE_SECONDS,
    resync: ResyncFreshness | None = None,
) -> object:
    return evaluate_readiness(
        connection_id=CONNECTION,
        manifest=manifest if manifest is not None else _manifest(),
        write_states=write_states if write_states is not None else _write_rows(),
        signals=signals
        if signals is not None
        else ReadinessSignals(
            connection_state="ACTIVE",
            anchor_history_id=9,
            retained_from=5,
            undo_evidence_continuous=True,
        ),
        now=NOW,
        watermark_at=watermark,
        committed_history_id=12,
        catchup_complete=catchup,
        resync=resync,
        freshness_max_age_seconds=max_age,
    )


def test_clean_result_carries_every_required_name_and_version() -> None:
    readiness = _evaluate()
    assert readiness.version == READINESS_VERSION
    assert {state.name for state in readiness.states} == set(_ALL_NAMES)
    assert readiness.supports("read")
    assert readiness.supports("send")
    assert readiness.freshness.fresh is True
    assert readiness.blocking_reason is None
    assert readiness.observation_allowed is True
    assert readiness.dependent_autonomy_permitted is True


def test_conditional_write_is_never_supported_for_gmail() -> None:
    # Even a manifest that (falsely) claims provider compare-and-set cannot raise this verdict.
    readiness = _evaluate(manifest=_manifest(_state("conditional_write", True)))
    state = readiness.state("conditional_write")
    assert state is not None and not state.supported
    assert state.reason == "modify_has_no_precondition_c1"


def test_attribution_never_raised_for_gmail() -> None:
    readiness = _evaluate(manifest=_manifest(_state("attribution", True)))
    state = readiness.state("attribution")
    assert state is not None and not state.supported
    assert state.reason == "history_has_no_actor_identity_c9"


def test_connection_badge_is_not_proof_of_sending() -> None:
    # An ACTIVE connection with no Executor-owned write rows reports send absent, never granted.
    readiness = _evaluate(write_states=())
    assert readiness.supports("send") is False
    assert readiness.supports("read") is True
    state = readiness.state("send")
    assert state is not None and state.reason == "capability_row_absent"


def test_failed_write_grant_degrades_writes_and_keeps_observation() -> None:
    signals = ReadinessSignals(
        connection_state="AUTHORIZED",
        write_grant_failed=True,
        anchor_history_id=9,
        retained_from=5,
        undo_evidence_continuous=True,
    )
    readiness = _evaluate(signals=signals)
    assert readiness.supports("read") is True
    assert readiness.observation_allowed is True
    assert readiness.supports("send") is False
    assert readiness.state("send").reason == "write_grant_unavailable"  # type: ignore[union-attr]
    assert readiness.supports("archive") is False
    assert readiness.dependent_autonomy_permitted is False
    assert readiness.blocking_reason == "write_grant_unavailable"


def test_read_failure_degrades_observation_not_write_verdicts() -> None:
    # The opposite direction: an authorization failure stops reads; stored write verdicts stand.
    signals = ReadinessSignals(
        connection_state="ACTIVE",
        authorization_failed=True,
        anchor_history_id=9,
        retained_from=5,
        undo_evidence_continuous=True,
    )
    readiness = _evaluate(signals=signals)
    assert readiness.supports("read") is False
    assert readiness.state("read").reason == "authorization_denied"  # type: ignore[union-attr]
    assert readiness.supports("send") is True
    assert readiness.blocking_reason == "authorization_denied"


def test_undo_proof_unverified_when_anchor_outside_retained_window() -> None:
    signals = ReadinessSignals(
        connection_state="ACTIVE",
        anchor_history_id=4,
        retained_from=10,
        undo_evidence_continuous=True,
    )
    state = _evaluate(signals=signals).state("undo_history_proof")
    assert state is not None and not state.supported
    assert state.evidence == "unverified"
    assert state.reason == "undo_history_anchor_outside_retained_window"


def test_undo_proof_unsupported_across_a_cursor_gap() -> None:
    signals = ReadinessSignals(connection_state="ACTIVE", cursor_gap=True)
    readiness = _evaluate(signals=signals)
    state = readiness.state("undo_history_proof")
    assert state is not None and not state.supported
    assert state.reason == "cursor_gap_blocks_undo_proof"
    assert readiness.blocking_reason == "observation_gap"
    assert readiness.dependent_autonomy_permitted is False


def test_resync_blocks_dependent_autonomy_not_observation() -> None:
    signals = ReadinessSignals(connection_state="ACTIVE", resync_required=True)
    readiness = _evaluate(signals=signals)
    assert readiness.supports("read") is True
    assert readiness.freshness.fresh is False
    assert readiness.blocking_reason == "resync_required"
    assert readiness.state("undo_history_proof").reason == "resync_blocks_undo_proof"  # type: ignore[union-attr]
    assert readiness.state("reconciliation").reason == "source_freshness_blocks_dependence"  # type: ignore[union-attr]
    assert readiness.dependent_autonomy_permitted is False


def test_stale_source_freshness_blocks_dependent_autonomy() -> None:
    readiness = _evaluate(watermark="2026-10-24T08:00:00Z", max_age=120.0)
    assert readiness.freshness.stale is True
    assert readiness.blocking_reason == "source_freshness_stale"
    assert readiness.dependent_autonomy_permitted is False
    assert readiness.state("reconciliation").evidence == "unverified"  # type: ignore[union-attr]


def test_missing_watermark_is_stale_not_assumed_fresh() -> None:
    readiness = _evaluate(watermark=None)
    assert readiness.freshness.age_seconds is None
    assert readiness.freshness.fresh is False


def test_disconnected_stops_observation_and_revocation_outranks_pause() -> None:
    disconnected = _evaluate(
        signals=ReadinessSignals(connection_state="DISCONNECTED", revoked=True, paused=True)
    )
    assert disconnected.observation_allowed is False
    assert disconnected.state("read").reason == "connection_disconnected"  # type: ignore[union-attr]
    assert disconnected.blocking_reason == "connection_disconnected"
    both = _evaluate(signals=ReadinessSignals(connection_state="PAUSED", revoked=True, paused=True))
    assert both.blocking_reason == "control_revoked"
    paused = _evaluate(signals=ReadinessSignals(connection_state="ACTIVE", paused=True))
    assert paused.blocking_reason == "control_paused"
    assert paused.observation_allowed is False


def test_readiness_payload_carries_only_hashes_and_safe_codes() -> None:
    readiness = _evaluate()
    rendered = str(readiness) + repr(readiness.states)
    assert CONNECTION not in rendered
    assert readiness.connection_ref_hash != CONNECTION
    assert readiness.connection_ref_hash.startswith("sha256:")
    assert connection_ref_hash(CONNECTION) == readiness.connection_ref_hash
    assert connection_ref_hash("other-conn") != readiness.connection_ref_hash


def test_invalid_inputs_are_typed_failures() -> None:
    with pytest.raises(ConnectorError):
        ReadinessSignals(connection_state="NOT_A_STATE")  # type: ignore[arg-type]
    with pytest.raises(ConnectorError):
        ReadinessSignals(connection_state="ACTIVE", anchor_history_id=-1)
    with pytest.raises(ConnectorError):
        connection_ref_hash("")
    with pytest.raises(ConnectorError):
        _evaluate(max_age=0.0)


def test_absent_write_rows_never_invented_from_provider_status() -> None:
    # Manifest claims only read-side rows; archive/trash/undo fall to absent, never inferred.
    readiness = _evaluate(write_states=(_state("archive", True),))
    assert readiness.supports("archive") is True
    assert readiness.state("trash").supported is False  # type: ignore[union-attr]
    assert readiness.state("trash").reason == "capability_row_absent"  # type: ignore[union-attr]


# -- resync visibility ----------------------------------------------------------------------------
def test_readiness_reports_resync_in_progress() -> None:
    resync = ResyncFreshness(in_progress=True, last_successful_at="2026-10-24T08:00:00Z")
    readiness = _evaluate(resync=resync)
    assert readiness.freshness.resync_in_progress is True
    assert readiness.freshness.fresh is False
    assert readiness.freshness.last_successful_resync_at == "2026-10-24T08:00:00Z"
    assert readiness.blocking_reason == "resync_in_progress"
    assert readiness.dependent_autonomy_permitted is False
    assert readiness.supports("read") is True  # observation itself is never revoked by a resync
    assert readiness.observation_allowed is True
    undo = readiness.state("undo_history_proof")
    assert undo is not None and not undo.supported
    assert undo.reason == "resync_in_progress_blocks_undo_proof"


def test_readiness_reports_last_successful_resync_time() -> None:
    completed = "2026-10-24T08:59:10Z"
    readiness = _evaluate(resync=ResyncFreshness(last_successful_at=completed))
    assert readiness.freshness.last_successful_resync_at == completed
    assert readiness.freshness.resync_in_progress is False
    assert readiness.freshness.last_resync_failure_code is None
    # Recorded truthfully, but the resync time never raises the freshness verdict itself.
    assert readiness.freshness.fresh is True
    assert readiness.blocking_reason is None


def test_readiness_reports_failed_resync_safe_code() -> None:
    signals = ReadinessSignals(connection_state="ACTIVE", resync_required=True)
    resync = ResyncFreshness(last_failure_code="provider_status_404")
    readiness = _evaluate(signals=signals, resync=resync)
    assert readiness.freshness.last_resync_failure_code == "provider_status_404"
    assert readiness.freshness.resync_in_progress is False
    assert readiness.blocking_reason == "resync_required"
    assert readiness.dependent_autonomy_permitted is False
    assert readiness.supports("read") is True


def test_resync_readiness_payload_contains_no_identifiers() -> None:
    hostile = f"{CONNECTION}:m-42/COHORT label"
    resync = ResyncFreshness(
        in_progress=True, last_successful_at="not-a-time", last_failure_code=hostile
    )
    assert resync.last_failure_code == "unrecognized_resync_code"
    assert resync.last_successful_at is None
    readiness = _evaluate(resync=resync)
    rendered = f"{readiness!r}{readiness.states!r}{readiness.freshness!r}"
    for leaked in (CONNECTION, "m-42", "COHORT", hostile):
        assert leaked not in rendered
    assert readiness.freshness.last_resync_failure_code == "unrecognized_resync_code"
    assert readiness.freshness.last_successful_resync_at is None
    assert ResyncFreshness(last_failure_code="provider_status_404").last_failure_code == (
        "provider_status_404"
    )
