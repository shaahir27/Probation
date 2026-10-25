"""Owner-only, hash-verified persistence for parsed Gmail message content.

Authority: ``docs/WP12_D4_GMAIL_CONTRACT.md`` section 12 (frozen). The read/observation path is
the only writer: after ``apply_owner_only`` plus ``verify_owner_only`` prove the directory is
owner-only, one bounded, already-parsed message is written atomically (temp file in the same
directory, then ``os.replace``) and only then does the caller commit its observation row. The
returned reference is relative below the payload root — never absolute, a token or a URL.

The JSON carries exactly the section-12 fields. No attachment bytes, no HTML source, no remote
image and no URL extracted from the body is ever written: the writer receives the already-parsed,
bounded ``ParsedMessage`` text only. A reader re-verifies the file's ACL, recomputes the content
hash from the file's own fields and raises a typed ``ConnectorError`` on a missing, malformed,
oversized or hash-mismatched payload — never an empty message.

No network, no LLM and no system clock live here.
"""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from probation.connectors.acl import apply_owner_only, verify_owner_only
from probation.connectors.types import (
    BoundedInputExceeded,
    ConnectorError,
    MessagePayload,
)
from probation.packs.mail.connectors.gmail_mime import ParsedMessage

MAX_PAYLOAD_BYTES: Final = 4 * 1024 * 1024

_CONTENT_FIELDS: Final = (
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
)
_FIELDS: Final = (*_CONTENT_FIELDS, "content_hash")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%~-]{0,254}$")
_ENCODING = "utf-8"


def _safe_segment(value: str, code: str) -> str:
    """A single path segment that cannot traverse, alias or overflow a directory entry."""
    if not isinstance(value, str) or not _SAFE_SEGMENT.fullmatch(value) or value.endswith("."):
        raise ConnectorError(code)
    return value


def _payload_filename(native_message_id: str) -> str:
    """``<native_message_id>.json``; only characters Windows cannot name are percent-encoded."""
    encoded = quote(native_message_id, safe="")
    if not encoded or len(encoded) > 200 or encoded in (".", "..") or encoded.endswith("."):
        encoded = "id-" + hashlib.sha256(native_message_id.encode(_ENCODING)).hexdigest()
    return f"{encoded}.json"


