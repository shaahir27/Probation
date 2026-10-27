"""Gmail write adapter conformance: the C1 degradation made honest, never hidden.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 2, 3, 6 and 9. Every write goes through the
same fake provider the real client would face (CONTRACT invariant I-17), and that fake enforces NO
precondition, so each test below proves something the ADAPTER detected rather than something the
provider refused. The D3 effect paths (``packs/mail/executor.py``, ``workers/mail_execution.py``)
are driven through the reviewed D4/D5 lifecycle; provider-effect helpers remain hash-locked.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fake_gmail_read import _Message
from fake_gmail_write import INBOX, SENT, TRASH, FakeGmailWriteTransport

from probation.connectors.types import (
    ConnectorError,
    HttpResult,
    MessagePayload,
    ProviderUnavailable,
    SourceSelection,
)
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.lifecycle import ResponseIntent, binding_hash
from probation.core.review_binding import build_review_binding
from probation.core.types import Action
from probation.db.access import Role, RoleAccess
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
from probation.db.lifecycle_responses import ResponseStore
from probation.packs.mail.connectors.capability import CapabilityGate, build_write_manifest
from probation.packs.mail.connectors.gmail_auth import GMAIL_MODIFY_SCOPE, GMAIL_SEND_SCOPE
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_sync import GmailSync
from probation.packs.mail.connectors.gmail_versions import bracketed_message_id
from probation.packs.mail.connectors.gmail_write import (
    GmailMailExecutionIO,
    InMemoryAnchorStore,
    build_raw_message,
    hashed_native_ref,
)
from probation.packs.mail.executor import execute_mail_action, undo_mail_action
from probation.packs.mail.lifecycle_io import MailConflict, MailExecutionIO
from probation.packs.mail.lifecycle_operations import payload_digest, prepare_effect
from probation.workers.executor import Executor
from tests.unit.wp6_mail_fixture import GRANT, seed

CONNECTION = "conn-1"
ACCOUNT = "acct-1"
TOKEN = "write-token"
COHORT = "COHORT"
NOW = "2026-10-24T09:00:00Z"
APPROVED_AT = "2026-10-01T01:00:01Z"
_LIFECYCLE_BASELINE = {
    "probation/packs/mail/executor.py": "d19261606b300b08",
    # A fresh OAuth grant supersedes older controls; undo still refuses any current pause or
    # revoke. The label baseline now includes its reviewed formatting and anchor proof.
    "probation/workers/mail_execution.py": "e9ac2fc76a6b65df",
    "probation/packs/mail/lifecycle_io.py": "92f811471e72f68f",
    "probation/packs/mail/lifecycle_operations.py": "8acef881814bc4cb",
}


def clock() -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC))


def selection() -> SourceSelection:
    return SourceSelection(CONNECTION, ACCOUNT, 1, label_ids=(COHORT,))


def message(native_id: str, *, labels: set[str], rfc_message_id: str | None = None) -> _Message:
    return _Message(
        native_id,
        thread_id=f"thread-{native_id}",
        from_addr="alice@sender.test",
        to_addr="owner@test.local",
        subject="Notice",
        date="Tue, 14 Nov 2023 22:13:20 +0000",
        message_id=rfc_message_id or f"<{native_id}@sender.test>",
        internal_date_ms=1700000000000,
        labels=labels,
        text="Some information.",
    )


class MemoryPayloads:
    """Injected ``PayloadWriter``/``PayloadReader``: section-12 refs, no filesystem.

    The write adapter only depends on ``PayloadReader.read(payload_ref)``; the read path here
    persists through the same store, so threading identity comes from real parsing of the fake
    provider's headers, not from a hand-built fixture.
    """

    def __init__(self) -> None:
        self.items: dict[str, MessagePayload] = {}

    def write(self, payload: MessagePayload) -> str:
        ref = f"{CONNECTION}/{payload.native_message_id}.json"
        self.items[ref] = payload
        return ref

    def read(self, payload_ref: str) -> MessagePayload:
        if payload_ref not in self.items:
            raise ConnectorError("payload_missing")
        return self.items[payload_ref]


def _payload(native_id: str, **overrides: Any) -> MessagePayload:
    values: dict[str, Any] = {
        "native_message_id": native_id,
        "thread_id": f"thread-{native_id}",
        "rfc_message_id": "<original-1@sender.test>",
        "from_addr": "alice@sender.test",
        "to_addr": ("owner@test.local",),
        "cc_addrs": (),
        "subject": "Notice",
        "body_text": "Some information.",
        "occurred_at": None,
        "attachment_present": False,
        "content_hash": "sha256:" + hashlib.sha256(native_id.encode()).hexdigest()[:32],
    }
    values.update(overrides)
    return MessagePayload(**values)


class RacingTransport:
    """Wraps the fake so an unrelated actor edits inside the check-then-act window (C1).

    The edit is fired just before the adapter's *second* metadata read: the Executor has already
    taken its snapshot, and the write is about to be checked against it. That is precisely the gap
    Gmail cannot close, because ``modify`` carries no precondition.
    """

    def __init__(self, fake: FakeGmailWriteTransport, native_id: str) -> None:
        self.fake = fake
        self.native_id = native_id
        self.metadata_reads = 0
        self.armed = False

    def _is_state_read(self, url: str, params: Any) -> bool:
        quoted = quote(self.native_id, safe="")
        match = url.endswith(f"/messages/{self.native_id}") or url.endswith(f"/messages/{quoted}")
        return match and dict(params or {}).get("format") == "metadata"

    def get(self, url: str, *, params: Any = None, access_token: str) -> HttpResult:
        state_read = self._is_state_read(url, params)
        if state_read and self.armed and self.metadata_reads == 1:
            self.armed = False
            self.fake.external_edit(self.native_id, add=("IMPORTANT",))
        result = self.fake.get(url, params=params, access_token=access_token)
        if state_read:
            self.metadata_reads += 1
        return result

    def post(self, url: str, **kwargs: Any) -> HttpResult:
        return self.fake.post(url, **kwargs)


@dataclass
class Env:
    """One Gmail account, one cohort, one Executor-authority store, one write adapter."""

    fake: FakeGmailWriteTransport
    read: GmailReadConnector
    io: GmailMailExecutionIO
    store: ConnectorAccess
    sync: GmailSync
    anchors: InMemoryAnchorStore
    native_id: str
    racing: RacingTransport | None = field(default=None)

    @property
    def labels(self) -> set[str]:
        return set(self.fake.messages[self.native_id].labels)

    def catch_up(self) -> None:
        """The read worker commits the provider's own history, which is all versions come from."""
        self.sync.incremental(selection(), owner="reader-a")


