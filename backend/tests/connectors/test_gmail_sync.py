"""Bootstrap + incremental sync: atomic page commits, fencing, resync and cohort privacy.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 2, 4, 7 and 9 (test ids for D4-07/06), and
docs/FULL_PRODUCT_SPEC.md sections 5.1, 6 and 7.2. The private store is exercised through the
real ``ingestor`` authority and the same fake provider the real transport would face.
"""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

from probation.connectors.acl import PrivatePathRejected
from probation.connectors.types import (
    CursorRejected,
    SourceSelection,
)
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
from probation.packs.mail.connectors import gmail_payloads as payloads_module
from probation.packs.mail.connectors.gmail_payloads import GmailPayloadStore
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_sync import GmailSync

CONNECTION = "conn-1"
ACCOUNT = "acct-1"
TOKEN = "read-token"
OWNER_LABEL = "COHORT"
STRANGER = "m-stranger"


def _clock() -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC))


def _selection() -> SourceSelection:
    return SourceSelection(
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        selection_revision=1,
        label_ids=(OWNER_LABEL,),
    )


def _message(native_id: str, *, labels: set[str]) -> _Message:
    return _Message(
        native_id,
        thread_id=f"thread-{native_id}",
        from_addr="alice@sender.test",
        to_addr="bob@owner.test",
        subject=f"body {native_id}",
        date="Tue, 14 Nov 2023 22:13:20 +0000",
        message_id=f"<{native_id}@sender.test>",
        internal_date_ms=1700000000000,
        labels=labels,
        text="hello body text",
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "gmail_metadata.db"
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    yield path


def _access(path: Path, authority: str = "ingestor") -> ConnectorAccess:
    return ConnectorAccess(open_store(path), authority)  # type: ignore[arg-type]


def _sync(
    fake: FakeGmailTransport, access: ConnectorAccess, clock: Clock | None = None
) -> GmailSync:
    resolved = clock if clock is not None else _clock()
    connector = GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=resolved,
        owner_label=OWNER_LABEL,
    )
    return GmailSync(
        access=access,
        connector=connector,
        clock=resolved,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        owner_label=OWNER_LABEL,
    )


def _count(access: ConnectorAccess, table: str) -> int:
    row = access.one(f"SELECT count(*) AS n FROM {table}")
    return int(row["n"]) if row is not None else 0  # type: ignore[index]


def _committed(access: ConnectorAccess) -> tuple[int, int]:
    row = access.one(
        "SELECT committed_history_id AS c,catchup_complete AS k FROM gmail_sync_cursors "
        "WHERE connection_id=? AND resource_key='cohort'",
        (CONNECTION,),
    )
    return (int(row["c"]), int(row["k"]))  # type: ignore[index]


def test_bootstrap_commits_all_pages_and_installs_watermark(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN, page_size=2)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    fake.add_message(_message("m2", labels={OWNER_LABEL, "INBOX"}))
    fake.add_message(_message(STRANGER, labels={"INBOX"}))
    access = _access(store)
    try:
        result = _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        assert result.observations_written >= 2
        assert result.catchup_complete is True
        assert _count(access, "gmail_observations") == 2
        committed, complete = _committed(access)
        assert complete == 1
        assert committed >= 1
        # The stranger message is never stored, in any table, at all.
        for table in ("gmail_observations", "gmail_history_events"):
            rows = access.query(f"SELECT * FROM {table}")
            assert not any(STRANGER in str(dict(row)) for row in rows)
    finally:
        access.conn.close()


def test_crash_before_page_commit_repeats(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN, page_size=5)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    fake.add_message(_message("m2", labels={OWNER_LABEL}))
    crash_access = _access(store)
    try:
        crasher = _sync(fake, crash_access)
        original = crasher._advance
        calls = {"n": 0}

        def boom(*args: object, **kwargs: object) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated crash before commit")
            original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(crasher, "_advance", boom)
        with pytest.raises(RuntimeError):
            crasher.bootstrap(_selection(), owner="reader-a")
        # The page that crashed left nothing behind: observation and cursor rolled back together.
        assert _count(crash_access, "gmail_observations") == 0
    finally:
        crash_access.conn.close()

    # Restarting the same sync commits cleanly and produces exactly one row per message.
    restart_access = _access(store)
    try:
        _sync(fake, restart_access).bootstrap(_selection(), owner="reader-a")
        assert _count(restart_access, "gmail_observations") == 2
    finally:
        restart_access.conn.close()


