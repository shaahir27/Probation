"""Gmail provider version facts: the ``revision`` token and the undo evidence behind it.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 2 and 4. Gmail offers no compare-and-set (C1),
so the contract's atomic CAS degrades to check-then-act. This module makes that degradation honest
by computing the only two version facts a Gmail write may trust:

* ``revision`` is the frozen D4 hash of ``(connection_id, native_message_id, thread_id, sorted
  labelIds, the message's own provider historyId)``: per message, advanced by any actor's change
  (C2), the only version token Gmail really offers. It is re-read immediately before the write; a
  mismatch answers ``mail_revision_conflict`` with a proven non-effect, as the synthetic does.
* ``label_versions`` are observed transition counts from the read layer's ``LabelVersionEvidence``,
  cross-checked against one bounded ``history.list`` from the provider. An unresolvable anchor, a
  non-continuous window or a disagreement raises ``MailConflict('undo_history_unavailable')``
  instead of returning ``{}`` (breaks every legitimate undo) or a constant (kills D3's ABA guard).

Nothing here dispatches a write. The adapter that does, and the receipts it journals, live in
``gmail_write.py``. This module also owns the label algebra the provider forces on us: which label
set a write must land, which capability row an effect needs, and how to read back a header.
"""

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from probation.connectors.types import (
    ConnectorError,
    HttpResult,
    HttpTransport,
    MessagePayload,
    ProviderUnavailable,
    advance_versions,
)
from probation.core.hashing import canonical_json
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_transport import quote_native_id
from probation.packs.mail.lifecycle_io import MailConflict

BASE_URL: Final = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_MAX_RESULTS: Final = 100
INBOX: Final = "INBOX"
TRASH: Final = "TRASH"
SENT: Final = "SENT"
_UNDU: Final = "undo_history_unavailable"
#: Gmail's own ``trash`` method also drops ``INBOX``. Undo restores only what Probation changed, so
#: this implicit transition is expected and is never invented back.
_IMPLICIT_ON_TRASH: Final[frozenset[str]] = frozenset({INBOX})


@dataclass(frozen=True)
class EffectAnchor:
    """Where Probation's own effect sat in provider history, and the versions observed before it."""

    native_message_id: str
    anchor_history_id: int
    before_revision: str
    baseline: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageState:
    """What the provider says a message is right now, plus the token derived from exactly that."""

    labels: tuple[str, ...]
    thread_id: str
    revision: str
    message_history_id: int


class AnchorStore(Protocol):
    """The effect anchor ``prepare_undo`` needs. Durable storage is an open interface request."""

    def save(self, anchor: EffectAnchor) -> None: ...

    def load(self, native_message_id: str) -> EffectAnchor | None: ...


class InMemoryAnchorStore:
    """Process-lifetime anchors. After a restart undo cannot be proven, so it fails closed."""

    def __init__(self) -> None:
        self._items: dict[str, EffectAnchor] = {}

    def save(self, anchor: EffectAnchor) -> None:
        self._items[anchor.native_message_id] = anchor

    def load(self, native_message_id: str) -> EffectAnchor | None:
        return self._items.get(native_message_id)


def _digest(fields: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(fields)).encode("utf-8")).hexdigest()


def hashed_native_ref(*, connection_id: str, account_id: str, native_message_id: str) -> str:
    """A native id is account-identifying: only this digest is publishable (section 7)."""
    fields = {"connection_id": connection_id, "account_id": account_id}
    fields["native_message_id"] = native_message_id
    return "sha256:" + _digest(fields)


def gmail_revision(
    *,
    connection_id: str,
    native_message_id: str,
    thread_id: str,
    labels: Sequence[str],
    message_history_id: int,
) -> str:
    """The frozen D4 revision token. It changes whenever any actor changes the message."""
    fields = {
        "connection_id": connection_id,
        "native_message_id": native_message_id,
        "thread_id": thread_id,
        "labels": sorted(labels),
        "message_history_id": message_history_id,
    }
    return _digest(fields)