def connector_access(path: Path, authority: str) -> ConnectorAccess:
    return ConnectorAccess(open_store(path), authority)  # type: ignore[arg-type]


_UNSET: Any = object()


def build_env(
    store_path: Path,
    *,
    require_cas: bool = False,
    allow_degraded: bool = True,
    payload_reader: Any = _UNSET,
    native_id: str = "m1",
    race: bool = False,
) -> Env:
    fake = FakeGmailWriteTransport(expected_token=TOKEN, page_size=5)
    fake.add_message(
        message(native_id, labels={COHORT, INBOX}, rfc_message_id="<original-1@sender.test>")
    )
    fake.add_message(
        message("m2", labels={COHORT, INBOX}, rfc_message_id="<original-2@sender.test>")
    )
    ingest = connector_access(store_path, "ingestor")
    reader = GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=clock(),
        owner_label=COHORT,
    )
    payloads = MemoryPayloads()
    sync = GmailSync(
        access=ingest,
        connector=reader,
        clock=clock(),
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        owner_label=COHORT,
        payloads=payloads,
    )
    sync.bootstrap(selection(), owner="reader-a")
    executor = connector_access(store_path, "executor")
    write_read = GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=clock(),
        owner_label=COHORT,
    )
    write_read.enumerate_cohort(selection())
    manifest = build_write_manifest(
        write_read, granted_scopes=(GMAIL_MODIFY_SCOPE, GMAIL_SEND_SCOPE)
    )
    racing = RacingTransport(fake, native_id) if race else None
    transport: Any = racing if racing is not None else fake
    anchors = InMemoryAnchorStore()
    gate = (
        CapabilityGate(manifest, require_provider_cas=True)
        if require_cas
        else CapabilityGate(manifest, allow_degraded_cas=allow_degraded)
    )
    io = GmailMailExecutionIO(
        transport,
        read=write_read,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        write_token=TOKEN,
        clock=clock(),
        gate=gate,
        store=executor,
        anchors=anchors,
        payload_reader=payloads if payload_reader is _UNSET else payload_reader,
    )
    return Env(
        fake=fake,
        read=write_read,
        io=io,
        store=executor,
        sync=sync,
        anchors=anchors,
        native_id=native_id,
        racing=racing,
    )


