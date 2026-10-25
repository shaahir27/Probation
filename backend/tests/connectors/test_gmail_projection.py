"""D4 temporal projection: an as-of Gmail read never touches the provider (D4-08).

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 2 and 4, docs/FULL_PRODUCT_SPEC.md sections 6
and 7.2 steps 5-6, and docs/CONTRACT.md invariants I-6 (HistoryView only) and I-7. The style follows
``backend/tests/property/test_no_peeking.py``: a pristine prefix is compared field by field against
the same database after the future has happened, at 50 seeded cuts.

Everything here reads only committed ``gmail_observations`` and ``gmail_history_events`` rows.
A projection is bound to the ``api`` connector authority, which owns no write table at all, so a
historical read is proven to be side-effect-free by the store's own authorizer rather than by a
test assertion.
"""

import json
import random
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

from probation.connectors.types import HttpResult, SourceSelection
from probation.core.clock import Clock, format_timestamp, timestamp_key
from probation.core.enums import ClockMode
from probation.db.gmail_store import ConnectorAccess, StoreAccessError, migrate_store, open_store
from probation.packs.base import WorldView
from probation.packs.mail.connectors.gmail_projection import (
    GmailProjector,
    ProjectionError,
)
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_sync import GmailSync

CONNECTION = "conn-1"
ACCOUNT = "acct@test.invalid"
TOKEN = "read-token"
OWNER_LABEL = "COHORT"
BASE = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)
PRE_EXISTING = 12
CUTS = 50
SEED = 4242
# Rows the corpus's terminal divergence commits at its one later knowledge time: the archived
# message re-observed at its advanced history id, the late arrival, and the late sent item.
TERMINAL_FUTURE_ROWS = 3


