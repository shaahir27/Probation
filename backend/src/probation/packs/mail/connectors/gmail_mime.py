"""Bounded, safe MIME/header parsing for observed Gmail messages. Stdlib only.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1 (T16/I-24) and 4, and
docs/FULL_PRODUCT_SPEC.md section 7.2 step 2. Every limit is a hard ceiling that fails
closed by raising ``BoundedInputExceeded``; a partial parse is never returned. Sender and
header parsing that is ambiguous or malformed raises a typed ``UnparseableHeader`` so the
caller emits no observation. Nothing here fetches an attachment, a remote image, or any URL
found inside message content — parsing is offline and byte-bounded only.
"""

from base64 import urlsafe_b64decode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

from probation.connectors.types import BoundedInputExceeded, ConnectorError
from probation.core.clock import format_timestamp

MAX_RAW_BYTES = 512 * 1024
MAX_MIME_DEPTH = 16
MAX_PART_COUNT = 256
MAX_TEXT_CHARS = 200_000


class UnparseableHeader(ConnectorError):
    """A required header could not be parsed unambiguously; the caller emits no observation."""


@dataclass(frozen=True)
class MimeLimits:
    """Approved ceilings. Defaults are the released hard limits; tests pass tighter values."""

    max_raw_bytes: int = MAX_RAW_BYTES
    max_depth: int = MAX_MIME_DEPTH
    max_parts: int = MAX_PART_COUNT
    max_text_chars: int = MAX_TEXT_CHARS


DEFAULT_LIMITS = MimeLimits()

_MULTIPART_PREFIX = "multipart/"


@dataclass(frozen=True)
class ParsedMessage:
    """Preserved, header-injection-safe view of one message. Never carries raw HTML bytes."""

    native_message_id: str
    thread_id: str | None
    rfc_message_id: str | None
    history_id: int
    from_addr: str
    to_addrs: tuple[str, ...]
    cc_addrs: tuple[str, ...]
    subject: str
    date: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    label_ids: tuple[str, ...]
    has_attachment: bool
    text: str
    occurrence_time: str
    is_sent: bool

    def header_map(self) -> dict[str, str]:
        """Deterministic header dict; every value already passed the CR/LF guard."""
        return {
            "From": self.from_addr,
            "To": ", ".join(self.to_addrs),
            "Cc": ", ".join(self.cc_addrs),
            "Subject": self.subject,
            "Date": self.date or "",
            "Message-ID": self.rfc_message_id or "",
            "In-Reply-To": self.in_reply_to or "",
            "References": " ".join(self.references),
        }


@dataclass
class _Budget:
    """Shared consumption counters so nested parts cannot each reset a limit."""

    limits: MimeLimits
    raw_bytes: int = 0
    parts: int = 0

    def add_bytes(self, amount: int) -> None:
        self.raw_bytes += amount
        if self.raw_bytes > self.limits.max_raw_bytes:
            raise BoundedInputExceeded("mime_raw_bytes")

    def add_part(self) -> None:
        self.parts += 1
        if self.parts > self.limits.max_parts:
            raise BoundedInputExceeded("mime_part_count")


def _guard(value: str, field_name: str) -> str:
    """Reject CR/LF and control characters so emitted headers cannot be injected."""
    for char in value:
        code = ord(char)
        if code == 13 or code == 10 or code == 0:
            raise UnparseableHeader(f"unsafe_header_{field_name}")
    return value