def make_action(kind: str, *, resource: str = "m1", identifier: str = "a") -> Action:
    params: dict[str, Any] = {"message_id": resource}
    if kind in {"REPLY", "FORWARD"}:
        params |= {
            "from_addr": "owner@test.local",
            "to_addr": "alice@sender.test",
            "subject": "Re: Notice",
            "body": "Thank you for the information.",
        }
    return Action(
        id=identifier,
        proposal_id="p",
        pack="mail",
        type=kind,
        params=params,
        level_required=2,
        recallable=True,
        created_at=NOW,
        updated_at=NOW,
    )


def label_payload(env: Env, *, add: list[str], remove: list[str]) -> dict[str, Any]:
    return {
        "type": "labels",
        "resource_id": env.native_id,
        "add_labels": add,
        "remove_labels": remove,
        "performed_at": NOW,
    }


def apply(env: Env, operation: str, revision: str, *, add: list[str], remove: list[str]) -> Any:
    payload = label_payload(env, add=add, remove=remove)
    return env.io.apply_mail(operation, payload_digest(payload), payload, revision)


def archive(env: Env) -> Any:
    """One legitimate Probation archive, then the ingestor catches up on the provider's history."""
    receipt = apply(
        env, "op-exec", env.io.snapshot_mail(env.native_id).revision, add=[], remove=[INBOX]
    )
    assert receipt.outcome == "confirmed", receipt.safe_code
    env.catch_up()
    return receipt


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "gmail_metadata.db"
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    return path


@pytest.fixture
def env(store_path: Path) -> Env:
    return build_env(store_path)


# -- contract shape ---------------------------------------------------------------------------
def test_adapter_satisfies_the_mail_execution_io_protocol(env: Env) -> None:
    assert isinstance(env.io, MailExecutionIO)
    snapshot = env.io.snapshot_mail(env.native_id)
    assert snapshot.labels == (COHORT, INBOX)
    assert snapshot.native_message_id == env.native_id
    assert snapshot.thread_id == f"thread-{env.native_id}"
    assert snapshot.label_versions == {}  # observed transitions only: nothing has changed yet


# -- 1 ----------------------------------------------------------------------------------------
def test_gmail_revision_detects_external_change(env: Env) -> None:
    """An external edit between snapshot and apply is caught by the adapter, never by Gmail."""
    before = env.io.snapshot_mail(env.native_id)
    env.fake.external_edit(env.native_id, add=("IMPORTANT",))
    assert "IMPORTANT" in env.labels  # Gmail refused nothing: modify carries no precondition (C1)
    receipt = apply(env, "op-1", before.revision, add=[], remove=[INBOX])
    assert receipt.outcome == "failed"
    assert receipt.safe_code == "mail_revision_conflict"
    assert receipt.confirmed_no_effect is True
    assert INBOX in env.labels and env.fake.write_calls == 0
    digest = payload_digest(label_payload(env, add=[], remove=[INBOX]))
    conflict = env.io.reconcile_mail("op-1", digest)
    assert conflict.outcome == "failed" and conflict.confirmed_no_effect is True
    assert env.io.journal_state("op-1") == "failed"
    # The identical call with a fresh revision goes through: only the revision differed.
    env.catch_up()  # the reader commits the provider's own history before versions are provable
    fresh = env.io.snapshot_mail(env.native_id)
    assert apply(env, "op-2", fresh.revision, add=[], remove=[INBOX]).outcome == "confirmed"


# -- 2 ----------------------------------------------------------------------------------------
def test_gmail_undo_refuses_after_label_removed_and_reapplied(env: Env) -> None:
    """The ABA case, refused by the real ``prepare_undo`` version equality, not by a stub."""
    act = make_action("TRASH")
    result = execute_mail_action(act, env.io)
    assert result.success and result.undo_data is not None
    env.catch_up()
    assert env.anchors.load(env.native_id).baseline == {}
    env.fake.external_edit(env.native_id, remove=(TRASH,))  # another actor removes the change
    env.catch_up()
    env.fake.external_edit(
        env.native_id, add=(TRASH,)
    )  # ...and re-adds it: the set looks identical
    env.catch_up()
    undone = undo_mail_action(act.model_copy(update={"undo": result.undo_data}), env.io)
    assert not undone.success and undone.error == "undo_state_conflict"
    assert env.io.snapshot_mail(env.native_id).label_versions == {TRASH: 3, INBOX: 1}
    assert env.fake.write_calls == 1 and TRASH in env.labels  # the refusal wrote nothing


