"""Read connector: truthful capabilities, cohort gate before any body fetch, distinct times.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 4 and 9. Every call goes through the same
fake provider the real client would use (CONTRACT I-17), so these tests exercise the production
code path offline. Label versions are read from persisted ``gmail_history_events`` rows only.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

from probation.connectors.types import (
    NativeRef,
    ProviderUnavailable,
    SelectionViolation,
    SourceSelection,
)
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
from probation.packs.mail.connectors.gmail_payloads import GmailPayloadStore
from probation.packs.mail.connectors.gmail_read import GmailReadConnector

CONNECTION = "conn-1"
ACCOUNT = "acct-1"
TOKEN = "read-token"
OWNER_LABEL = "COHORT"
_SECRET = "SECRET-LABEL"
_NOW = "2026-10-24T09:00:00Z"

_SEED_EVENT = (
    "INSERT INTO gmail_history_events"
    " (connection_id,account_id,history_id,native_message_id,label_id,event_type,observed_at)"
    " VALUES(?,?,?,?,?,?,?)"
)


def _clock() -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC))


def _selection(*, labels: tuple[str, ...] = (OWNER_LABEL,)) -> SourceSelection:
    return SourceSelection(
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        selection_revision=1,
        label_ids=labels,
    )


def _connector(
    fake: FakeGmailTransport, payloads: GmailPayloadStore | None = None
) -> GmailReadConnector:
    return GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=_clock(),
        owner_label=OWNER_LABEL,
        payloads=payloads,
    )


@pytest.fixture
def payloads(tmp_path: Path) -> GmailPayloadStore:
    return GmailPayloadStore(tmp_path / "payloads", CONNECTION)


def _message(native_id: str, *, labels: set[str], internal_ms: int = 1700000000000) -> _Message:
    return _Message(
        native_id,
        thread_id=f"thread-{native_id}",
        from_addr="alice@sender.test",
        to_addr="bob@owner.test",
        subject=f"body {native_id}",
        date="Tue, 14 Nov 2023 22:13:20 +0000",
        message_id=f"<{native_id}@sender.test>",
        internal_date_ms=internal_ms,
        labels=labels,
        text="hello body text",
    )


def _ref(native_id: str) -> NativeRef:
    return NativeRef(CONNECTION, ACCOUNT, native_id)


def _seed(access: ConnectorAccess, native_id: str, events: list[tuple[int, str, bool]]) -> None:
    """Persist provider-shaped label transitions for one message (fixture only, never a path)."""
    for history_id, label_id, added in events:
        event_type = "labelAdded" if added else "labelRemoved"
        access.write(
            "gmail_history_events",
            _SEED_EVENT,
            (CONNECTION, ACCOUNT, history_id, native_id, label_id, event_type, _NOW),
        )


@pytest.fixture
def ingestor() -> Iterator[ConnectorAccess]:
    conn = open_store(":memory:")
    assert migrate_store(conn) is True
    access = ConnectorAccess(conn, "ingestor")
    try:
        yield access
    finally:
        access.conn.close()


# -- capability truth -----------------------------------------------------------------------
def test_capability_matrix_marks_conditional_modify_unsupported() -> None:
    manifest = _connector(FakeGmailTransport()).capabilities()
    assert manifest.supports("read") is True
    conditional = manifest.state("conditional_write")
    assert conditional is not None
    assert conditional.supported is False
    assert conditional.evidence == "unsupported"
    assert conditional.reason == "modify_has_no_precondition_c1"


def test_undo_history_proof_supported_but_window_bounded() -> None:
    manifest = _connector(FakeGmailTransport()).capabilities()
    state = manifest.state("undo_history_proof")
    assert state is not None and state.supported is True
    assert "window" in (state.reason or "")
    assert manifest.granted_scopes == ("gmail.readonly",)
    assert manifest.idempotency == "none"


def test_reconciliation_capability_is_bounded_not_exact() -> None:
    manifest = _connector(FakeGmailTransport()).capabilities()
    state = manifest.state("reconciliation")
    assert state is not None and state.supported is True
    assert "bounded" in (state.reason or "")  # C8: a bounded SENT search, never exact
    assert manifest.reconciliation == "bounded_local_evidence"


# -- cohort gate enforced before any body fetch (proof a) -----------------------------------
def test_non_cohort_id_triggers_zero_body_requests(payloads: GmailPayloadStore) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL, "INBOX"}))
    fake.add_message(_message("m-sec", labels={"INBOX"}))  # security/recovery mail, never selected
    connector = _connector(fake, payloads)
    refs = connector.enumerate_cohort(_selection())
    assert [ref.native_message_id for ref in refs] == ["m-cohort"]
    assert fake.body_calls == 0  # enumeration alone fetched no bodies
    with pytest.raises(SelectionViolation):
        connector.observe(_ref("m-sec"), observed_at="2026-10-24T09:00:00Z")
    assert fake.body_calls == 0  # the gate rejects before any messages.get


def test_cohort_member_body_is_fetched_once(payloads: GmailPayloadStore) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL, "INBOX"}))
    connector = _connector(fake, payloads)
    connector.enumerate_cohort(_selection())
    observation = connector.observe(_ref("m-cohort"), observed_at="2026-10-24T09:05:00Z")
    assert fake.body_calls == 1
    assert observation.native_message_id == "m-cohort"
    assert observation.event_type == "message_added"


# -- selection survives archive (proof c) ---------------------------------------------------
def test_tracking_survives_archive_after_inbox_removed() -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL, "INBOX"}))
    connector = _connector(fake)
    connector.enumerate_cohort(_selection())
    fake.modify_labels("m-cohort", remove=("INBOX",))  # archive keeps the owner label
    refs = connector.enumerate_cohort(_selection())
    assert any(ref.native_message_id == "m-cohort" for ref in refs)
    assert "m-cohort" in connector.proven()  # membership follows the label, not the inbox


# -- distinct times, separate identifiers ---------------------------------------------------
def test_observation_keeps_provider_occurrence_and_local_time_distinct(
    payloads: GmailPayloadStore,
) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL}, internal_ms=1700000000000))
    connector = _connector(fake, payloads)
    connector.enumerate_cohort(_selection())
    observed_at = "2026-10-24T09:10:00Z"
    observation = connector.observe(_ref("m-cohort"), observed_at=observed_at)
    assert observation.observed_at == observed_at
    assert observation.occurrence_time is not None
    assert (
        observation.occurrence_time != observed_at
    )  # internalDate, never the local knowledge time
    assert observation.provenance == "provider_occurrence"


def test_observed_at_is_stamped_from_the_injected_clock(tmp_path: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL}, internal_ms=1700000000000))
    clock = Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 11, 3, 7, 30, 0, tzinfo=UTC))
    connector = GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=clock,
        owner_label=OWNER_LABEL,
        payloads=GmailPayloadStore(tmp_path / "payloads", CONNECTION),
    )
    connector.enumerate_cohort(_selection())
    observation = connector.observe(_ref("m-cohort"))  # observed_at omitted -> injected Clock
    assert observation.observed_at == clock.now_iso()
    assert observation.occurrence_time is not None
    assert observation.occurrence_time != observation.observed_at
    assert observation.provenance == "provider_occurrence"


def test_four_identifiers_never_substitute(payloads: GmailPayloadStore) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("native-A", labels={OWNER_LABEL}))
    connector = _connector(fake, payloads)
    connector.enumerate_cohort(_selection())
    observation = connector.observe(_ref("native-A"), observed_at="2026-10-24T09:00:00Z")
    assert observation.native_message_id == "native-A"
    assert observation.thread_id == "thread-native-A"
    assert observation.rfc_message_id == "<native-A@sender.test>"
    assert observation.history_id >= 1
    assert (
        len({observation.native_message_id, observation.thread_id, observation.rfc_message_id}) == 3
    )


def test_foreign_account_ref_is_rejected(payloads: GmailPayloadStore) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL}))
    connector = _connector(fake, payloads)
    connector.enumerate_cohort(_selection())
    foreign = NativeRef(CONNECTION, "other-account", "m-cohort")
    with pytest.raises(SelectionViolation):
        connector.observe(foreign, observed_at="2026-10-24T09:00:00Z")


def test_sent_cohort_message_observed_as_sent(payloads: GmailPayloadStore) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-sent", labels={OWNER_LABEL, "SENT"}))
    connector = _connector(fake, payloads)
    connector.enumerate_cohort(_selection())
    observation = connector.observe(_ref("m-sent"), observed_at="2026-10-24T09:00:00Z")
    assert observation.event_type == "sent_observed"  # an observation, never an incoming situation


# -- out-of-cohort history is storage-silent (proof b) --------------------------------------
def test_out_of_cohort_history_stores_nothing(ingestor: ConnectorAccess) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL, "INBOX"}))
    fake.add_message(_message("m-stranger", labels={"INBOX"}))
    fake.modify_labels("m-cohort", remove=("INBOX",))  # cohort label event
    fake.modify_labels("m-stranger", add=(_SECRET,))  # out-of-cohort label event
    connector = _connector(fake)
    refs = connector.enumerate_cohort(_selection())
    assert [ref.native_message_id for ref in refs] == ["m-cohort"]

    transitions = connector.cohort_transitions(list(fake.history))
    assert transitions  # the cohort message's own event is projected
    assert all(t.native_message_id == "m-cohort" for t in transitions)
    assert all(t.label_id != _SECRET for t in transitions)  # no stranger label name escapes

    for transition in transitions:
        _seed(
            ingestor,
            transition.native_message_id,
            [(transition.history_id, transition.label_id, transition.added)],
        )
    rows = ingestor.query("SELECT native_message_id,label_id FROM gmail_history_events")
    assert all(row["native_message_id"] != "m-stranger" for row in rows)
    assert not any(row["label_id"] == _SECRET for row in rows)  # total storage silence
    assert "m-stranger" not in connector.proven()


# -- label versions from persisted rows, never synthesized ----------------------------------
def test_label_version_evidence_counts_persisted_transitions(ingestor: ConnectorAccess) -> None:
    connector = _connector(FakeGmailTransport(expected_token=TOKEN))
    connector.enumerate_cohort(_selection())
    _seed(ingestor, "m-cohort", [(5, OWNER_LABEL, True), (6, OWNER_LABEL, False)])
    evidence = connector.label_version_evidence("m-cohort", access=ingestor, anchor_history_id=0)
    assert evidence.versions == {OWNER_LABEL: 2}  # remove-then-readd advances the count (ABA)
    assert evidence.continuous is True
    assert evidence.anchor_history_id == 0


def test_label_version_evidence_never_synthesizes_or_pads(ingestor: ConnectorAccess) -> None:
    connector = _connector(FakeGmailTransport(expected_token=TOKEN))
    connector.enumerate_cohort(_selection())
    _seed(ingestor, "m-cohort", [(7, "INBOX", False)])
    evidence = connector.label_version_evidence("m-cohort", access=ingestor, anchor_history_id=0)
    assert evidence.versions == {"INBOX": 1}
    assert OWNER_LABEL not in evidence.versions  # a label that never moved is not defaulted in
    ghost = connector.label_version_evidence("m-none", access=ingestor, anchor_history_id=0)
    assert ghost.versions == {}  # empty retained history -> no invented version


def test_label_version_evidence_not_continuous_without_anchor(ingestor: ConnectorAccess) -> None:
    connector = _connector(FakeGmailTransport(expected_token=TOKEN))
    _seed(ingestor, "m-cohort", [(3, OWNER_LABEL, True)])
    evidence = connector.label_version_evidence("m-cohort", access=ingestor, anchor_history_id=None)
    assert evidence.continuous is False  # no anchor -> cannot bound the window -> fail closed


def test_label_version_evidence_gap_window_not_continuous(ingestor: ConnectorAccess) -> None:
    connector = _connector(FakeGmailTransport(expected_token=TOKEN))
    _seed(ingestor, "m-cohort", [(4, OWNER_LABEL, True)])
    evidence = connector.label_version_evidence(
        "m-cohort", access=ingestor, anchor_history_id=0, window_complete=False
    )
    assert evidence.continuous is False  # an acknowledged gap cannot prove completeness


def test_label_version_evidence_anchor_outside_retained_window(ingestor: ConnectorAccess) -> None:
    connector = _connector(FakeGmailTransport(expected_token=TOKEN))
    _seed(ingestor, "m-cohort", [(120, OWNER_LABEL, True)])
    evidence = connector.label_version_evidence(
        "m-cohort", access=ingestor, anchor_history_id=5, retained_from=10
    )
    assert evidence.continuous is False  # anchor predates the retained history window


def test_history_404_flags_resync_and_evidence_not_continuous(ingestor: ConnectorAccess) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-cohort", labels={OWNER_LABEL}))
    fake.set_history_expired_below(100)  # any startHistoryId below 100 now answers 404 (C3)
    connector = _connector(fake)
    connector.enumerate_cohort(_selection())
    _seed(ingestor, "m-cohort", [(150, OWNER_LABEL, True)])
    with pytest.raises(ProviderUnavailable):
        connector.history_page({"startHistoryId": 5, "maxResults": 50})
    # The aged-out window is recorded, so the connector refuses to claim continuity.
    evidence = connector.label_version_evidence(
        "m-cohort", access=ingestor, anchor_history_id=120, window_complete=True
    )
    assert evidence.continuous is False


# -- live gate stays offline ----------------------------------------------------------------
@pytest.mark.live
def test_live_gmail_profile_and_bounded_read() -> None:
    """Phase 7 live test. Exercises real Gmail profile read and bounded list over real transport.

    Opt-in: PROBATION_GMAIL_LIVE_CONSENT=scoped-authorization-granted.
    Required env: PROBATION_GMAIL_CLIENT_ID, PROBATION_GMAIL_CLIENT_SECRET,
    PROBATION_GMAIL_REFRESH_TOKEN, PROBATION_GMAIL_ACCOUNT.
    """
    import os

    if os.environ.get("PROBATION_GMAIL_LIVE_CONSENT") != "scoped-authorization-granted":
        pytest.skip("PROBATION_GMAIL_LIVE_CONSENT not granted")
    client_id = os.environ.get("PROBATION_GMAIL_CLIENT_ID") or os.environ.get(
        "PROBATION_GMAIL_READ_CLIENT_ID", ""
    )
    client_secret = os.environ.get("PROBATION_GMAIL_CLIENT_SECRET") or os.environ.get(
        "PROBATION_GMAIL_READ_CLIENT_SECRET", ""
    )
    refresh_token = os.environ.get("PROBATION_GMAIL_REFRESH_TOKEN") or os.environ.get(
        "PROBATION_GMAIL_READ_REFRESH_TOKEN", ""
    )
    account = os.environ.get("PROBATION_GMAIL_ACCOUNT", "").strip().lower()
    label = os.environ.get("PROBATION_GMAIL_LABEL", "PROBATION")
    if not (client_id and client_secret and refresh_token and account):
        pytest.skip("live credentials missing")

    from probation.connectors.credentials_state import SecretMaterial
    from probation.packs.mail.connectors.gmail_auth import OAuthTokenExchange, StateVault
    from probation.packs.mail.connectors.gmail_transport import (
        GmailHttpTransport,
        GmailProfileGateway,
        GoogleTokenTransport,
    )

    api_transport = GmailHttpTransport()
    token_transport = GoogleTokenTransport()
    try:
        gateway = GmailProfileGateway(api_transport)
        exchange = OAuthTokenExchange(
            client_id=client_id,
            client_secret=client_secret,
            vault=StateVault(),
            transport=token_transport,
            userinfo=gateway,
        )
        bundle = exchange.refresh("cred-ref-live", SecretMaterial(refresh_token, "refresh"))
        assert bundle.account_id == account

        read = GmailReadConnector(
            api_transport,
            connection_id="live-conn",
            account_id=account,
            access_token=bundle.access.reveal(),
            owner_label=label,
            clock=Clock.live(),
        )
        email = gateway.account_email(bundle.access)
        assert email == account
        cohort = read.enumerate_cohort(
            SourceSelection(
                connection_id="live-conn",
                account_id=account,
                selection_revision=1,
                label_ids=(label,),
            )
        )
        assert cohort, "approved synthetic test cohort is empty"
    finally:
        api_transport.close()