class ExplodingTransport:
    """A transport that fails the test the moment a projection tries to reach the provider."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(
        self,
        url: str,
        *,
        params: Any = None,
        access_token: str,
    ) -> HttpResult:
        del params, access_token
        self.calls.append(url)
        raise AssertionError(f"a historical read issued a provider call: {url}")

    def post(
        self,
        url: str,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        access_token: str,
    ) -> HttpResult:
        del json_body, data, access_token
        self.calls.append(url)
        raise AssertionError(f"a historical read issued a provider call: {url}")


def _clock() -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=BASE)


def _selection() -> SourceSelection:
    return SourceSelection(
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        selection_revision=1,
        label_ids=(OWNER_LABEL,),
    )


def _message(
    native_id: str,
    *,
    labels: set[str],
    date: str = "Tue, 14 Nov 2023 22:13:20 +0000",
    internal: datetime = datetime(2026, 10, 24, 8, 30, tzinfo=UTC),
) -> _Message:
    return _Message(
        native_id,
        thread_id=f"thread-{native_id}",
        from_addr="alice@sender.test",
        to_addr="bob@owner.test",
        subject=f"subject {native_id}",
        date=date,
        message_id=f"<{native_id}@sender.test>",
        internal_date_ms=int(internal.timestamp() * 1000),
        labels=labels,
        text=f"body of {native_id}",
    )


def _store(path: Path) -> ConnectorAccess:
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    return ConnectorAccess(open_store(path), "ingestor")


def _reader(path: Path) -> ConnectorAccess:
    """The projection authority: it owns no write table, so it cannot mutate while it reads."""
    return ConnectorAccess(open_store(path), "api")


def _snapshot(source: sqlite3.Connection, target: Path) -> Path:
    conn = open_store(target)
    try:
        source.backup(conn)
    finally:
        conn.close()
    return target


def _sync(fake: FakeGmailTransport, access: ConnectorAccess, clock: Clock) -> GmailSync:
    connector = GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=clock,
        owner_label=OWNER_LABEL,
    )
    return GmailSync(
        access=access,
        connector=connector,
        clock=clock,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        owner_label=OWNER_LABEL,
    )


def _projector(
    access: ConnectorAccess,
    clock: Clock,
    transport: Any | None = None,
    engine: sqlite3.Connection | None = None,
) -> GmailProjector:
    reader: GmailReadConnector | None = None
    if transport is not None:
        reader = GmailReadConnector(
            transport,
            connection_id=CONNECTION,
            account_id=ACCOUNT,
            access_token=TOKEN,
            clock=clock,
            owner_label=OWNER_LABEL,
        )
    return GmailProjector(
        access=access,
        clock=clock,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        reader=reader,
        engine=engine,
    )


class _Corpus:
    """A prefix snapshot per cut, the same database after the future, and the expected answers."""

    def __init__(self) -> None:
        self.stamps: list[str] = []
        self.pristine: list[Path] = []
        self.full: Path = Path()
        self.expected: list[dict[str, Any]] = []


def _answer(projection: Any) -> dict[str, Any]:
    """Everything an as-of answer commits to, in directly comparable plain values."""
    return {
        "as_of": projection.as_of,
        "messages": {
            message.native_message_id: message.as_world_record() for message in projection.messages
        },
        "changes": [
            (
                change.native_message_id,
                change.kind,
                change.label_id,
                change.history_id,
                change.observed_at,
            )
            for change in projection.changes
        ],
        "issues": sorted(projection.issues),
    }


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> _Corpus:
    root = tmp_path_factory.mktemp("gmail-projection")
    full_path = root / "full.db"
    access = _store(full_path)
    clock = _clock()
    fake = FakeGmailTransport(expected_token=TOKEN, page_size=5)
    for index in range(PRE_EXISTING):
        fake.add_message(_message(f"m-old-{index}", labels={OWNER_LABEL, "INBOX"}))
    sync = _sync(fake, access, clock)
    sync.bootstrap(_selection(), owner="reader-a")

    corpus = _Corpus()
    corpus.full = full_path
    selection = _selection()
    # One cohort re-scan per minute. Each re-scan is a whole committed page set against the same
    # observation primary key, so a message keeps the knowledge time of the scan that first saw it
    # and the prefix snapshot below is exactly the store as it stood at that instant.
    for index in range(CUTS):
        fake.add_message(_message(f"m-live-{index}", labels={OWNER_LABEL, "INBOX"}))
        clock.advance_seconds(60)
        sync.bootstrap(selection, owner="reader-a")
        stamp = clock.now_iso()
        corpus.stamps.append(stamp)
        corpus.pristine.append(_snapshot(access.conn, root / f"prefix-{index}.db"))

    # The future diverges only in the full store: an earlier message is archived, one is
    # permanently removed from the cohort, another arrives, and a message we sent ourselves
    # appears. None of it may reach an answer already given for an earlier instant.
    fake.modify_labels("m-live-2", remove=("INBOX",))
    fake.delete_message("m-live-5")
    fake.add_message(_message("m-live-late", labels={OWNER_LABEL, "INBOX"}))
    fake.add_message(_message("m-sent-late", labels={OWNER_LABEL, "SENT"}))
    clock.advance_seconds(600)
    sync.bootstrap(selection, owner="reader-a")

    for index, stamp in enumerate(corpus.stamps):
        prefix = _reader(corpus.pristine[index])
        corpus.expected.append(_answer(_projector(prefix, clock).project(stamp)))
    return corpus


def test_historical_read_issues_no_provider_call(corpus: _Corpus) -> None:
    """A transport that raises on any call, and a past projection that still answers exactly."""
    cut = corpus.stamps[7]
    boom = ExplodingTransport()
    projector = _projector(_reader(corpus.pristine[7]), _clock(), transport=boom)
    projection = projector.project(cut)

    assert boom.calls == []
    assert projector.provider_calls == 0
    assert projection.as_of == cut
    assert projection.messages, "the historical projection answered with nothing"
    assert _answer(projection) == corpus.expected[7]

    # The same projector can serve a live diagnostic, so the transport is genuinely wired and
    # the empty counter above is a real guarantee rather than a stub that cannot be called.
    live_fake = FakeGmailTransport(expected_token=TOKEN)
    live_fake.add_message(_message("m1", labels={OWNER_LABEL, "INBOX"}))
    live = _projector(
        _reader(corpus.pristine[0]),
        _clock(),
        transport=live_fake,
    )
    assert live.read_provider_watermark() == 1
    assert live.provider_calls == 1
    with pytest.raises(ProjectionError, match="historical_read_never_polls"):
        live.read_provider_watermark(as_of="2026-10-24T08:59:00Z")


def test_projection_satisfies_the_world_view_seam(corpus: _Corpus) -> None:
    """Gmail projects through ``WorldView``, not a parallel read interface (PACKS_SPEC section 0)."""
    view = _projector(_reader(corpus.pristine[3]), _clock()).view(corpus.stamps[3])
    assert isinstance(view, WorldView)
    records = view.get_messages()
    assert len(records) == PRE_EXISTING + 4
    assert view.get_message("m-live-3") is not None
    assert view.get_message("m-live-4") is None
    # A later cut asked of an earlier view re-reads the store; it never widens the past.
    assert len(view.get_messages(as_of=corpus.stamps[0])) == PRE_EXISTING + 1
    inbox = [row["native_message_id"] for row in view.get_messages(label="INBOX")]
    assert len(inbox) == PRE_EXISTING + 4
    assert "m-live-2" in inbox
    # Gmail history names no actor, so this view can never hand out "user" actions (C9).
    assert view.get_user_actions(item_id="m-live-3", actor="user") == []
    assert view.get_events() == [] and view.get_files() == []


def _future_rows(access: ConnectorAccess, cut: str) -> int:
    """Rows this connection committed strictly after ``cut``: observations and label events."""
    total = 0
    for table in ("gmail_observations", "gmail_history_events"):
        rows = access.query(
            f"SELECT count(*) AS n FROM {table} WHERE observed_at COLLATE UTC_TIMESTAMP > ?",
            (cut,),
        )
        total += int(rows[0]["n"])
    return total


@pytest.mark.parametrize("cut_index", list(range(CUTS)))
def test_future_mutations_leave_every_earlier_answer_identical(
    corpus: _Corpus, cut_index: int
) -> None:
    """V08/no-peeking for Gmail: at 50 seeded cuts the past answers exactly as it did."""
    cut = corpus.stamps[cut_index]
    rng = random.Random(SEED + cut_index)
    later = rng.sample(range(cut_index + 1, CUTS), min(CUTS - cut_index - 1, 4))
    rows = corpus.expected  # the prefix answers, computed once for every cut

    # The full store really does hold a different future past this cut; otherwise the comparison
    # would be a prefix against itself and would prove nothing.
    full = _reader(corpus.full)
    future = _future_rows(full, cut)
    assert future > 0, f"cut {cut_index}: no future left to mutate"

    projection = _projector(full, _clock()).project(cut)
    answer = _answer(projection)
    want = rows[cut_index]
    assert answer["as_of"] == want["as_of"]
    assert answer["issues"] == want["issues"]
    assert answer["changes"] == want["changes"], (
        f"cut {cut_index} (t={cut}): changes at or before the cut differ from the prefix answer"
    )
    assert answer["messages"].keys() == want["messages"].keys(), (
        f"cut {cut_index} (t={cut}): {len(want['messages'])} pre-cut messages became "
        f"{len(answer['messages'])}"
    )
    for native_id, want_row in want["messages"].items():
        got_row = answer["messages"][native_id]
        assert got_row == want_row, (
            f"cut {cut_index} (t={cut}): message {native_id} changed in the past: "
            + "; ".join(
                f"{key}: {want_row[key]!r} -> {got_row[key]!r}"
                for key in sorted(want_row)
                if got_row[key] != want_row[key]
            )
        )
    # Every sampled later knowledge time really is after this cut, and its rows really are in the
    # full store and not in the prefix, so the comparison had a future to hide from the past. The
    # prefix is a snapshot frozen at this cut, so the future lives in the full store by
    # construction: asserting rows after a later stamp *in the prefix* would assert the snapshot
    # is not a past at all. What must hold is the gap itself — the full store carries rows at
    # every later knowledge time, and the prefix carries none of them.
    prefix = _reader(corpus.pristine[cut_index])
    assert _future_rows(prefix, cut) == 0, "the prefix snapshot holds rows from after its own cut"
    for index in later:
        assert timestamp_key(corpus.stamps[index]) > timestamp_key(cut)
        assert _future_rows(full, corpus.stamps[index]) > 0
        assert _future_rows(prefix, corpus.stamps[index]) == 0
    del prefix
    # Each scan after this cut committed exactly one fresh observation at its own knowledge time
    # (re-scans of unchanged messages dedupe on the observation primary key), and the terminal
    # divergence committed exactly TERMINAL_FUTURE_ROWS more. The exact count proves both that a
    # real future exists to hide and that no re-scan leaked a duplicate row into it.
    assert future == (CUTS - 1 - cut_index) + TERMINAL_FUTURE_ROWS


def test_three_times_stay_distinct(tmp_path: Path) -> None:
    """Occurrence, provider position and local knowledge are three different things (I-6/I-7)."""
    occurrence = datetime(2026, 10, 24, 8, 30, tzinfo=UTC)
    knowledge = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
    access = _store(tmp_path / "times.db")
    clock = Clock(mode=ClockMode.REPLAY, initial_time=knowledge)
    fake = FakeGmailTransport(expected_token=TOKEN)
    # A Date header from 2023 on a message the provider says occurred minutes ago.
    fake.add_message(
        _message(
            "m-old-header",
            labels={OWNER_LABEL, "INBOX"},
            date="Tue, 14 Nov 2023 22:13:20 +0000",
            internal=occurrence,
        )
    )
    _sync(fake, access, clock).bootstrap(_selection(), owner="reader-a")

    projection = _projector(_reader(tmp_path / "times.db"), clock).project()
    (message,) = projection.messages
    assert message.occurrence_time == format_timestamp(occurrence)
    assert message.known_at == format_timestamp(knowledge)
    assert message.provider_sequence > 0
    assert message.occurrence_claimed is True
    assert len({message.occurrence_time, message.known_at, str(message.provider_sequence)}) == 3
    # The Date header said 2023. Nothing the projection emits carries any time but the provider
    # occurrence and the local knowledge instant: the store keeps a content hash and a payload
    # reference, never a header or a body, so there is no Date to confuse and no text to invent.
    item = message.as_raw_item()
    assert item is not None
    assert "2023" not in json.dumps(item, sort_keys=True)
    assert "body" not in json.loads(item["payload_json"])
    assert json.loads(item["payload_json"])["payload_ref"] == message.payload_ref
    assert item["known_at"] == format_timestamp(knowledge)
    assert item["occurred_at"] == format_timestamp(occurrence)

    # Between occurrence and knowledge the message had happened but was not yet knowable.
    early = _projector(_reader(tmp_path / "times.db"), clock).project(format_timestamp(occurrence))
    assert early.messages == ()
    assert early.situation_candidates() == ()


def test_occurrence_provenance_recorded_not_assumed(tmp_path: Path) -> None:
    """An occurrence the store cannot vouch for is reported as unknown, never as provider truth."""
    access = _store(tmp_path / "prov.db")
    clock = _clock()
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message("m-claimed", labels={OWNER_LABEL, "INBOX"}))
    _sync(fake, access, clock).bootstrap(_selection(), owner="fake")
    access.write(
        "gmail_observations",
        """INSERT INTO gmail_observations VALUES
           (?,?,'m-unclaimed',900,'message_added','sha256:c','sha256:v',?,?,'unknown',
            'thread-x','<m-unclaimed@sender.test>','data/private/gmail/x','["INBOX"]',0)""",
        (
            CONNECTION,
            ACCOUNT,
            format_timestamp(clock.now()),
            format_timestamp(datetime(2020, 1, 1, tzinfo=UTC)),
        ),
    )

    records = {
        message.native_message_id: message
        for message in _projector(_reader(tmp_path / "prov.db"), clock).project().messages
    }
    assert records["m-claimed"].occurrence_claimed is True
    unclaimed = records["m-unclaimed"]
    assert unclaimed.occurrence_provenance == "unknown"
    assert unclaimed.occurrence_time is None
    assert unclaimed.occurrence_claimed is False
    # Nothing to anchor an occurrence to: knowledge time carries the record, silently and honestly.
    assert unclaimed.known_at == format_timestamp(clock.now())
    assert unclaimed.as_raw_item()["occurred_at"] == unclaimed.known_at
    assert (
        "occurrence_unverified:m-unclaimed"
        in _answer(_projector(_reader(tmp_path / "prov.db"), clock).project())["issues"]
    )


def test_projection_writes_nothing(corpus: _Corpus) -> None:
    """Reading is bound to a connector authority that owns no writable table at all."""
    reader = _reader(corpus.full)
    assert reader.allowed_tables == frozenset()
    with pytest.raises(StoreAccessError, match="may not write"):
        reader.write("gmail_observations", "DELETE FROM gmail_observations")
    with pytest.raises(StoreAccessError, match="may not write"):
        reader.write("gmail_history_events", "UPDATE gmail_history_events SET label_id='X'")
    before = _store_digest(reader)
    projection = _projector(reader, _clock()).project()
    assert projection.messages
    after = _store_digest(_reader(corpus.full))
    assert before == after, "a projection altered the committed observation store"


def _store_digest(access: ConnectorAccess) -> str:
    parts: list[str] = []
    for table in ("gmail_observations", "gmail_history_events", "gmail_sync_cursors"):
        rows = access.query(f"SELECT * FROM {table} ORDER BY rowid")
        parts.append(json.dumps([tuple(row) for row in rows], sort_keys=True, default=str))
    return json.dumps(parts)
