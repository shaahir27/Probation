"""Bounded, safe MIME parsing: each hard limit fails closed, and headers cannot be injected.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1 (I-24/T16) and 4. These are pure offline
tests over the stdlib parser; nothing here touches the network or a real account.
"""

from base64 import urlsafe_b64encode
from typing import Any

import pytest

from probation.connectors.types import BoundedInputExceeded
from probation.packs.mail.connectors.gmail_mime import (
    MimeLimits,
    UnparseableHeader,
    parse_message,
)


def _b64(text: str) -> str:
    return urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _header(name: str, value: str) -> dict[str, str]:
    return {"name": name, "value": value}


def _text_part(text: str, mime: str = "text/plain") -> dict[str, Any]:
    return {
        "mimeType": mime,
        "headers": [_header("Content-Type", f"{mime}; charset=UTF-8")],
        "body": {"data": _b64(text)},
    }


def _message(
    parts: list[dict[str, Any]],
    *,
    native_id: str = "msg-1",
    thread_id: str = "thread-1",
    history_id: int = 42,
    headers: list[dict[str, str]] | None = None,
    labels: list[str] | None = None,
    internal_date: str = "1700000000000",
) -> dict[str, Any]:
    base_headers = [
        _header("From", "Alice <alice@sender.test>"),
        _header("To", "bob@owner.test"),
        _header("Subject", "Weekly sync"),
        _header("Date", "Tue, 14 Nov 2023 22:13:20 +0000"),
        _header("Message-ID", "<rfc-unique@sender.test>"),
    ]
    top = {
        "headers": base_headers if headers is None else headers,
        "mimeType": "multipart/alternative",
        "parts": parts,
    }
    return {
        "id": native_id,
        "threadId": thread_id,
        "historyId": history_id,
        "labelIds": labels if labels is not None else ["INBOX"],
        "internalDate": internal_date,
        "payload": top,
    }


def test_plain_text_is_preferred_over_html() -> None:
    parsed = parse_message(
        _message(
            [
                _text_part("Visible plain body"),
                _text_part("<b>Visible html body</b>", "text/html"),
            ]
        )
    )
    assert parsed.text == "Visible plain body"


def test_html_only_is_reduced_without_scripts_or_execution() -> None:
    parsed = parse_message(
        _message(
            [
                _text_part(
                    "<html><body><script>alert('x')</script>"
                    "<img src='https://remote.test/pixel.png'><p>Real text here</p></body></html>",
                    "text/html",
                )
            ]
        )
    )
    assert "Real text here" in parsed.text
    assert "alert" not in parsed.text
    assert "remote.test" not in parsed.text


def test_identifiers_stay_separate_and_never_substitute() -> None:
    parsed = parse_message(
        _message([_text_part("hi")], native_id="native-9", thread_id="thread-9", history_id=7)
    )
    assert parsed.native_message_id == "native-9"
    assert parsed.thread_id == "thread-9"
    assert parsed.rfc_message_id == "<rfc-unique@sender.test>"
    assert parsed.history_id == 7
    assert parsed.native_message_id != parsed.rfc_message_id != parsed.thread_id


def test_attachment_presence_recorded_without_body_fetch() -> None:
    attachment = {
        "mimeType": "application/pdf",
        "filename": "report.pdf",
        "headers": [_header("Content-Disposition", 'attachment; filename="report.pdf"')],
        "body": {"data": _b64("ATTACHMENT-BYTES-SHOULD-NOT-LEAK-INTO-TEXT")},
    }
    parsed = parse_message(_message([_text_part("Please see attached."), attachment]))
    assert parsed.has_attachment is True
    assert "ATTACHMENT-BYTES" not in parsed.text
    assert parsed.text == "Please see attached."


def test_in_reply_to_and_references_preserved() -> None:
    headers = [
        _header("From", "carol@sender.test"),
        _header("Message-ID", "<reply@sender.test>"),
        _header("In-Reply-To", "<orig@sender.test>"),
        _header("References", "<a@sender.test> <b@sender.test>"),
    ]
    parsed = parse_message(_message([_text_part("ok")], headers=headers))
    assert parsed.in_reply_to == "<orig@sender.test>"
    assert parsed.references == ("<a@sender.test>", "<b@sender.test>")