# -- 4 ----------------------------------------------------------------------------------------
def test_gmail_undo_succeeds_when_only_probation_changed_labels(env: Env) -> None:
    act = make_action("ARCHIVE")
    result = execute_mail_action(act, env.io)
    assert result.success
    env.catch_up()
    undone = undo_mail_action(act.model_copy(update={"undo": result.undo_data}), env.io)
    assert undone.success, undone.error
    assert env.labels == {COHORT, INBOX} and env.fake.write_calls == 2
    env.catch_up()
    assert env.io.snapshot_mail(env.native_id).label_versions == {INBOX: 2}


# -- 5 ----------------------------------------------------------------------------------------
def test_unrelated_label_change_does_not_block_undo(env: Env) -> None:
    act = make_action("ARCHIVE")
    result = execute_mail_action(act, env.io)
    env.fake.external_edit(env.native_id, add=("IMPORTANT",))
    env.catch_up()
    undone = undo_mail_action(act.model_copy(update={"undo": result.undo_data}), env.io)
    assert undone.success, undone.error
    assert env.labels == {COHORT, INBOX, "IMPORTANT"}  # an untouched label stays untouched


# -- 3 ----------------------------------------------------------------------------------------
def test_gmail_snapshot_fails_closed_on_stale_anchor(env: Env) -> None:
    """A history anchor that aged out raises; it never degrades to ``{}`` or to a constant."""
    act = make_action("ARCHIVE")
    result = execute_mail_action(act, env.io)
    assert result.success
    env.catch_up()
    anchor = env.anchors.load(env.native_id)
    assert anchor is not None and anchor.anchor_history_id >= 1
    # The healthy path proves versions are per-label and provider-derived, never a constant.
    assert env.io.snapshot_mail(env.native_id).label_versions == {INBOX: 1}
    env.fake.set_history_expired_below(anchor.anchor_history_id + 1)
    with pytest.raises(MailConflict) as raised:
        env.io.snapshot_mail(env.native_id)
    assert "undo_history_unavailable" in str(raised.value)
    writes = env.fake.write_calls
    undone = undo_mail_action(act.model_copy(update={"undo": result.undo_data}), env.io)
    assert not undone.success and env.fake.write_calls == writes
    # Even after history serves again, a resync inside this process keeps the window untrusted.
    with pytest.raises(ProviderUnavailable):
        env.read.history_page({"startHistoryId": 0})
    env.fake.set_history_expired_below(0)
    with pytest.raises(MailConflict):
        env.io.snapshot_mail(env.native_id)


# -- 7 ----------------------------------------------------------------------------------------
def test_post_write_verification_detects_divergence(env: Env) -> None:
    """The provider answered but did something else: never report confirmed."""
    before = env.io.snapshot_mail(env.native_id)
    env.fake.arm_diverted_modify(add=("IMPORTANT",), remove=())
    receipt = apply(env, "op-diverge", before.revision, add=[], remove=[INBOX])
    assert receipt.outcome == "unknown" and receipt.safe_code == "mail_effect_diverged"
    assert receipt.confirmed_no_effect is False and INBOX in env.labels
    env.catch_up()
    fresh = env.io.snapshot_mail(env.native_id)
    env.fake.arm_dropped_write()  # HTTP 200 with nothing applied: provably no effect
    dropped = apply(env, "op-drop", fresh.revision, add=("STARRED",), remove=[])
    assert dropped.outcome == "failed" and dropped.confirmed_no_effect is True
    assert "STARRED" not in env.labels


