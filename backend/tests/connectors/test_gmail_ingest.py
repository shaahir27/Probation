"""The D4 bridge: committed Gmail observations reach the existing engine ingest path.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 4, 7, 11 (rows 19 and 30) and 12, docs/CONTRACT.md
section 3 and I-6/I-7. Real private store, real ingestor authority, real role-bound engine: an
arrival becomes one raw item and one pack-built situation carrying the persisted sender, subject and
body; SENT/labels/tombstones never become an arrival; reruns and a crash between commits repeat
safely; out-of-cohort content never appears. A missing, escaping or hash-mismatched payload raises
a safe code and stores no row. The bootstrap case uses the real Windows payload store end to end;
the unit cases inject the reader so the bridge's own ref and hash checks are exercised directly.
"""

import ast
import inspect
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

import probation.packs.mail.connectors.gmail_ingest as bridge_module
from probation.connectors.types import (
    ConnectorError,
    MessagePayload,
    PayloadReader,
    SourceSelection,
)
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.db.access import Role, RoleAccess
from probation.db.connection import get_connection, get_role_connection, init_db
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
from probation.db.guards import AccessError
from probation.packs.mail.connectors.gmail_ingest import GmailIngestBridge
from probation.packs.mail.connectors.gmail_payloads import GmailPayloadStore
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_sync import GmailSync

CONNECTION = "conn-1"
ACCOUNT = "acct@test.invalid"
TOKEN = "read-token"
OWNER_LABEL = "COHORT"
NOW = "2026-10-24T09:00:00Z"
OCCURRED_AT = "2026-10-24T08:30:00Z"
BASE = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)