def test_cc_recipients_are_preserved_and_guarded() -> None:
    headers = [
        _header("From", "Alice <alice@sender.test>"),
        _header("To", "bob@owner.test"),
        _header("Cc", "carol@cc.test, dave@cc.test"),
        _header("Subject", "with cc"),
        _header("Message-ID", "<cc@sender.test>"),
    ]
    parsed = parse_message(_message([_text_part("hi")], headers=headers))
    assert parsed.cc_addrs == ("carol@cc.test", "dave@cc.test")
    assert parsed.header_map()["Cc"] == "carol@cc.test, dave@cc.test"
    # A Cc carrying CR/LF is rejected before it can be emitted as a header.
    poisoned = list(headers)
    poisoned[2] = _header("Cc", "carol@cc.test\r\nBcc: attacker@evil.test")
    with pytest.raises(UnparseableHeader):
        parse_message(_message([_text_part("hi")], headers=poisoned))


def test_occurrence_time_from_internal_date_not_from_headers() -> None:
    parsed = parse_message(_message([_text_part("hi")], internal_date="1700000000000"))
    assert parsed.occurrence_time.startswith("2023-11-14")
    assert parsed.date is not None  # Date header preserved but never used as knowledge time


def test_sender_fail_closed_when_missing() -> None:
    headers = [_header("Subject", "no sender"), _header("To", "bob@owner.test")]
    with pytest.raises(UnparseableHeader):
        parse_message(_message([_text_part("hi")], headers=headers))


def test_sender_fail_closed_when_ambiguous() -> None:
    headers = [_header("From", "definitely not an address"), _header("To", "bob@owner.test")]
    with pytest.raises(UnparseableHeader):
        parse_message(_message([_text_part("hi")], headers=headers))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Subject", "Report\r\nX-Injected: evil"),
        ("From", "alice@sender.test\r\nBcc: attacker@evil.test"),
        ("Message-ID", "<a@x.test>\r\nInjected: yes"),
    ],
)
def test_header_injection_is_rejected(field: str, value: str) -> None:
    headers = {
        "From": "alice@sender.test",
        "To": "bob@owner.test",
        "Subject": "clean",
        "Message-ID": "<ok@sender.test>",
    }
    headers[field] = value
    parsed_headers = [_header(name, sent_value) for name, sent_value in headers.items()]
    with pytest.raises(UnparseableHeader):
        parse_message(_message([_text_part("hi")], headers=parsed_headers))


def test_sent_message_is_observed_as_sent_not_incoming() -> None:
    parsed = parse_message(
        _message(
            [_text_part("sent")],
            labels=["SENT"],
            headers=[
                _header("From", "me@owner.test"),
                _header("Message-ID", "<s@x.test>"),
            ],
        )
    )
    assert parsed.is_sent is True


# -- one dedicated test per hard limit ------------------------------------------------------
def test_mime_limits_raw_bytes_exceeded() -> None:
    limits = MimeLimits(max_raw_bytes=4)
    with pytest.raises(BoundedInputExceeded) as exc:
        parse_message(_message([_text_part("a longer body than four bytes")]), limits=limits)
    assert exc.value.safe_code == "mime_raw_bytes"


def test_mime_limits_depth_exceeded() -> None:
    deep: dict[str, Any] = _text_part("innermost")
    for _ in range(5):
        deep = {"mimeType": "multipart/mixed", "headers": [], "parts": [deep]}
    with pytest.raises(BoundedInputExceeded) as exc:
        parse_message(_message([deep]), limits=MimeLimits(max_depth=2))
    assert exc.value.safe_code == "mime_depth"


def test_mime_limits_part_count_exceeded() -> None:
    parts = [_text_part(f"chunk {index}") for index in range(6)]
    with pytest.raises(BoundedInputExceeded) as exc:
        parse_message(_message(parts), limits=MimeLimits(max_parts=3))
    assert exc.value.safe_code == "mime_part_count"


def test_mime_limits_text_chars_exceeded() -> None:
    long_text = "x" * 500
    with pytest.raises(BoundedInputExceeded) as exc:
        parse_message(_message([_text_part(long_text)]), limits=MimeLimits(max_text_chars=100))
    assert exc.value.safe_code == "mime_text_chars"