# -- 6 ----------------------------------------------------------------------------------------
def test_ambiguous_send_stays_unknown_and_is_never_resent(env: Env) -> None:
    prepared = prepare_effect(make_action("REPLY"), env.io.snapshot_mail(env.native_id), NOW)
    payload, digest = prepared["payload"], prepared["payload_hash"]
    env.fake.arm_ambiguous_write(status=504, applied=True)
    lost = env.io.apply_mail(
        "op-send", digest, payload, env.io.snapshot_mail(env.native_id).revision
    )
    assert lost.outcome == "unknown" and lost.safe_code == "transport_ambiguous"
    assert env.fake.send_calls == 1
    env.io.apply_mail("op-send", digest, payload, env.io.snapshot_mail(env.native_id).revision)
    assert env.fake.send_calls == 1, "a retry must never resend an ambiguous send"
    resolved = env.io.reconcile_mail("op-send", digest)
    assert resolved.outcome == "confirmed" and str(resolved.native_ref).startswith("sha256:")
    assert _sent_count(env) == 1
    # An ambiguous send that never landed is still unknown: absence is not proof of failure.
    ghost = prepare_effect(
        make_action("REPLY", identifier="g"), env.io.snapshot_mail(env.native_id), NOW
    )
    env.fake.arm_ambiguous_write(status=504, applied=False)
    never = env.io.apply_mail(
        "op-ghost",
        ghost["payload_hash"],
        ghost["payload"],
        env.io.snapshot_mail(env.native_id).revision,
    )
    assert never.outcome == "unknown"
    resolved_ghost = env.io.reconcile_mail("op-ghost", ghost["payload_hash"])
    assert resolved_ghost.outcome == "unknown"
    assert resolved_ghost.safe_code == "needs_reconciliation"
    assert _sent_count(env) == 1 and env.io.journal_state("op-ghost") == "unknown"
    assert env.fake.send_calls == 2


def _sent_count(env: Env) -> int:
    return sum(1 for item in env.fake.messages.values() if SENT in item.labels)


# -- C7: reply threading ---------------------------------------------------------------------
def _raw_headers(raw: str) -> dict[str, str]:
    head, _, _ = raw.partition("\r\n\r\n")
    headers: dict[str, str] = {}
    for line in head.split("\r\n"):
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    return headers


def test_reply_threads_on_the_rfc_message_id_and_provider_thread(env: Env) -> None:
    """C7 requires all three: threadId, RFC In-Reply-To/References, and the reviewed subject."""
    prepared = prepare_effect(make_action("REPLY"), env.io.snapshot_mail(env.native_id), NOW)
    payload, digest = prepared["payload"], prepared["payload_hash"]
    receipt = env.io.apply_mail(
        "op-thread", digest, payload, env.io.snapshot_mail(env.native_id).revision
    )
    assert receipt.outcome == "confirmed", receipt.safe_code
    assert env.fake.send_calls == 1
    assert env.fake.send_bodies[-1]["threadId"] == f"thread-{env.native_id}"
    headers = _raw_headers(env.fake.sent_raw[-1])
    assert headers["in-reply-to"] == "<original-1@sender.test>"
    assert headers["references"] == "<original-1@sender.test>"
    assert headers["subject"] == payload["message"]["subject"] == "Re: Notice"
    # The native Gmail id is a different namespace and must never appear in either header.
    assert env.native_id not in headers["in-reply-to"]
    assert env.native_id not in headers["references"]
    sent = [item for item in env.fake.messages.values() if SENT in item.labels]
    assert len(sent) == 1 and sent[0].thread_id == f"thread-{env.native_id}"
    assert sent[0].in_reply_to == "<original-1@sender.test>"
    assert sent[0].references == ("<original-1@sender.test>",)


@pytest.mark.parametrize("broken", ["rfc", "thread", "native", "reader"])
def test_reply_refuses_without_a_provider_threading_identity(store_path: Path, broken: str) -> None:
    """A missing RFC id, thread id or payload store refuses before any POST. No fabricated header."""
    original = {
        "rfc": _payload("m1", rfc_message_id=None),
        "thread": _payload("m1", thread_id=None),
        "native": _payload("m1", rfc_message_id="m1"),
    }.get(broken)
    payloads = None
    if original is not None:
        payloads = MemoryPayloads()
        payloads.write(original)
    env = build_env(store_path, payload_reader=payloads)
    prepared = prepare_effect(make_action("REPLY"), env.io.snapshot_mail(env.native_id), NOW)
    posts = len(env.fake.post_paths)
    receipt = env.io.apply_mail(
        "op-refuse",
        prepared["payload_hash"],
        prepared["payload"],
        env.io.snapshot_mail(env.native_id).revision,
    )
    assert receipt.outcome == "failed" and receipt.safe_code == "reply_threading_unavailable"
    assert receipt.confirmed_no_effect is True
    assert env.fake.send_calls == 0 and len(env.fake.post_paths) == posts
    assert env.io.journal_state("op-refuse") == "failed"