_OBSERVATION = """INSERT INTO gmail_observations
 (connection_id,account_id,native_message_id,history_id,event_type,content_hash,version_hash,
  observed_at,occurrence_time,occurrence_provenance,thread_id,rfc_message_id,payload_ref,
  label_ids,is_sent) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""

_LABEL_EVENT = """INSERT INTO gmail_history_events
 (connection_id,account_id,history_id,native_message_id,label_id,event_type,observed_at)
 VALUES(?,?,?,?,?,?,?)"""

_ZERO_TABLES = ("proposals", "drafts", "outcomes", "ledger", "actions", "exposure_log", "llm_cache")


class _Payloads:
    """The persisted content the read path would hand the bridge through its injected reader."""

    def __init__(self) -> None:
        self.stored: dict[str, MessagePayload] = {}
        self.reads: list[str] = []

    def put(self, payload: MessagePayload) -> str:
        ref = f"{CONNECTION}/{payload.native_message_id}.json"
        self.stored[ref] = payload
        return ref

    def read(self, payload_ref: str) -> MessagePayload:
        self.reads.append(payload_ref)
        if payload_ref not in self.stored:
            raise ConnectorError("payload_missing")
        return self.stored[payload_ref]


def _payload(native_id: str, *, content_hash: str | None = None) -> MessagePayload:
    return MessagePayload(
        native_message_id=native_id,
        thread_id=f"thread-{native_id}",
        rfc_message_id=f"<{native_id}@sender.test>",
        from_addr="alice@sender.test",
        to_addr=("owner@example.test",),
        cc_addrs=("carol@example.test",),
        subject=f"subject {native_id}",
        body_text=f"body of {native_id}",
        occurred_at=OCCURRED_AT,
        attachment_present=False,
        content_hash=f"sha256:content-{native_id}" if content_hash is None else content_hash,
    )


def _bridge(
    store: ConnectorAccess,
    engine: sqlite3.Connection,
    payloads: PayloadReader,
    clock: Clock | None = None,
) -> GmailIngestBridge:
    return GmailIngestBridge(
        access=store,
        engine=engine,
        clock=clock or Clock(mode=ClockMode.REPLAY, initial_time=BASE),
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        payloads=payloads,
    )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "gmail_metadata.db"
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    return path


@pytest.fixture
def store(store_path: Path) -> Iterator[ConnectorAccess]:
    access = ConnectorAccess(open_store(store_path), "ingestor")
    try:
        yield access
    finally:
        access.conn.close()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "engine.db"
    init_db(path)
    conn = get_role_connection(path, Role.INGESTOR)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def payloads() -> _Payloads:
    return _Payloads()


def _commit_observation(
    store: ConnectorAccess,
    native_id: str,
    payloads: _Payloads,
    *,
    event_type: str = "message_added",
    is_sent: int = 0,
    history_id: int = 1,
    labels: tuple[str, ...] = ("INBOX",),
    ref: str | None = None,
    content_hash: str | None = None,
) -> None:
    if ref is None:
        record = _payload(native_id)
        payload_ref: str | None = payloads.put(record)
        digest = content_hash or record.content_hash
    else:
        payload_ref = ref
        digest = content_hash or f"sha256:content-{native_id}"
    if event_type == "message_deleted":
        payload_ref = None
    store.write(
        "gmail_observations",
        _OBSERVATION,
        (
            CONNECTION,
            ACCOUNT,
            native_id,
            history_id,
            event_type,
            digest,
            f"sha256:version-{native_id}-{history_id}",
            NOW,
            OCCURRED_AT,
            "provider_occurrence",
            f"thread-{native_id}",
            f"<{native_id}@sender.test>",
            payload_ref,
            json.dumps(list(labels)),
            is_sent,
        ),
    )


def _label_event(
    store: ConnectorAccess,
    native_id: str,
    *,
    added: bool = True,
    history_id: int = 2,
    label: str = "INBOX",
) -> None:
    store.write(
        "gmail_history_events",
        _LABEL_EVENT,
        (
            CONNECTION,
            ACCOUNT,
            history_id,
            native_id,
            label,
            "labelAdded" if added else "labelRemoved",
            NOW,
        ),
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])


def _source_refs(conn: sqlite3.Connection) -> set[str]:
    return {str(row["source_ref"]) for row in conn.execute("SELECT source_ref FROM raw_items")}


def _fake_message(native_id: str, labels: set[str]) -> _Message:
    return _Message(
        native_id,
        thread_id=f"thread-{native_id}",
        from_addr="alice@sender.test",
        to_addr="owner@example.test",
        subject=f"subject {native_id}",
        date="Tue, 14 Nov 2023 22:13:20 +0000",
        message_id=f"<{native_id}@sender.test>",
        internal_date_ms=1700000000000,
        labels=labels,
        text=f"body of {native_id}",
    )


def _bootstrap(store: ConnectorAccess, clock: Clock, *messages: _Message) -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    for message in messages:
        fake.add_message(message)
    connector = GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=clock,
        owner_label=OWNER_LABEL,
    )
    selection = SourceSelection(
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        selection_revision=1,
        label_ids=(OWNER_LABEL,),
    )
    GmailSync(
        access=store,
        connector=connector,
        clock=clock,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        owner_label=OWNER_LABEL,
    ).bootstrap(selection, owner="reader-a")


def test_incoming_message_creates_raw_item_and_situation(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-in", payloads)
    before = _count(store.conn, "gmail_observations")
    result = _bridge(store, engine, payloads).run()

    assert result.raw_items_stored == 1
    assert _count(engine, "raw_items") == 1
    raw = engine.execute("SELECT * FROM raw_items").fetchone()
    assert raw["source_ref"] == "m-in"  # native id, never the history id or RFC Message-ID
    assert raw["source_id"] == f"gmail-source:{CONNECTION}"
    assert raw["pack"] == "mail" and raw["item_kind"] == "mail_in"
    assert raw["known_at"] == NOW
    payload = json.loads(raw["payload_json"])
    assert payload["labels"] == ["INBOX"]
    assert payload["message_id"] == "<m-in@sender.test>"

    assert _count(engine, "situations") == 1
    situation = engine.execute("SELECT * FROM situations").fetchone()
    assert situation["raw_item_id"] == raw["id"]
    assert situation["pack"] == "mail" and situation["family"] == "email_action"

    assert _count(engine, "sources") == 1
    source = engine.execute("SELECT * FROM sources").fetchone()
    assert source["kind"] == "gmail_live" and source["pack"] == "mail"
    assert source["ref"] == ACCOUNT
    # The bridge only reads the private store; it never observes or advances anything.
    assert _count(store.conn, "gmail_observations") == before


def test_situation_carries_real_sender_subject_and_body(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-in", payloads)
    assert _bridge(store, engine, payloads).run().raw_items_stored == 1

    content = json.loads(engine.execute("SELECT payload_json FROM raw_items").fetchone()[0])
    assert content["from"] == "alice@sender.test"
    assert content["to"] == "owner@example.test"
    assert content["cc"] == "carol@example.test"
    assert content["subject"] == "subject m-in"
    assert content["body"] == "body of m-in"
    assert content["thread_id"] == "thread-m-in"
    assert content["message_id"] == "<m-in@sender.test>"

    situation = engine.execute("SELECT * FROM situations").fetchone()
    assert situation["sender_key"] == "alice@sender.test"
    assert situation["occurred_at"] == OCCURRED_AT
    assert situation["redacted_text"] == "Subject: subject m-in\n\nbody of m-in"
    assert payloads.reads == [f"{CONNECTION}/m-in.json"]


def test_missing_payload_fails_closed_and_creates_no_raw_item(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-absent", payloads, ref=f"{CONNECTION}/m-absent.json")

    with pytest.raises(ConnectorError) as excinfo:
        _bridge(store, engine, payloads).run()

    assert excinfo.value.safe_code == "payload_missing"
    assert str(excinfo.value) == "payload_missing"  # a safe code, never message content
    assert _count(engine, "raw_items") == 0
    assert _count(engine, "situations") == 0


def test_payload_hash_mismatch_fails_closed(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    ref = payloads.put(_payload("m-hash"))
    _commit_observation(store, "m-hash", payloads, ref=ref, content_hash="sha256:committed-other")

    with pytest.raises(ConnectorError) as excinfo:
        _bridge(store, engine, payloads).run()

    assert excinfo.value.safe_code == "payload_hash_mismatch"
    assert _count(engine, "raw_items") == 0
    assert _count(engine, "situations") == 0


@pytest.mark.parametrize(
    "ref",
    [
        f"../{CONNECTION}/m-escape.json",
        f"{CONNECTION}/../m-escape.json",
        f"/absolute/{CONNECTION}/m-escape.json",
        f"C:/absolute/{CONNECTION}/m-escape.json",
        f"{CONNECTION}\\m-escape.json",
    ],
)
def test_payload_ref_escape_is_rejected(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads, ref: str
) -> None:
    _commit_observation(store, "m-escape", payloads, ref=ref)

    with pytest.raises(ConnectorError) as excinfo:
        _bridge(store, engine, payloads).run()

    assert excinfo.value.safe_code == "payload_ref_escapes_root"
    assert payloads.reads == []  # the reader is never asked to open an escaping ref
    assert _count(engine, "raw_items") == 0


def test_sent_and_label_events_still_create_nothing(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-sent", payloads, event_type="sent_observed", is_sent=1)
    _label_event(store, "m-label", added=True)
    _commit_observation(store, "m-deleted", payloads, event_type="message_deleted", history_id=3)

    result = _bridge(store, engine, payloads).run()

    assert (result.raw_items_stored, result.situations_built) == (0, 0)
    assert _count(engine, "raw_items") == 0
    assert _count(engine, "situations") == 0
    assert payloads.reads == []  # an exclusion never triggers a content read


def test_reingest_is_idempotent_with_content(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-in", payloads)
    bridge = _bridge(store, engine, payloads)
    assert bridge.run().raw_items_stored == 1
    content = json.loads(engine.execute("SELECT payload_json FROM raw_items").fetchone()[0])
    situation = engine.execute("SELECT redacted_text FROM situations").fetchone()
    assert content["body"] == "body of m-in"
    assert "body of m-in" in situation["redacted_text"]

    second = bridge.run()
    assert (second.raw_items_stored, second.situations_built) == (0, 0)
    assert _count(engine, "raw_items") == 1
    assert _count(engine, "situations") == 1


def test_sent_observation_never_creates_incoming_situation(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-out", payloads, event_type="sent_observed", is_sent=1)
    _commit_observation(store, "m-in", payloads)
    _bridge(store, engine, payloads).run()

    assert _source_refs(engine) == {"m-in"}
    assert _count(engine, "raw_items") == 1
    assert _count(engine, "situations") == 1
    kinds = {str(row["item_kind"]) for row in engine.execute("SELECT item_kind FROM raw_items")}
    assert kinds == {"mail_in"}


def test_label_event_and_tombstone_create_no_new_item(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m1", payloads)
    _label_event(store, "m1", added=False, history_id=2, label="INBOX")
    _label_event(store, "m1", added=True, history_id=3, label="IMPORTANT")
    _label_event(store, "m-label-only", added=True, history_id=4)  # never fetched: no snapshot
    _commit_observation(store, "m-deleted", payloads, event_type="message_deleted", history_id=5)

    _bridge(store, engine, payloads).run()
    assert _source_refs(engine) == {"m1"}
    assert _count(engine, "situations") == 1

    # A later label change about the same message must not invent a second decision item.
    _label_event(store, "m1", added=True, history_id=6, label="STARRED")
    result = _bridge(store, engine, payloads).run()
    assert result.raw_items_stored == 0
    assert _count(engine, "raw_items") == 1
    assert _count(engine, "situations") == 1


def test_reingest_is_idempotent(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-in", payloads)
    bridge = _bridge(store, engine, payloads)
    first = bridge.run()
    second = bridge.run()

    assert (first.raw_items_stored, first.situations_built) == (1, 1)
    assert (second.raw_items_stored, second.situations_built) == (0, 0)
    assert _count(engine, "raw_items") == 1
    assert _count(engine, "situations") == 1
    assert _count(engine, "sources") == 1


def test_crash_between_item_and_situation_repeats_safely(
    store: ConnectorAccess,
    engine: sqlite3.Connection,
    payloads: _Payloads,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit_observation(store, "m-in", payloads)
    bridge = _bridge(store, engine, payloads)

    def boom(conn: sqlite3.Connection) -> int:
        del conn
        raise RuntimeError("simulated crash after the raw item committed")

    with monkeypatch.context() as patch:
        patch.setattr(bridge_module, "ingest_situations", boom)
        with pytest.raises(RuntimeError):
            bridge.run()

    # The arrival is durable even though extraction never ran.
    assert _count(engine, "raw_items") == 1
    assert _count(engine, "situations") == 0

    second = bridge.run()
    assert second.raw_items_stored == 0
    assert _count(engine, "raw_items") == 1
    assert _count(engine, "situations") == 1


def test_out_of_cohort_never_reaches_engine(
    store: ConnectorAccess, engine: sqlite3.Connection, store_path: Path
) -> None:
    clock = Clock(mode=ClockMode.REPLAY, initial_time=BASE)
    _bootstrap(
        store,
        clock,
        _fake_message("m-in", {OWNER_LABEL, "INBOX"}),
        _fake_message("m-stranger", {"INBOX"}),  # no owner label: out of cohort upstream
    )
    stored_ids = {
        str(row["native_message_id"])
        for row in store.query("SELECT DISTINCT native_message_id FROM gmail_observations")
    }
    assert stored_ids == {"m-in"}

    # The real payload store written by bootstrap, read back through the bridge, end to end.
    reader = GmailPayloadStore(store_path.parent / "payloads", CONNECTION)
    _bridge(store, engine, reader, clock).run()
    assert _source_refs(engine) == {"m-in"}
    assert "m-stranger" not in _source_refs(engine)
    situation = engine.execute("SELECT * FROM situations").fetchone()
    assert situation["sender_key"] == "alice@sender.test"
    assert "Subject: subject m-in" in situation["redacted_text"]
    assert "body of m-in" in situation["redacted_text"]


def test_bridge_requires_ingestor_bound_connection(
    store_path: Path,
    store: ConnectorAccess,
    engine: sqlite3.Connection,
    payloads: _Payloads,
    tmp_path: Path,
) -> None:
    wrong_store = ConnectorAccess(open_store(store_path), "api")
    try:
        with pytest.raises(ConnectorError):
            _bridge(wrong_store, engine, payloads)
    finally:
        wrong_store.conn.close()

    unbound = get_connection(":memory:")
    try:
        with pytest.raises(ValueError):
            _bridge(store, unbound, payloads)
    finally:
        unbound.close()

    path = tmp_path / "wrong_role.db"
    init_db(path)
    brain = get_role_connection(path, Role.BRAIN)
    try:
        with pytest.raises(ValueError):
            _bridge(store, brain, payloads)
    finally:
        brain.close()


def test_bridge_cannot_write_a_proposal(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-in", payloads)
    _bridge(store, engine, payloads).run()

    assert all(_count(engine, table) == 0 for table in _ZERO_TABLES)
    with pytest.raises(AccessError):
        RoleAccess(engine, Role.INGESTOR).execute_write(
            "proposals", "INSERT INTO proposals (id) VALUES (?)", ("p-1",)
        )
    assert _count(engine, "proposals") == 0


def test_redaction_and_llm_boundary_untouched(
    store: ConnectorAccess, engine: sqlite3.Connection, payloads: _Payloads
) -> None:
    _commit_observation(store, "m-in", payloads)
    _bridge(store, engine, payloads).run()

    # The bridge stores the committed metadata and payload content verbatim; redaction belongs to
    # the pipeline, and the pack-built situation proves the existing pipeline still owns it.
    raw = engine.execute("SELECT payload_json FROM raw_items").fetchone()
    payload = json.loads(raw["payload_json"])
    assert payload["rfc_message_id"] == "<m-in@sender.test>"
    assert payload["message_id"] == "<m-in@sender.test>"
    situation = engine.execute("SELECT * FROM situations").fetchone()
    assert (situation["sender_key"], situation["redacted_text"]) == (
        "alice@sender.test",
        "Subject: subject m-in\n\nbody of m-in",
    )

    # No spend, no proposal and no cache row: the bridge called no model.
    assert all(_count(engine, table) == 0 for table in _ZERO_TABLES)
    # No LLM, redaction or wall-clock dependency is imported by the bridge at all.
    tree = ast.parse(inspect.getsource(bridge_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any(name.startswith("probation.llm") for name in imported)
    assert "datetime" not in imported and "time" not in imported
