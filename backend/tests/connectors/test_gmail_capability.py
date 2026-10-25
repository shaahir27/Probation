"""Capability truth and the pre-dispatch gate for the Gmail write side (D4-02/D4-08).

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 2, 6 and 7. The write manifest may only ever
inherit the read side's verdicts, never upgrade them: a local lock is not provider atomicity (C1),
history carries no actor (C9), and an ambiguous send has no provider idempotency key (C8). Blocked
operations must carry a safe reason, and the rows are Executor-owned in the private store.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_gmail_write import INBOX
from test_gmail_write import ACCOUNT, CONNECTION, build_env, connector_access

from probation.connectors.types import CapabilityState, ConnectorError
from probation.db.gmail_store import migrate_store, open_store
from probation.packs.mail.connectors.capability import (
    DEGRADED_CAS_REASON,
    CapabilityGate,
    build_write_manifest,
    load_write_manifest,
    persist_write_capabilities,
)
from probation.packs.mail.connectors.gmail_auth import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
)

SCOPES = (GMAIL_READONLY_SCOPE, GMAIL_MODIFY_SCOPE, GMAIL_SEND_SCOPE)


@pytest.fixture
def store_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "gmail_capabilities.db"
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    yield path


def test_gmail_capability_matrix_marks_conditional_modify_unsupported(store_path: Path) -> None:
    env = build_env(store_path)
    manifest = build_write_manifest(env.read, granted_scopes=SCOPES)
    conditional = manifest.state("conditional_write")
    assert conditional is not None
    assert manifest.supports("conditional_write") is False
    assert conditional.evidence == "unsupported"
    assert conditional.reason == "modify_has_no_precondition_c1"
    # C2/C3: undo proof exists but is window-bounded, never claimed as durable.
    history = manifest.state("undo_history_proof")
    assert history is not None and history.supported and history.evidence == "supported"
    assert history.reason == "window_bounded_history_about_one_week"
    # C9: no provider can say who changed a message.
    assert manifest.supports("attribution") is False
    assert manifest.state("attribution").reason == "history_has_no_actor_identity_c9"  # type: ignore[union-attr]
    # C8: no idempotency key, so reconciliation stays a bounded evidence search.
    assert manifest.idempotency == "none"
    assert manifest.reconciliation == "bounded_local_evidence"
    assert manifest.state("reconciliation").reason == "bounded_sent_search_not_exact_c8"  # type: ignore[union-attr]
    assert manifest.supports("archive") and manifest.supports("trash") and manifest.supports("send")
    assert manifest.provider == "gmail" and manifest.provider_version == "v1"


def test_write_manifest_can_never_upgrade_a_read_verdict(store_path: Path) -> None:
    env = build_env(store_path)
    read_manifest = env.read.capabilities()
    write_manifest = build_write_manifest(env.read, granted_scopes=SCOPES)
    for name in ("conditional_write", "undo_history_proof", "reconciliation", "read"):
        inherited = read_manifest.state(name)
        assert inherited is not None and write_manifest.state(name) == inherited


def test_gate_blocks_every_cas_dependent_operation_when_modify_has_no_precondition(
    store_path: Path,
) -> None:
    env = build_env(store_path)
    strict = CapabilityGate(
        build_write_manifest(env.read, granted_scopes=SCOPES), require_provider_cas=True
    )
    blocked = [item for item in strict.readiness() if not item.allowed]
    assert {item.operation for item in blocked} >= {"archive", "trash", "undo", "atomic_reconcile"}
    for operation in ("archive", "trash", "undo", "atomic_reconcile"):
        verdict = strict.verdict(operation)
        assert not verdict.allowed and verdict.safe_reason == "modify_has_no_precondition_c1"
        assert "conditional_write" in verdict.missing
    assert strict.verdict(
        "send"
    ).allowed  # a send never claimed conditional atomicity to begin with
    with pytest.raises(ConnectorError) as raised:
        strict.require("archive")
    assert raised.value.safe_code == "capability_blocked_modify_has_no_precondition_c1"


def test_gate_blocks_cas_dependent_operations_by_default(store_path: Path) -> None:
    """C1: no opt-in, so archive/trash/undo/atomic_reconcile never reach check-then-act dispatch."""
    env = build_env(store_path)
    gate = CapabilityGate(build_write_manifest(env.read, granted_scopes=SCOPES))
    for operation in ("archive", "trash", "undo", "atomic_reconcile"):
        verdict = gate.verdict(operation)
        assert not verdict.allowed, operation
        assert verdict.safe_reason == DEGRADED_CAS_REASON == "conditional_write_unsupported"
        assert verdict.missing == ("conditional_write",)
    blocked = {item.operation for item in gate.readiness() if not item.allowed}
    assert blocked >= {"archive", "trash", "undo", "atomic_reconcile"}
    with pytest.raises(ConnectorError) as raised:
        gate.require("archive")
    assert raised.value.safe_code == "capability_blocked_conditional_write_unsupported"
    assert gate.verdict("send").allowed and gate.verdict("reconcile").allowed


def test_explicit_degraded_opt_in_dispatches_but_still_reports_the_gap(store_path: Path) -> None:
    """The caller may accept check-then-act; the manifest and verdict never stop saying so."""
    env = build_env(store_path)
    manifest = build_write_manifest(env.read, granted_scopes=SCOPES)
    gate = CapabilityGate(manifest, allow_degraded_cas=True)
    assert manifest.supports("conditional_write") is False
    for operation in ("archive", "trash", "undo"):
        verdict = gate.verdict(operation)
        assert verdict.allowed, operation
        assert verdict.degraded is True
        assert verdict.safe_reason == "conditional_write_unsupported"
        assert verdict.missing == ("conditional_write",)
        assert gate.require(operation).degraded is True
    # ``atomic_reconcile`` promises atomicity itself, so degradation cannot satisfy it.
    strict_atomic = gate.verdict("atomic_reconcile")
    assert not strict_atomic.allowed and strict_atomic.degraded is False
    assert strict_atomic.safe_reason == "modify_has_no_precondition_c1"
    assert gate.verdict("send").degraded is False
    assert gate.verdict("send").safe_reason is None
    # Strict and degraded are mutually exclusive policies, refused rather than resolved by order.
    with pytest.raises(ConnectorError) as raised:
        CapabilityGate(manifest, require_provider_cas=True, allow_degraded_cas=True)
    assert raised.value.safe_code == "conflicting_cas_policy"


def test_gate_allows_effects_that_tolerate_check_then_act_but_never_attribution(
    store_path: Path,
) -> None:
    env = build_env(store_path)
    gate = CapabilityGate(
        build_write_manifest(env.read, granted_scopes=SCOPES), allow_degraded_cas=True
    )
    for operation in ("archive", "trash", "send", "undo", "reconcile"):
        assert gate.verdict(operation).allowed, operation
    assert not gate.verdict("attribution").allowed
    assert gate.verdict("attribution").safe_reason == "history_has_no_actor_identity_c9"
    assert gate.verdict("forward").allowed  # provider support exists; the D3 allowlist is separate
    assert not gate.verdict("unknown_operation").allowed


def test_scope_short_of_an_operation_blocks_it(store_path: Path) -> None:
    env = build_env(store_path)
    manifest = build_write_manifest(env.read, granted_scopes=(GMAIL_READONLY_SCOPE,))
    gate = CapabilityGate(manifest)
    assert not gate.verdict("send").allowed
    assert gate.verdict("send").safe_reason == "scope_not_granted_gmail_send"
    granted = CapabilityGate(build_write_manifest(env.read, granted_scopes=SCOPES))
    assert granted.verdict("send").allowed


def test_write_capabilities_persist_under_executor_authority_only(store_path: Path) -> None:
    path = store_path
    env = build_env(path)
    manifest = build_write_manifest(env.read, granted_scopes=SCOPES)
    written = persist_write_capabilities(
        env.store,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        manifest=manifest,
        manifest_version=1,
    )
    assert written >= 5
    rows = env.store.query(
        "SELECT name,supported,evidence,reason,owner_role FROM gmail_capabilities"
        " WHERE owner_role='write' ORDER BY name"
    )
    stored = {str(row["name"]): dict(row) for row in rows}
    assert stored["conditional_write"]["supported"] == 0
    assert stored["conditional_write"]["reason"] == "modify_has_no_precondition_c1"
    # A supported row never carries a reason, so no reader can mistake a note for a guarantee.
    assert stored["archive"]["supported"] == 1 and stored["archive"]["reason"] is None
    assert set(stored) >= {
        "archive",
        "trash",
        "send",
        "forward",
        "reconciliation",
        "undo_history_proof",
        "conditional_write",
    }
    assert "attribution" not in stored and "read" not in stored  # read-owned rows: D4 section 7
    assert written == len(stored)
    reader = connector_access(path, "read_worker")
    with pytest.raises(ConnectorError) as refused:
        persist_write_capabilities(
            reader,
            connection_id=CONNECTION,
            account_id=ACCOUNT,
            manifest=manifest,
            manifest_version=2,
        )
    assert refused.value.safe_code == "capability_rows_need_executor_authority"
    assert (
        env.store.one("SELECT count(*) AS n FROM gmail_capabilities WHERE owner_role='write'")["n"]
        == written
    )  # type: ignore[index]
    assert json.dumps([dict(row) for row in rows])  # rows are readable by any role, writable by one
    assert (
        env.store.one("SELECT count(*) AS n FROM gmail_capabilities WHERE owner_role='write'")["n"]
        == written
    )  # type: ignore[index]
    reloaded = load_write_manifest(env.store, connection_id=CONNECTION, account_id=ACCOUNT)
    assert reloaded.supports("conditional_write") is False
    assert reloaded.state("archive").supported is True  # type: ignore[union-attr]
    assert env.io.snapshot_mail("m1").labels[-1] == INBOX


def test_unsupported_state_without_a_reason_is_rejected() -> None:
    with pytest.raises(ConnectorError):
        CapabilityState(name="archive", supported=False, verified_at="2026-10-24T09:00:00Z")