def test_bracketed_message_id_is_bracketed_exactly_once_and_never_native() -> None:
    assert bracketed_message_id("orig@sender.test", native_message_id="m1") == (
        "<orig@sender.test>"
    )
    assert bracketed_message_id("<orig@sender.test>", native_message_id="m1") == (
        "<orig@sender.test>"
    )
    for bad in (None, "", "m1", "<m1>", "<<orig@sender.test>>", "<a@b> <c@d>"):
        with pytest.raises(MailConflict):
            bracketed_message_id(bad, native_message_id="m1")


def test_raw_message_never_emits_the_native_id_as_a_threading_header() -> None:
    values: dict[str, Any] = {
        "from_addr": "owner@test.local",
        "to_addr": "alice@sender.test",
        "message_id": "<action@probation.local>",
        "subject": "Re: Notice",
        "body": "Thank you.",
        "in_reply_to": "m1",  # the frozen payload's native id: never a header value
    }
    with pytest.raises(MailConflict):
        build_raw_message(values)
    raw = build_raw_message(values, rfc_message_id="<original-1@sender.test>")
    assert _raw_headers(raw)["in-reply-to"] == "<original-1@sender.test>"
    assert _raw_headers(raw)["references"] == "<original-1@sender.test>"
    assert "in-reply-to" not in _raw_headers(build_raw_message({**values, "in_reply_to": None}))


# -- 8 ----------------------------------------------------------------------------------------
def test_capability_gate_blocks_unsupported_effect_before_dispatch(store_path: Path) -> None:
    """With no provider compare-and-set, a CAS-dependent effect is refused before any write."""
    strict = build_env(store_path, require_cas=True)
    revision = strict.io.snapshot_mail(strict.native_id).revision
    with pytest.raises(ConnectorError) as raised:
        apply(strict, "op-gated", revision, add=[], remove=[INBOX])
    assert raised.value.safe_code == "capability_blocked_modify_has_no_precondition_c1"
    assert strict.fake.write_calls == 0 and INBOX in strict.labels
    verdict = strict.io.gate.verdict("archive")
    assert not verdict.allowed and verdict.safe_reason == "modify_has_no_precondition_c1"
    assert any(not item.allowed for item in strict.io.gate.readiness())


def test_gate_blocks_cas_dependent_dispatch_by_default_and_reports_opt_in(
    store_path: Path,
) -> None:
    """No opt-in means no archive: Gmail's missing conditional write blocks it by default."""
    env = build_env(store_path, allow_degraded=False)
    revision = env.io.snapshot_mail(env.native_id).revision
    with pytest.raises(ConnectorError) as raised:
        apply(env, "op-default", revision, add=[], remove=[INBOX])
    assert raised.value.safe_code == "capability_blocked_conditional_write_unsupported"
    assert env.fake.write_calls == 0 and INBOX in env.labels
    assert env.io.gate.verdict("archive").safe_reason == "conditional_write_unsupported"
    assert env.io.gate.verdict("send").allowed  # a send never depended on provider CAS
    # The deliberate opt-in permits check-then-act, but the verdict and receipt still say so.
    env.io.gate = CapabilityGate(env.io.gate.manifest, allow_degraded_cas=True)
    verdict = env.io.gate.verdict("archive")
    assert verdict.allowed and verdict.degraded
    assert verdict.safe_reason == "conditional_write_unsupported"
    assert verdict.missing == ("conditional_write",)
    assert env.io.gate.manifest.supports("conditional_write") is False
    receipt = apply(
        env, "op-degraded", env.io.snapshot_mail(env.native_id).revision, add=[], remove=[INBOX]
    )
    assert receipt.outcome == "confirmed", receipt.safe_code
    assert receipt.after_state["degraded_reason"] == "conditional_write_unsupported"
    assert env.fake.write_calls == 1


def test_gate_blocks_an_operation_that_needs_an_unsupported_capability(env: Env) -> None:
    """Attribution is unsupported (C9), so nothing may claim to know who changed a message."""
    with pytest.raises(ConnectorError) as raised:
        env.io.gate.require("attribution")
    assert raised.value.safe_code == "capability_blocked_history_has_no_actor_identity_c9"
    assert env.io.gate.verdict("attribution").missing == ("attribution",)