def intended_labels(before: Sequence[str], add: Sequence[str], remove: Sequence[str]) -> set[str]:
    """What the provider must show afterwards, including Gmail's implicit INBOX drop on trash."""
    intended = (set(before) | set(add)) - set(remove)
    return intended - _IMPLICIT_ON_TRASH if TRASH in add else intended


def effect_operation(add: Sequence[str], remove: Sequence[str]) -> str:
    """Which gate row an effect needs. Undo is a second ``apply_mail``, nothing more."""
    if TRASH in add or TRASH in remove:
        return "trash"
    if add and not remove:
        return "undo"
    return "archive"


def decode_response(result: HttpResult) -> dict[str, Any]:
    if not result.ok:
        raise ProviderUnavailable(f"provider_status_{result.status}")
    try:
        decoded = json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderUnavailable("malformed_provider_response") from exc
    if not isinstance(decoded, Mapping):
        raise ProviderUnavailable("malformed_provider_response")
    return dict(decoded)


def as_sequence(value: object) -> list[Any]:
    return (
        list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []
    )


def as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


def header_value(payload: Mapping[str, Any], name: str) -> str:
    head = payload.get("payload")
    wanted = name.lower()
    for header in as_sequence(head.get("headers") if isinstance(head, Mapping) else None):
        if isinstance(header, Mapping) and str(header.get("name", "")).lower() == wanted:
            return str(header.get("value", "")).strip()
    return ""


#: RFC 5322 ``msg-id`` inside its brackets, conservatively: no whitespace, no nested angle
#: brackets, at least one ``@`` separating a non-empty local part from a non-empty domain.
_MESSAGE_ID: Final = re.compile(r"^[^<>@\s]+@[^<>@\s]+$")


def bracketed_message_id(value: str | None, *, native_message_id: str) -> str:
    """Exactly one pair of angle brackets around the provider's RFC ``Message-ID``.

    Gmail's native message id and the sender's RFC id are different namespaces; the native id is
    never a substitute for the header (C7). A missing, malformed or native-derived id refuses.
    """
    text = (value or "").strip()
    if len(text) > 2 and text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()
    if (
        not text
        or text in (native_message_id, native_message_id.strip("<>"))
        or any(ord(char) < 33 for char in text)
        or not _MESSAGE_ID.match(text)
    ):
        raise MailConflict("reply_threading_unavailable")
    return f"<{text}>"


def reply_threading(
    original: MessagePayload, *, resource_id: str, reviewed_thread_id: object = None
) -> tuple[str, str]:
    """The provider's thread id plus RFC ``Message-ID`` for a reply, or a refusal.

    Both come from the persisted original message. If the reviewed payload names a different
    thread, the two descriptions disagree about which message is being answered, so neither is
    trusted. The caller sends nothing rather than guessing a thread.
    """
    if original.native_message_id != resource_id:
        raise MailConflict("reply_threading_unavailable")
    thread_id = (original.thread_id or "").strip()
    if (
        not thread_id
        or len(thread_id) > 512
        or any(ord(char) < 33 for char in thread_id)
        or (
            isinstance(reviewed_thread_id, str)
            and reviewed_thread_id
            and reviewed_thread_id != thread_id
        )
    ):
        raise MailConflict("reply_threading_unavailable")
    return thread_id, bracketed_message_id(original.rfc_message_id, native_message_id=resource_id)