def _canonical(document: Mapping[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_document(document: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(document).encode(_ENCODING)).hexdigest()[:32]


def _content_document(payload: MessagePayload) -> dict[str, object]:
    """The exact section-12 fields that the content hash covers (no hash field itself)."""
    return {
        "native_message_id": payload.native_message_id,
        "thread_id": payload.thread_id,
        "rfc_message_id": payload.rfc_message_id,
        "from_addr": payload.from_addr,
        "to_addr": list(payload.to_addr),
        "cc_addrs": list(payload.cc_addrs),
        "subject": payload.subject,
        "body_text": payload.body_text,
        "occurred_at": payload.occurred_at,
        "attachment_present": payload.attachment_present,
    }


def payload_from_parsed(parsed: ParsedMessage) -> MessagePayload:
    """Turn one bounded parse into the persisted record. Attachment content never appears."""
    document: dict[str, object] = {
        "native_message_id": parsed.native_message_id,
        "thread_id": parsed.thread_id,
        "rfc_message_id": parsed.rfc_message_id,
        "from_addr": parsed.from_addr,
        "to_addr": list(parsed.to_addrs),
        "cc_addrs": list(parsed.cc_addrs),
        "subject": parsed.subject,
        "body_text": parsed.text,
        "occurred_at": parsed.occurrence_time,
        "attachment_present": parsed.has_attachment,
    }
    return MessagePayload(
        native_message_id=parsed.native_message_id,
        thread_id=parsed.thread_id,
        rfc_message_id=parsed.rfc_message_id,
        from_addr=parsed.from_addr,
        to_addr=parsed.to_addrs,
        cc_addrs=parsed.cc_addrs,
        subject=parsed.subject,
        body_text=parsed.text,
        occurred_at=parsed.occurrence_time,
        attachment_present=parsed.has_attachment,
        content_hash=_hash_document(document),
    )


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise ConnectorError("payload_malformed")
    return value


def _optional_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data[key]
    if value is None or isinstance(value, str):
        return value
    raise ConnectorError("payload_malformed")


def _str_list(data: Mapping[str, Any], key: str) -> list[str]:
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConnectorError("payload_malformed")
    return [str(item) for item in value]


def _payload_from_file(data: Mapping[str, Any]) -> MessagePayload:
    """Validate field types, recompute the hash, then build the record. Never trusts the file."""
    if set(data) != set(_FIELDS):
        raise ConnectorError("payload_malformed")
    attachment = data["attachment_present"]
    if not isinstance(attachment, bool):
        raise ConnectorError("payload_malformed")
    document: dict[str, object] = {
        "native_message_id": _required_str(data, "native_message_id"),
        "thread_id": _optional_str(data, "thread_id"),
        "rfc_message_id": _optional_str(data, "rfc_message_id"),
        "from_addr": _required_str(data, "from_addr"),
        "to_addr": _str_list(data, "to_addr"),
        "cc_addrs": _str_list(data, "cc_addrs"),
        "subject": _required_str(data, "subject"),
        "body_text": _required_str(data, "body_text"),
        "occurred_at": _optional_str(data, "occurred_at"),
        "attachment_present": attachment,
    }
    stored_hash = _required_str(data, "content_hash")
    if stored_hash != _hash_document(document):
        raise ConnectorError("payload_hash_mismatch")
    return MessagePayload(
        native_message_id=str(document["native_message_id"]),
        thread_id=document["thread_id"] if isinstance(document["thread_id"], str) else None,
        rfc_message_id=(
            document["rfc_message_id"] if isinstance(document["rfc_message_id"], str) else None
        ),
        from_addr=str(document["from_addr"]),
        to_addr=tuple(_str_list(data, "to_addr")),
        cc_addrs=tuple(_str_list(data, "cc_addrs")),
        subject=str(document["subject"]),
        body_text=str(document["body_text"]),
        occurred_at=document["occurred_at"] if isinstance(document["occurred_at"], str) else None,
        attachment_present=attachment,
        content_hash=stored_hash,
    )


class GmailPayloadStore:
    """``PayloadWriter`` and ``PayloadReader`` over one owner-only payload root.

    ``root`` is the contract's payload directory (``<private_root>/connectors/payloads``). A
    writer must be bound to one connection id; a reader may stay unbound and serve any
    ``<connection>/<native_message_id>.json`` reference below that root.
    """

    def __init__(self, root: Path, connection_id: str | None = None) -> None:
        self._root = Path(root)
        self._connection_id = (
            None if connection_id is None else _safe_segment(connection_id, "unsafe_connection_id")
        )

    # -- writer -----------------------------------------------------------------------------
    def write(self, payload: MessagePayload) -> str:
        """Persist one parsed message atomically; return the relative ref, never a path."""
        connection = self._connection_id
        if connection is None:
            raise ConnectorError("payload_store_unbound")
        filename = _payload_filename(payload.native_message_id)
        document = _content_document(payload)
        document["content_hash"] = payload.content_hash
        encoded = _canonical(document).encode(_ENCODING)
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise BoundedInputExceeded("payload_bytes")
        directory = self._root / connection
        self._owner_only_directory(self._root)
        self._owner_only_directory(directory)
        target = directory / filename
        ref = f"{connection}/{filename}"
        if not self._reusable(target, payload.content_hash):
            self._atomic_write(target, encoded)
        return ref

    def _owner_only_directory(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if not path.is_dir():
                raise ConnectorError("payload_directory_unavailable")
        except OSError as exc:
            raise ConnectorError("payload_directory_unavailable") from exc
        apply_owner_only(path, is_dir=True)  # raises PrivatePathRejected/AclUnsupported
        verify_owner_only(path)

    def _reusable(self, target: Path, content_hash: str) -> bool:
        """Re-observation reuses an intact file; a damaged one is replaced, never trusted."""
        if not target.is_file():
            return False
        try:
            verify_owner_only(target)
            data = json.loads(target.read_text(encoding=_ENCODING))
            if not isinstance(data, dict):
                return False
            return _payload_from_file(data).content_hash == content_hash
        except (ConnectorError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False

    def _atomic_write(self, target: Path, encoded: bytes) -> None:
        directory = target.parent
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".payload-", suffix=".tmp", dir=directory
            )
        except OSError as exc:
            raise ConnectorError("payload_write_failed") from exc
        os.close(descriptor)
        temp = Path(temp_name)
        try:
            # Seal the ACL before the first payload byte is written: a fresh temp file starts
            # with the process default DACL (user, SYSTEM, Administrators), and no payload byte
            # may ever exist on a file that is not provably owner-only.
            apply_owner_only(temp, is_dir=False)
            verify_owner_only(temp)
            with open(temp, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            verify_owner_only(temp)
            os.replace(temp, target)
            verify_owner_only(target)
        except OSError as exc:
            raise ConnectorError("payload_write_failed") from exc
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass

    # -- reader -----------------------------------------------------------------------------
    def read(self, payload_ref: str) -> MessagePayload:
        """Read one ref, re-proving ACL and content hash. Missing or changed content raises."""
        connection, filename = _parse_ref(payload_ref)
        if self._connection_id is not None and connection != self._connection_id:
            raise ConnectorError("payload_ref_foreign_connection")
        try:
            root = self._root.resolve()
            directory = (root / connection).resolve()
            target = (directory / filename).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ConnectorError("payload_missing") from exc
        if directory.parent != root or target.parent != directory or not target.is_file():
            raise ConnectorError("payload_ref_escapes_root")
        verify_owner_only(target)
        try:
            if target.stat().st_size > MAX_PAYLOAD_BYTES:
                raise BoundedInputExceeded("payload_bytes")
            data = json.loads(target.read_text(encoding=_ENCODING))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorError("payload_unreadable") from exc
        if not isinstance(data, dict):
            raise ConnectorError("payload_malformed")
        return _payload_from_file(data)


def _parse_ref(payload_ref: str) -> tuple[str, str]:
    """Exactly ``<connection>/<native_message_id>.json``; no absolute, traversal or alias forms."""
    if not isinstance(payload_ref, str) or not payload_ref or len(payload_ref) > 512:
        raise ConnectorError("invalid_payload_ref")
    if "\\" in payload_ref or Path(payload_ref).is_absolute():
        raise ConnectorError("invalid_payload_ref")
    parts = payload_ref.split("/")
    if len(parts) != 2:
        raise ConnectorError("invalid_payload_ref")
    connection = _safe_segment(parts[0], "invalid_payload_ref")
    filename = parts[1]
    if not filename.endswith(".json") or len(filename) <= len(".json"):
        raise ConnectorError("invalid_payload_ref")
    stem = filename[: -len(".json")]
    if not _SAFE_FILENAME.fullmatch(stem) or stem.endswith("."):
        raise ConnectorError("invalid_payload_ref")
    return connection, filename