def _decode_mime_words(value: str) -> str:
    try:
        parts = decode_header(value)
    except Exception as exc:  # malformed RFC 2047 encoded-word
        raise UnparseableHeader("undecodable_header") from exc
    decoded: list[str] = []
    for token, charset in parts:
        if isinstance(token, bytes):
            decoded.append(token.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(token)
    return "".join(decoded).strip()


def _headers(part: Mapping[str, Any]) -> dict[str, str]:
    raw = part.get("headers")
    result: dict[str, str] = {}
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return result
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and isinstance(value, str):
            # Last write wins is unsafe for a repeated identity header; keep the first.
            result.setdefault(name.lower(), value)
    return result


class _TextExtractor(HTMLParser):
    """Conservative HTML to text: keeps visible data, drops scripts/styles, fetches nothing."""

    def __init__(self, limit_chars: int) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._count = 0
        self._limit = limit_chars
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in ("br", "p", "div", "li", "tr"):
            self._emit(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._emit(data)

    def _emit(self, text: str) -> None:
        if not text:
            return
        self._count += len(text)
        if self._count > self._limit:
            raise BoundedInputExceeded("mime_text_chars")
        self._chunks.append(text)

    def text(self) -> str:
        return " ".join("".join(self._chunks).split())


def _html_to_text(html: str, limit_chars: int) -> str:
    parser = _TextExtractor(limit_chars)
    parser.feed(html)
    parser.close()
    return parser.text()


def _decode_body(data: str, budget: _Budget, *, fetch_bytes: bool) -> str:
    budget.add_part()
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    budget.add_bytes(len(padded))
    if not fetch_bytes:
        # Attachment present but never fetched: account for its size, decode nothing.
        return ""
    try:
        raw = urlsafe_b64decode(padded)
    except Exception as exc:  # not valid base64url
        raise UnparseableHeader("undecodable_body") from exc
    return raw.decode("utf-8", errors="replace")


def _occurrence_time(internal_date: object) -> str:
    if isinstance(internal_date, str) and internal_date.isdigit():
        dt = datetime.fromtimestamp(int(internal_date) / 1000.0, UTC)
        return format_timestamp(dt)
    if isinstance(internal_date, int):
        dt = datetime.fromtimestamp(internal_date / 1000.0, UTC)
        return format_timestamp(dt)
    raise UnparseableHeader("missing_internal_date")


def _extract_text(
    part: Mapping[str, Any], budget: _Budget, depth: int, plain: list[str], html: list[str]
) -> bool:
    if depth > budget.limits.max_depth:
        raise BoundedInputExceeded("mime_depth")
    mime = str(part.get("mimeType") or "").lower()
    headers = _headers(part)
    disposition = headers.get("content-disposition", "").lower()
    body = part.get("body")
    is_attachment = bool(part.get("filename")) or "attachment" in disposition
    data = body.get("data") if isinstance(body, Mapping) else None
    if isinstance(data, str):
        text = _decode_body(data, budget, fetch_bytes=(not is_attachment and _is_textual(mime)))
        if not is_attachment:
            if mime == "text/plain":
                plain.append(text)
                return True
            if mime == "text/html":
                html.append(text)
    for child in _child_parts(part):
        if _extract_text(child, budget, depth + 1, plain, html):
            if _is_textual(mime):
                return True
    return bool(plain) and not _multipart(mime)


def _is_textual(mime: str) -> bool:
    return mime in ("text/plain", "text/html")


def _multipart(mime: str) -> bool:
    return mime.startswith(_MULTIPART_PREFIX)


def _child_parts(part: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    parts = part.get("parts")
    children: list[Mapping[str, Any]] = []
    if isinstance(parts, Sequence) and not isinstance(parts, (str, bytes)):
        for child in parts:
            if isinstance(child, Mapping):
                children.append(child)
    return children


def _attachment_count(part: Mapping[str, Any], budget: _Budget, depth: int) -> int:
    if depth > budget.limits.max_depth:
        raise BoundedInputExceeded("mime_depth")
    headers = _headers(part)
    disposition = headers.get("content-disposition", "").lower()
    count = 1 if (part.get("filename") or "attachment" in disposition) else 0
    for child in _child_parts(part):
        count += _attachment_count(child, budget, depth + 1)
    return count


def _references(value: str) -> tuple[str, ...]:
    tokens = [token for token in value.replace(",", " ").split() if token]
    for token in tokens:
        _guard(token, "references")
    return tuple(tokens)


def _parse_sender(headers: Mapping[str, str]) -> str:
    from_raw = headers.get("from")
    if from_raw is None:
        raise UnparseableHeader("missing_from")
    from_value = _decode_mime_words(from_raw)
    _guard(from_value, "from")
    _, address = parseaddr(from_value)
    if not address or "@" not in address:
        raise UnparseableHeader("ambiguous_from")
    return address.lower()


def _parse_recipients(headers: Mapping[str, str], name: str = "to") -> tuple[str, ...]:
    raw = headers.get(name, "")
    value = _decode_mime_words(raw) if raw else ""
    _guard(value, name)
    addresses: list[str] = []
    for _, address in getaddresses([value]) if value else []:
        if address and "@" in address:
            addresses.append(address.lower())
    return tuple(dict.fromkeys(addresses))


def _date_string(headers: Mapping[str, str]) -> str | None:
    raw = headers.get("date")
    if not raw:
        return None
    value = _decode_mime_words(raw)
    _guard(value, "date")
    try:
        parsedate_to_datetime(value)
    except (TypeError, ValueError):
        # A malformed Date header is preserved verbatim, never used as knowledge time (I-6).
        return value
    return value


def parse_message(
    message: Mapping[str, Any],
    *,
    limits: MimeLimits = DEFAULT_LIMITS,
) -> ParsedMessage:
    """Parse one Gmail message resource into a bounded, safe observation input.

    Fails closed on any limit breach (``BoundedInputExceeded``) or on ambiguous sender or
    header parsing (``UnparseableHeader``). A ``SENT`` label marks a self-authored message; SENT
    is an observation, never an incoming decision situation.
    """
    native_id = message.get("id")
    if not isinstance(native_id, str) or not native_id:
        raise UnparseableHeader("missing_native_id")
    history_id = message.get("historyId")
    if not isinstance(history_id, int) or history_id < 0:
        raise UnparseableHeader("missing_history_id")
    payload = message.get("payload")
    if not isinstance(payload, Mapping):
        raise UnparseableHeader("missing_payload")

    budget = _Budget(limits=limits)
    top_headers = _headers(payload)
    label_ids = _string_tuple(message.get("labelIds"))
    for label in label_ids:
        _guard(label, "label")

    plain: list[str] = []
    html: list[str] = []
    _extract_text(payload, budget, 0, plain, html)

    if plain:
        text = " ".join(" ".join(plain).split())
    elif html:
        text = _html_to_text(" ".join(html), limits.max_text_chars)
    else:
        text = ""
    if len(text) > limits.max_text_chars:
        raise BoundedInputExceeded("mime_text_chars")

    rfc_id = top_headers.get("message-id")
    rfc_message_id = _guard(_decode_mime_words(rfc_id), "message_id") if rfc_id else None
    in_reply_to_raw = top_headers.get("in-reply-to")
    in_reply_to = (
        _guard(_decode_mime_words(in_reply_to_raw), "in_reply_to") if in_reply_to_raw else None
    )
    references = _references(top_headers.get("references", ""))
    subject_raw = top_headers.get("subject", "")
    subject = _guard(_decode_mime_words(subject_raw), "subject")

    has_attachment = _attachment_count(payload, budget, 0) > 0
    thread_id = message.get("threadId")
    is_sent = "SENT" in label_ids
    return ParsedMessage(
        native_message_id=native_id,
        thread_id=thread_id if isinstance(thread_id, str) else None,
        rfc_message_id=rfc_message_id,
        history_id=history_id,
        from_addr=_parse_sender(top_headers),
        to_addrs=_parse_recipients(top_headers, "to"),
        cc_addrs=_parse_recipients(top_headers, "cc"),
        subject=subject,
        date=_date_string(top_headers),
        in_reply_to=in_reply_to,
        references=references,
        label_ids=label_ids,
        has_attachment=has_attachment,
        text=text,
        occurrence_time=_occurrence_time(message.get("internalDate")),
        is_sent=is_sent,
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(str(item) for item in value)
    return ()