class GmailVersioning:
    """The provider's version facts for one cohort message, read on demand, never guessed."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        read: GmailReadConnector,
        connection_id: str,
        access_token: str,
        store: ConnectorAccess,
        anchors: AnchorStore,
        retained_from_history_id: int = 0,
        max_history_pages: int = 10,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        if not access_token and token_provider is None:
            raise ConnectorError("write_token_unconfigured")
        self._token_provider = token_provider
        self._transport = transport
        self._read = read
        self._connection_id = connection_id
        self._token = access_token
        self._store = store
        self._anchors = anchors
        self._retained_from = retained_from_history_id
        self._max_history_pages = max_history_pages
        self._history_seen: dict[str, int] = {}

    def _auth(self) -> str:
        return self._token if self._token_provider is None else self._token_provider()

    def state(self, native_id: str) -> MessageState:
        payload = self._resource(native_id)
        labels = tuple(sorted(str(item) for item in as_sequence(payload.get("labelIds"))))
        thread_id = str(payload.get("threadId") or "")
        history_id = self._history_seen[native_id]
        revision = gmail_revision(
            connection_id=self._connection_id,
            native_message_id=native_id,
            thread_id=thread_id,
            labels=labels,
            message_history_id=history_id,
        )
        return MessageState(labels, thread_id, revision, history_id)

    def _resource(self, native_id: str) -> dict[str, Any]:
        result = self._transport.get(
            f"{BASE_URL}/messages/{quote_native_id(native_id)}",
            params={"format": "metadata"},
            access_token=self._auth(),
        )
        if result.status == 404:
            raise MailConflict("mail_resource_missing")
        payload = decode_response(result)
        history_id = as_int(payload.get("historyId"))
        if history_id is None:
            raise MailConflict("missing_message_history_id")
        self._history_seen[native_id] = history_id
        return payload

    # -- undo evidence, or a loud refusal ---------------------------------------------------
    def label_versions(self, native_id: str, message_history_id: int) -> dict[str, int]:
        anchor = self._anchors.load(native_id)
        start, baseline = (
            (anchor.anchor_history_id, dict(anchor.baseline))
            if anchor is not None
            else (self._window_start(), {})
        )
        records, reached_end = self._provider_window(start, message_history_id)
        transitions = tuple(
            item
            for item in self._read.cohort_transitions(records)
            if item.native_message_id == native_id
        )
        provider = advance_versions(baseline, transitions, native_id)
        evidence = self._read.label_version_evidence(
            native_id,
            access=self._store,
            anchor_history_id=start,
            baseline=baseline,
            window_complete=reached_end,
            retained_from=self._retained_from,
        )
        if not evidence.continuous or provider != evidence.versions:
            # The window cannot prove these counts. Refuse loudly: a guess here would silently
            # disable the version equality that ``prepare_undo`` depends on.
            raise MailConflict(_UNDU)
        return dict(evidence.versions)

    def _window_start(self) -> int:
        """The committed ingestor anchor: versions are the provider's, never a local counter."""
        row = self._store.one(
            "SELECT bootstrap_history_id AS anchor FROM gmail_sync_cursors WHERE connection_id=?"
            " AND role='read' AND catchup_complete=1 AND bootstrap_history_id IS NOT NULL"
            " ORDER BY filter_revision DESC LIMIT 1",
            (self._connection_id,),
        )
        if row is None or row["anchor"] is None:
            raise MailConflict(_UNDU)
        return int(row["anchor"])

    def _provider_window(self, start: int, message_history_id: int) -> tuple[list[Any], bool]:
        """One bounded ``history.list`` from the anchor. A 404, a gap or a page cap refuses proof."""
        records: list[Any] = []
        token: str | None = None
        end_seen = 0
        for _ in range(self._max_history_pages):
            params: dict[str, object] = {"startHistoryId": start, "maxResults": GMAIL_MAX_RESULTS}
            if token is not None:
                params["pageToken"] = token
            try:
                payload = self._read.history_page(params)
            except ProviderUnavailable as exc:
                if exc.safe_code == "provider_status_404":
                    raise MailConflict(_UNDU) from exc
                raise
            end_seen = max(end_seen, as_int(payload.get("historyId")) or 0)
            records.extend(
                item for item in as_sequence(payload.get("history")) if isinstance(item, Mapping)
            )
            raw = payload.get("nextPageToken")
            token = str(raw) if raw else None
            if token is None:
                return records, end_seen >= message_history_id
        return records, False


__all__ = [
    "BASE_URL",
    "GMAIL_MAX_RESULTS",
    "INBOX",
    "SENT",
    "TRASH",
    "AnchorStore",
    "EffectAnchor",
    "GmailVersioning",
    "InMemoryAnchorStore",
    "MessageState",
    "as_int",
    "as_sequence",
    "bracketed_message_id",
    "decode_response",
    "effect_operation",
    "gmail_revision",
    "hashed_native_ref",
    "header_value",
    "intended_labels",
    "reply_threading",
]