# -- 10 ---------------------------------------------------------------------------------------
def test_conformance_stale_expected_revision_is_detected(tmp_path: Path, store_path: Path) -> None:
    """End to end through D3's Executor: a stale revision is a proven non-effect, not a guess."""
    conn, world = seed(tmp_path, "ARCHIVE")
    target = "<m@test.local>"
    env = build_env(store_path, native_id=target, race=True)
    assert env.racing is not None
    binding = build_review_binding(
        conn,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=APPROVED_AT,
        response="accept",
    )
    ResponseStore(RoleAccess(conn, Role.API)).submit(
        ResponseIntent(
            request_id="approve",
            proposal_id="proposal",
            response="accept",
            owner_id="owner",
            responded_at=APPROVED_AT,
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
        )
    )
    executor = Executor(
        conn,
        env.io,
        licence_checker=lambda *_: 0,
        grant_resolver=lambda _: GRANT,
        worker_id="executor",
    )
    executor.process_responses(APPROVED_AT)
    env.racing.armed = True  # an unrelated actor edits after the snapshot, before the write
    history_before = env.fake.history_calls
    result = executor.process_queue(APPROVED_AT)
    assert result and not result[0].success
    assert result[0].error == "mail_revision_conflict"
    assert env.fake.write_calls == 0, "a stale revision must never reach the provider"
    assert env.racing.metadata_reads == 2, "the adapter re-reads immediately before writing"
    assert env.fake.history_calls == history_before + 1, "only the snapshot read provider history"
    # attempts.finish admits a definitive FAILED only on this adapter's non-effect proof.
    assert conn.execute("SELECT state FROM execution_attempts").fetchone()[0] == "failed"
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "FAILED"
    assert INBOX in env.labels
    world.close()
    conn.close()


# -- 11 ---------------------------------------------------------------------------------------
def test_native_receipt_is_hashed_not_raw(env: Env) -> None:
    revision = env.io.snapshot_mail(env.native_id).revision
    reads, history = env.fake.metadata_calls, env.fake.history_calls
    receipt = apply(env, "op-exec", revision, add=[], remove=[INBOX])
    assert receipt.outcome == "confirmed", receipt.safe_code
    # The pre-write check and the post-write verification are two metadata reads, and the effect
    # takes exactly one bounded history read to anchor its undo proof: never a second snapshot.
    assert env.fake.metadata_calls - reads == 2 and env.fake.history_calls - history == 1
    assert env.io.current_labels(env.native_id) == frozenset({COHORT})
    env.catch_up()
    rows = env.store.query("SELECT * FROM gmail_effect_receipts")
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["outcome"] == "confirmed" and row["operation"] == "execute"
    assert row["anchor_history_id"] is not None and row["verified_no_effect"] == 0
    assert row["safe_code"] is None
    assert isinstance(row["native_ref_hash"], str) and len(row["native_ref_hash"]) == 71
    assert row["native_ref_hash"] == hashed_native_ref(
        connection_id=CONNECTION, account_id=ACCOUNT, native_message_id=env.native_id
    )
    for field_name in ("native_ref_hash", "payload_hash", "safe_code", "action_id", "outcome"):
        assert env.native_id not in str(row[field_name]), field_name
    text = "".join(str(value) for value in row.values())
    assert "@" not in text and "owner@test.local" not in text  # no mailbox address, ever
    assert receipt.native_ref == row["native_ref_hash"]
    assert env.native_id not in str(receipt.after_state) and ACCOUNT not in str(receipt.after_state)


def test_trash_uses_the_reversible_method_and_never_a_delete_or_settings_call(env: Env) -> None:
    act = make_action("TRASH")
    result = execute_mail_action(act, env.io)
    assert result.success
    env.catch_up()
    assert undo_mail_action(act.model_copy(update={"undo": result.undo_data}), env.io).success
    assert env.fake.trash_calls == 1 and env.fake.untrash_calls == 1
    assert env.fake.modify_calls == 0
    forbidden = ("delete", "settings", "filter", "labels/create", "history")
    assert not any(word in path for path in env.fake.post_paths for word in forbidden)
    # Undo restores only what Probation changed: Gmail's implicit INBOX removal is never invented.
    assert TRASH not in env.labels and INBOX not in env.labels


# -- frozen D3 effect paths -------------------------------------------------------------------
def test_mail_lifecycle_effect_paths_match_the_reviewed_baseline() -> None:
    root = Path(__file__).parents[2] / "src"
    for relative, expected in _LIFECYCLE_BASELINE.items():
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()[:16]
        assert digest == expected, f"Reviewed lifecycle baseline changed unexpectedly: {relative}"
