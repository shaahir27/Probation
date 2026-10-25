"""Payload persistence: owner-only ACL, atomic write, relative refs, hash-checked reads.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 12 (frozen). These tests use real Windows ACLs,
the real read connector and the shared fake provider; the store is never mocked. A payload that
cannot be written leaves no observation, and a payload that changed under us is a hard error.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

from probation.connectors import acl as acl_mod
from probation.connectors.types import ConnectorError, NativeRef, SourceObservation, SourceSelection
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.packs.mail.connectors.gmail_mime import parse_message
from probation.packs.mail.connectors.gmail_payloads import GmailPayloadStore, payload_from_parsed
from probation.packs.mail.connectors.gmail_read import GmailReadConnector

CONNECTION = "conn-1"
ACCOUNT = "acct-1"
TOKEN = "read-token"
OWNER_LABEL = "COHORT"
OBSERVED_AT = "2026-10-24T09:05:00Z"
SECTION_12_FIELDS = {
    "native_message_id",
    "thread_id",
    "rfc_message_id",
    "from_addr",
    "to_addr",
    "cc_addrs",
    "subject",
    "body_text",
    "occurred_at",
    "attachment_present",
    "content_hash",
}

requires_windows = pytest.mark.skipif(
    not acl_mod.IS_WINDOWS,
    reason="host must be the Windows target of this connector; ACL proof is real",
)


def _clock() -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC))


def _selection() -> SourceSelection:
    return SourceSelection(
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        selection_revision=1,
        label_ids=(OWNER_LABEL,),
    )


def _message(
    native_id: str = "m-cohort",
    *,
    html: str | None = None,
    attachment: bool = False,
    text: str | None = "hello body text",
) -> _Message:
    return _Message(
        native_id,
        thread_id=f"thread-{native_id}",
        from_addr="alice@sender.test",
        to_addr="bob@owner.test",
        subject=f"body {native_id}",
        date="Tue, 14 Nov 2023 22:13:20 +0000",
        message_id=f"<{native_id}@sender.test>",
        internal_date_ms=1700000000000,
        labels={OWNER_LABEL, "INBOX"},
        text=text,
        html=html,
        attachment=attachment,
    )


def _connector(fake: FakeGmailTransport, store: GmailPayloadStore) -> GmailReadConnector:
    return GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=_clock(),
        owner_label=OWNER_LABEL,
        payloads=store,
    )


def _observe(root: Path, message: _Message) -> tuple[SourceObservation, Path]:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(message)
    connector = _connector(fake, GmailPayloadStore(root, CONNECTION))
    connector.enumerate_cohort(_selection())
    observation = connector.observe(
        NativeRef(CONNECTION, ACCOUNT, message.native_id), observed_at=OBSERVED_AT
    )
    return observation, root


@requires_windows
def test_message_body_is_persisted_and_ref_resolves(tmp_path: Path) -> None:
    observation, root = _observe(tmp_path / "payloads", _message())

    assert observation.payload_ref is not None
    payload = GmailPayloadStore(root).read(observation.payload_ref)  # unbound reader
    assert payload.native_message_id == "m-cohort"
    assert payload.from_addr == "alice@sender.test"
    assert payload.subject == "body m-cohort"
    assert payload.body_text == "hello body text"
    assert payload.content_hash == observation.content_hash
    assert payload.content_hash.startswith("sha256:")
    # The reader recomputes the hash from the file's own fields, not from the observation row.
    document = json.loads((root / observation.payload_ref).read_text(encoding="utf-8"))
    assert document["content_hash"] == observation.content_hash


@requires_windows
def test_payload_ref_is_relative_never_absolute(tmp_path: Path) -> None:
    observation, root = _observe(tmp_path / "payloads", _message())

    ref = observation.payload_ref
    assert ref == f"{CONNECTION}/m-cohort.json"
    assert not Path(ref).is_absolute()
    assert ".." not in Path(ref).parts
    assert (root / ref).is_file()
    assert str(tmp_path) not in ref  # never a local absolute path


@requires_windows
def test_payload_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    observation, root = _observe(tmp_path / "payloads", _message())
    assert observation.payload_ref is not None
    path = root / observation.payload_ref

    document = json.loads(path.read_text(encoding="utf-8"))
    document["subject"] = "tampered under us"
    path.write_text(json.dumps(document), encoding="utf-8")

    reader = GmailPayloadStore(root)
    with pytest.raises(ConnectorError) as excinfo:
        reader.read(observation.payload_ref)
    assert excinfo.value.safe_code == "payload_hash_mismatch"

    path.unlink()
    with pytest.raises(ConnectorError) as missing:
        reader.read(observation.payload_ref)
    assert missing.value.safe_code == "payload_missing"


@requires_windows
def test_payload_contains_no_attachment_or_url_content(tmp_path: Path) -> None:
    html = (
        '<html><body><p>click <a href="https://tracker.example/redirect">here</a></p>'
        '<img src="https://images.example/pixel.png"><script>fetch("https://evil.example")</script>'
        "</body></html>"
    )
    observation, root = _observe(tmp_path / "payloads", _message(html=html, attachment=True))
    assert observation.payload_ref is not None
    raw = (root / observation.payload_ref).read_text(encoding="utf-8")
    document = json.loads(raw)

    assert set(document) == SECTION_12_FIELDS  # exactly the section-12 fields
    assert document["attachment_present"] is True
    assert document["body_text"] == "hello body text"
    for forbidden in (
        "attachment-bytes-not-fetched",
        "note.bin",
        "https://",
        "<a ",
        "<img",
        "<script",
        "tracker.example",
        "images.example",
        "evil.example",
    ):
        assert forbidden not in raw


@requires_windows
def test_payload_ref_rejects_traversal_absolute_and_wrong_extension(tmp_path: Path) -> None:
    reader = GmailPayloadStore(tmp_path / "payloads")
    for ref in (
        "/etc/passwd",
        "C:/windows/system32/config",
        "../escape.json",
        f"{CONNECTION}/../../escape.json",
        f"{CONNECTION}/m-cohort.txt",
        f"{CONNECTION}\\m-cohort.json",
        f"{CONNECTION}//m-cohort.json",
        f"{CONNECTION}/.json",
    ):
        with pytest.raises(ConnectorError):
            reader.read(ref)


def test_payload_from_parsed_hashes_its_own_fields() -> None:
    fake = FakeGmailTransport(expected_token=TOKEN)
    fake.add_message(_message())
    payload = payload_from_parsed(parse_message(fake.messages["m-cohort"].resource(body=True)))
    assert payload.content_hash.startswith("sha256:")
    assert payload.to_addr == ("bob@owner.test",)
    assert payload.occurred_at is not None