def test_crash_after_commit_does_not_duplicate(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN, page_size=5)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    fake.add_message(_message("m2", labels={OWNER_LABEL}))
    fake.offer_duplicate_pages()
    fake.offer_overlapping_pages()
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        first = _count(access, "gmail_observations")
        committed_after_first = _committed(access)
        # A worker that restarts after committing replays; the primary key keeps it idempotent.
        fake.offer_duplicate_pages()
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        assert _count(access, "gmail_observations") == first
        assert _committed(access)[0] == committed_after_first[0]
    finally:
        access.conn.close()


def test_second_worker_cannot_advance_cursor(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    a_access = _access(store)
    b_access = _access(store)
    try:
        sync_a = _sync(fake, a_access)
        fence_a = sync_a.claim("reader-a", _selection())
        assert fence_a == 1
        sync_b = _sync(fake, b_access)
        with pytest.raises(CursorRejected):
            sync_b.claim("reader-b", _selection())
    finally:
        a_access.conn.close()
        b_access.conn.close()


def test_stale_worker_is_fenced_out_after_takeover(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    a_access = _access(store)
    b_access = _access(store)
    clock = _clock()
    try:
        sync_a = _sync(fake, a_access)
        fence_a = sync_a.claim("reader-a", _selection())
        # A's lease expires; B takes over, which advances the fencing token.
        clock.advance_seconds(120)
        fake_b = FakeGmailTransport(expected_token=TOKEN)
        fake_b.add_message(_message("m1", labels={OWNER_LABEL}))
        sync_b = GmailSync(
            access=b_access,
            connector=GmailReadConnector(
                fake_b,
                connection_id=CONNECTION,
                account_id=ACCOUNT,
                access_token=TOKEN,
                clock=clock,
                owner_label=OWNER_LABEL,
            ),
            clock=clock,
            connection_id=CONNECTION,
            account_id=ACCOUNT,
            owner_label=OWNER_LABEL,
        )
        sync_b.claim("reader-b", _selection())
        # A still holds the stale fence; any cursor advance it attempts must be refused.
        with pytest.raises(CursorRejected), a_access.transaction() as tx:
            tx.write(
                "gmail_observations",
                "INSERT OR IGNORE INTO gmail_observations (connection_id,account_id,"
                "native_message_id,history_id,event_type,content_hash,version_hash,observed_at,"
                "occurrence_provenance,label_ids,payload_ref) VALUES('"
                + CONNECTION
                + "','"
                + ACCOUNT
                + "','m1',9,'message_added','sha256:a','sha256:b',?,"
                "'provider_occurrence','[]','data/private/x')",
                (clock.now_iso(),),
            )
            sync_a._advance(tx, _selection(), "reader-a", fence_a, committed=9, complete=False)
        assert _count(a_access, "gmail_observations") == 0
    finally:
        a_access.conn.close()
        b_access.conn.close()


def test_404_history_triggers_resync_not_empty_poll(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        committed, complete = _committed(access)
        assert complete == 1
        # Age the history window out from under the durable watermark.
        fake.set_history_expired_below(committed + 1)
        fake.history_calls = 0
        result = _sync(fake, access).incremental(_selection(), owner="reader-a")
        assert result.resync_required is True
        assert result.catchup_complete is False  # never reported as a clean, empty poll
        assert fake.history_calls >= 1
        assert _committed(access)[0] == committed
    finally:
        access.conn.close()


def test_incremental_records_label_changes_and_tombstones(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        # Another actor archives then restores: a remove followed by an add.
        fake.modify_labels("m1", add=("label-archived",), remove=(OWNER_LABEL,))
        fake.modify_labels("m1", add=(OWNER_LABEL,), remove=("label-archived",))
        _sync(fake, access).incremental(_selection(), owner="reader-a")
        events = access.query(
            "SELECT event_type FROM gmail_history_events WHERE native_message_id='m1'"
        )
        kinds = [str(row["event_type"]) for row in events]
        assert "labelRemoved" in kinds and "labelAdded" in kinds
        # Out-of-cohort label work for the stranger is never recorded.
        fake.add_message(_message(STRANGER, labels={"INBOX"}))
        _sync(fake, access).incremental(_selection(), owner="reader-a")
        assert not any(
            STRANGER in str(dict(row)) for row in access.query("SELECT * FROM gmail_history_events")
        )
    finally:
        access.conn.close()


def test_out_of_cohort_history_stores_nothing(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        before_obs = _count(access, "gmail_observations")
        before_hist = _count(access, "gmail_history_events")
        # A brand-new inbound message that was never approved into the cohort.
        fake.add_message(_message(STRANGER, labels={"INBOX", "CATEGORY_UPDATES"}))
        _sync(fake, access).incremental(_selection(), owner="reader-a")
        assert _count(access, "gmail_observations") == before_obs
        assert _count(access, "gmail_history_events") == before_hist
        for table in ("gmail_observations", "gmail_history_events"):
            assert not any(
                STRANGER in str(dict(row)) for row in access.query(f"SELECT * FROM {table}")
            )
    finally:
        access.conn.close()


def test_label_evidence_counts_only_persisted_transitions(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        anchor = _committed(access)[0]
        fake.modify_labels("m1", add=("extra",), remove=(OWNER_LABEL,))
        fake.modify_labels("m1", add=(OWNER_LABEL,), remove=("extra",))
        _sync(fake, access).incremental(_selection(), owner="reader-a")
        evidence = _sync(fake, access).build_label_evidence(
            _selection(), "m1", anchor_history_id=anchor
        )
        assert evidence.continuous is True
        assert evidence.versions.get(OWNER_LABEL, 0) >= 1
        assert evidence.versions.get("extra", 0) >= 1
    finally:
        access.conn.close()


def test_label_evidence_not_continuous_after_resync(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        anchor = _committed(access)[0]
        evidence = _sync(fake, access).build_label_evidence(
            _selection(), "m1", anchor_history_id=anchor, resync_required=True
        )
        assert evidence.continuous is False
    finally:
        access.conn.close()


def test_cursor_reuse_rejected_across_filter_revisions(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        bumped = SourceSelection(
            connection_id=CONNECTION,
            account_id=ACCOUNT,
            selection_revision=2,
            label_ids=(OWNER_LABEL,),
        )
        with pytest.raises(CursorRejected):
            _sync(fake, access).incremental(bumped, owner="reader-a")
    finally:
        access.conn.close()


def test_two_ingestor_connections_are_distinct_sqlite_handles(store: Path) -> None:
    a = _access(store)
    b = _access(store)
    try:
        assert a.conn is not b.conn
        assert isinstance(a.conn, sqlite3.Connection)
    finally:
        a.conn.close()
        b.conn.close()


# -- section 12: payloads are real, relative and fail closed --------------------------------
def _payload_root(store: Path) -> Path:
    """The contract root beside the private metadata store, as GmailSync derives it."""
    return store.parent / "payloads"


def test_incremental_new_message_gets_a_body_and_observation(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        # A brand-new inbound message, already carrying the owner label at delivery.
        fake.add_message(_message("m-new", labels={OWNER_LABEL, "INBOX"}))
        bodies_before = fake.body_calls

        result = _sync(fake, access).incremental(_selection(), owner="reader-a")

        assert result.observations_written == 1
        assert fake.body_calls == bodies_before + 1  # exactly the new message's body
        row = access.one(
            "SELECT payload_ref,event_type FROM gmail_observations WHERE native_message_id='m-new'"
        )
        assert row is not None
        assert row["event_type"] == "message_added"
        ref = str(row["payload_ref"])
        assert not Path(ref).is_absolute()
        payload = GmailPayloadStore(_payload_root(store)).read(ref)
        assert payload.native_message_id == "m-new"
        assert payload.from_addr == "alice@sender.test"
        assert payload.subject == "body m-new"
        assert payload.body_text == "hello body text"
    finally:
        access.conn.close()


def test_out_of_cohort_new_message_gets_no_body_request(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        fake.add_message(_message(STRANGER, labels={"INBOX", "CATEGORY_UPDATES"}))
        bodies_before = fake.body_calls

        result = _sync(fake, access).incremental(_selection(), owner="reader-a")

        assert fake.body_calls == bodies_before  # the zero-body-request guarantee holds
        assert result.observations_written == 0
        assert (
            access.one(
                "SELECT 1 AS present FROM gmail_observations WHERE native_message_id=?",
                (STRANGER,),
            )
            is None
        )
    finally:
        access.conn.close()


def test_payload_write_requires_owner_only_acl(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    access = _access(store)

    def deny(path: Path) -> None:
        raise PrivatePathRejected("forced_acl_failure")

    monkeypatch.setattr(payloads_module, "verify_owner_only", deny)
    try:
        with pytest.raises(PrivatePathRejected):
            _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        assert _count(access, "gmail_observations") == 0  # fail closed: no observation row
        assert not list(_payload_root(store).rglob("*.json"))  # and no payload file
    finally:
        access.conn.close()


def test_reobservation_reuses_payload_and_does_not_duplicate(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        first = access.query(
            "SELECT payload_ref FROM gmail_observations WHERE native_message_id='m1'"
        )
        assert len(first) == 1
        ref = str(first[0]["payload_ref"])
        payload_dir = _payload_root(store) / CONNECTION
        first_files = sorted(path.name for path in payload_dir.glob("*.json"))

        # A restart re-observes the same message: same ref, same single file, same single row.
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")

        rows = access.query(
            "SELECT payload_ref FROM gmail_observations WHERE native_message_id='m1'"
        )
        assert len(rows) == 1
        assert str(rows[0]["payload_ref"]) == ref
        assert sorted(path.name for path in payload_dir.glob("*.json")) == first_files
        assert first_files == ["m1.json"]
        assert not list(payload_dir.glob("*.tmp"))  # atomic temp files never survive
    finally:
        access.conn.close()


# -- explicit resync: stale history re-bootstraps instead of degrading forever ----------------
def _message_rows(access: ConnectorAccess, native_id: str) -> list[sqlite3.Row]:
    return access.query(
        "SELECT history_id,event_type,payload_ref,observed_at FROM gmail_observations"
        " WHERE native_message_id=? ORDER BY history_id",
        (native_id,),
    )


def test_stale_history_triggers_real_resync_and_recovers(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        committed, complete = _committed(access)
        assert complete == 1

        # Age the provider window out from under the durable watermark.
        fake.set_history_expired_below(committed + 1)
        stale = _sync(fake, access).incremental(_selection(), owner="reader-a")
        assert stale.resync_required is True
        assert stale.catchup_complete is False  # a 404 is never a clean, empty poll
        assert _committed(access) == (committed, 1)
        failed = _sync(fake, access).resync_markers(_selection())[-1]
        assert failed.status == "failed" and failed.safe_code == "provider_status_404"

        # A new provider record moves the retained window past the old anchor: history serves
        # again and the very next incremental re-bootstraps instead of degrading.
        fake.add_message(_message("m2", labels={OWNER_LABEL}))
        recovered = _sync(fake, access).incremental(_selection(), owner="reader-a")
        assert recovered.resync_required is False
        assert recovered.catchup_complete is True
        new_committed, new_complete = _committed(access)
        assert (new_committed, new_complete) == (committed + 1, 1)
        marker = _sync(fake, access).resync_markers(_selection())[-1]
        assert marker.status == "complete" and marker.safe_code is None
        assert marker.anchor_history_id == committed + 1

        # The connection truly recovered: the next incremental advances and observes normally.
        fake.add_message(_message("m3", labels={OWNER_LABEL}))
        after = _sync(fake, access).incremental(_selection(), owner="reader-a")
        assert after.resync_required is False
        assert after.observations_written == 1
        assert len(_message_rows(access, "m3")) == 1
    finally:
        access.conn.close()


def test_resync_does_not_duplicate_existing_observations(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    fake.add_message(_message("m2", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        before = {mid: _message_rows(access, mid) for mid in ("m1", "m2")}
        assert all(len(rows) == 1 for rows in before.values())

        fake.add_message(_message("m3", labels={OWNER_LABEL}))
        result = _sync(fake, access).resync(_selection(), owner="reader-a")

        assert result.resync_required is False
        assert result.observations_written == 1  # only the message the store had never seen
        for mid, rows in before.items():
            after = _message_rows(access, mid)
            assert len(after) == 1
            assert tuple(after[0]) == tuple(rows[0])  # the committed row is untouched
        assert len(_message_rows(access, "m3")) == 1
        assert _count(access, "gmail_observations") == 3
        assert len(list(_payload_root(store).rglob("*.json"))) == 3
    finally:
        access.conn.close()


def test_resync_preserves_messages_still_selected_and_adds_new_ones(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        original = _message_rows(access, "m1")[0]
        ref = str(original["payload_ref"])
        payload = GmailPayloadStore(_payload_root(store)).read(ref)
        assert payload.native_message_id == "m1"

        fake.add_message(_message("m2", labels={OWNER_LABEL}))
        result = _sync(fake, access).resync(_selection(), owner="reader-a")

        assert result.resync_required is False
        preserved = _message_rows(access, "m1")
        assert len(preserved) == 1 and tuple(preserved[0]) == tuple(original)
        added = _message_rows(access, "m2")
        assert len(added) == 1 and added[0]["event_type"] == "message_added"
        assert GmailPayloadStore(_payload_root(store)).read(str(added[0]["payload_ref"]))
    finally:
        access.conn.close()


def test_resync_never_invents_missing_messages(store: Path) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    fake.add_message(_message("m2", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        original = _message_rows(access, "m1")
        assert len(original) == 1

        # The provider stops serving m1 and publishes no history record for the loss.
        fake.drop_message("m1")
        fake.add_message(_message("m3", labels={OWNER_LABEL}))
        result = _sync(fake, access).resync(_selection(), owner="reader-a")

        assert result.resync_required is False
        assert _message_rows(access, "m1") == original  # no fabricated re-snapshot
        tombstones = access.query(
            "SELECT 1 AS present FROM gmail_observations"
            " WHERE native_message_id='m1' AND event_type='message_deleted'"
        )
        assert tombstones == []  # absence is not a deletion observation
        assert _message_rows(access, "m-ghost") == []
        assert len(_message_rows(access, "m3")) == 1
    finally:
        access.conn.close()


def test_crash_mid_resync_repeats_safely(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    fake.add_message(_message("m2", labels={OWNER_LABEL}))
    access = _access(store)
    try:
        _sync(fake, access).bootstrap(_selection(), owner="reader-a")
        committed_before, complete_before = _committed(access)
        assert complete_before == 1

        crashing = _sync(fake, access)
        original_catchup = crashing._catch_up

        def catch_up_after_late_arrival(*args: object, **kwargs: object) -> object:
            # Arrives after the cohort enumeration but inside the new anchor interval.
            fake.add_message(_message("m3", labels={OWNER_LABEL}))
            return original_catchup(*args, **kwargs)  # type: ignore[arg-type]

        def crash(*args: object, **kwargs: object) -> int:
            raise RuntimeError("simulated crash mid-resync")

        monkeypatch.setattr(crashing, "_catch_up", catch_up_after_late_arrival)
        monkeypatch.setattr(crashing, "_apply_entry", crash)
        with pytest.raises(RuntimeError):
            crashing.resync(_selection(), owner="reader-a")

        # The crashed page committed nothing and the old watermark never moved, so it cannot
        # point past data that was not committed.
        assert _message_rows(access, "m3") == []
        assert _committed(access) == (committed_before, 1)
        assert crashing.resync_markers(_selection())[-1].status == "in_progress"

        # A restart repeats the whole resync; the PK dedupes and the cursor installs once.
        restarted = _sync(fake, access)
        result = restarted.resync(_selection(), owner="reader-a")
        assert result.resync_required is False
        assert _committed(access) == (fake.current_history_id, 1)
        assert len(_message_rows(access, "m3")) == 1
        assert _count(access, "gmail_observations") == 3
        assert [m.status for m in restarted.resync_markers(_selection())] == [
            "in_progress",
            "complete",
        ]
    finally:
        access.conn.close()


def test_competing_resync_exactly_one_wins(store: Path) -> None:
    fake_a = FakeGmailTransport(expected_token=TOKEN)
    fake_a.add_message(_message("m1", labels={OWNER_LABEL}))
    a_access = _access(store)
    b_access = _access(store)
    try:
        sync_a = _sync(fake_a, a_access)
        sync_a.bootstrap(_selection(), owner="reader-a")
        committed = _committed(a_access)[0]
        sync_a.claim("reader-a", _selection())  # A's resync lease is live

        fake_b = FakeGmailTransport(expected_token=TOKEN)
        fake_b.add_message(_message("m1", labels={OWNER_LABEL}))
        sync_b = _sync(fake_b, b_access)
        with pytest.raises(CursorRejected) as raised:
            sync_b.resync(_selection(), owner="reader-b")
        assert raised.value.safe_code == "lease_held_by_active_worker"
        # The loser dispatched nothing, wrote no marker and advanced nothing.
        assert (
            fake_b.profile_calls,
            fake_b.list_calls,
            fake_b.body_calls,
            fake_b.history_calls,
        ) == (0, 0, 0, 0)
        assert sync_b.resync_markers(_selection()) == ()
        assert _committed(a_access)[0] == committed

        # The lease holder still owns the fence and completes the one real resync.
        result = sync_a.resync(_selection(), owner="reader-a")
        assert result.resync_required is False
        markers = sync_a.resync_markers(_selection())
        assert len(markers) == 1 and markers[0].status == "complete"
        assert _committed(a_access)[0] == fake_a.current_history_id
    finally:
        a_access.conn.close()
        b_access.conn.close()


def test_resync_marker_is_recorded(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m1", labels={OWNER_LABEL}))
    access = _access(store)
    clock = _clock()
    sync = _sync(fake, access, clock)
    try:
        sync.bootstrap(_selection(), owner="reader-a")
        fake.add_message(_message("m2", labels={OWNER_LABEL}))
        attempted_at = clock.now_iso()

        original_catchup = sync._catch_up

        def catch_up_then_tick(*args: object, **kwargs: object) -> object:
            # Arrives after enumeration, inside the new anchor interval: the catch-up must apply
            # it before the watermark is installed.
            fake.add_message(_message("m3", labels={OWNER_LABEL}))
            outcome = original_catchup(*args, **kwargs)  # type: ignore[arg-type]
            clock.advance_seconds(5)
            return outcome

        monkeypatch.setattr(sync, "_catch_up", catch_up_then_tick)
        result = sync.resync(_selection(), owner="reader-a")
        assert result.resync_required is False
        assert result.committed_history_id == fake.current_history_id == 3
        assert len(_message_rows(access, "m3")) == 1  # caught up, not skipped by the new anchor
        assert _committed(access) == (3, 1)
        marker = sync.resync_markers(_selection())[-1]
        assert marker.status == "complete"
        assert marker.safe_code is None
        assert marker.attempted_at == attempted_at
        assert marker.finished_at == "2026-10-24T09:00:05Z"
        assert marker.anchor_history_id == 2
        assert marker.committed_history_id == result.committed_history_id

        # A failed attempt is recorded with its safe code only, never provider text.
        monkeypatch.setattr(sync, "_catch_up", original_catchup)
        fake.set_history_expired_below(fake.current_history_id + 1)
        failed = sync.incremental(_selection(), owner="reader-a")
        assert failed.resync_required is True
        assert failed.committed_history_id == 3  # the failed resync moved nothing
        failed_marker = sync.resync_markers(_selection())[-1]
        assert failed_marker.status == "failed"
        assert failed_marker.safe_code == "provider_status_404"
        assert failed_marker.finished_at is not None
    finally:
        access.conn.close()


def test_bootstrap_404_during_catchup_does_not_claim_a_clean_bootstrap(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale cursor during bootstrap catch-up must not install a complete watermark."""
    from probation.connectors.types import HistoryStale
    from probation.packs.mail.connectors.gmail_sync import SyncResult

    fake = FakeGmailTransport()
    access = _access(store)
    try:
        sync = _sync(fake, access)
        monkeypatch.setattr(
            sync,
            "_catch_up",
            lambda *args, **kwargs: SyncResult(
                0, 0, fake.current_history_id, False, resync_required=True
            ),
        )
        result = sync.bootstrap(_selection(), owner="reader-a")
        assert result.resync_required is True
        assert result.catchup_complete is False
        assert _committed(access)[1] == 0
        with pytest.raises(HistoryStale):
            sync.incremental(_selection(), owner="reader-a")
    finally:
        access.conn.close()
