"""Fake Gmail provider that is faithful to documented Gmail limits, over HttpTransport.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1 and 6, and CONTRACT invariant I-17.
The real read connector and this fake share one code path: every Gmail call is an ordinary
HTTP request through the injected transport, and the fake answers with byte-for-byte the JSON
shapes the REST reference documents. There is no ``if synthetic:`` branch anywhere.

A fake that offered stronger guarantees than Gmail would prove nothing, so this reproduces the
weaknesses deliberately: ``modify`` accepts NO precondition (C1), each message carries its own
advancing ``historyId`` (C2), history is a bounded window that returns HTTP 404 once the anchor
ages out (C3), and pages can be duplicated or overlap on demand.
"""

import json
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from probation.connectors.types import HttpResult, HttpTransport

_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


@dataclass(frozen=True)
class _Page:
    """One bounded result page plus the token to request the next one."""

    items: list[Any]
    next_token: str | None


class _Message:
    """One stored message. ``history_id`` is the last history record that touched it (C2)."""

    def __init__(
        self,
        native_id: str,
        *,
        thread_id: str,
        from_addr: str,
        to_addr: str,
        subject: str,
        date: str,
        message_id: str,
        internal_date_ms: int,
        labels: set[str],
        text: str | None = None,
        html: str | None = None,
        in_reply_to: str | None = None,
        references: tuple[str, ...] = (),
        attachment: bool = False,
    ) -> None:
        self.native_id = native_id
        self.thread_id = thread_id
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.subject = subject
        self.date = date
        self.message_id = message_id
        self.internal_date_ms = internal_date_ms
        self.labels = set(labels)
        self.text = text
        self.html = html
        self.in_reply_to = in_reply_to
        self.references = references
        self.attachment = attachment
        self.history_id = 0
        self.deleted = False

    def resource(self, *, body: bool) -> dict[str, Any]:
        headers = [
            {"name": "From", "value": self.from_addr},
            {"name": "To", "value": self.to_addr},
            {"name": "Subject", "value": self.subject},
            {"name": "Date", "value": self.date},
            {"name": "Message-ID", "value": self.message_id},
        ]
        if self.in_reply_to:
            headers.append({"name": "In-Reply-To", "value": self.in_reply_to})
        if self.references:
            headers.append({"name": "References", "value": " ".join(self.references)})
        payload: dict[str, Any] = {
            "headers": headers,
            "mimeType": "multipart/alternative",
            "parts": [],
        }
        if body:
            if self.attachment:
                payload["parts"].append(
                    {
                        "mimeType": "application/octet-stream",
                        "filename": "note.bin",
                        "headers": [
                            {
                                "name": "Content-Disposition",
                                "value": 'attachment; filename="note.bin"',
                            }
                        ],
                        "body": {"data": _b64(b"attachment-bytes-not-fetched")},
                    }
                )
            if self.text is not None:
                payload["parts"].append(
                    {
                        "mimeType": "text/plain",
                        "headers": [{"name": "Content-Type", "value": "text/plain; charset=UTF-8"}],
                        "body": {"data": _b64(self.text.encode("utf-8"))},
                    }
                )
            if self.html is not None:
                payload["parts"].append(
                    {
                        "mimeType": "text/html",
                        "headers": [{"name": "Content-Type", "value": "text/html; charset=UTF-8"}],
                        "body": {"data": _b64(self.html.encode("utf-8"))},
                    }
                )
        return {
            "id": self.native_id,
            "threadId": self.thread_id,
            "labelIds": sorted(self.labels),
            "snippet": (self.text or "")[:80],
            "historyId": self.history_id,
            "internalDate": str(self.internal_date_ms),
            "payload": payload,
        }


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii")


class FakeGmailTransport(HttpTransport):
    """Deterministic Gmail REST fake. Tests mutate it through explicit, documented hooks."""

    def __init__(
        self,
        *,
        account_id: str = "acct-1",
        email: str = "owner@example.test",
        page_size: int = 2,
        expected_token: str = "read-token",
    ) -> None:
        self.account_id = account_id
        self.email = email
        self.page_size = page_size
        self.expected_token = expected_token
        self.messages: dict[str, _Message] = {}
        self._order: list[str] = []
        self.history: list[dict[str, Any]] = []
        self.current_history_id = 0
        self.retained_history_min = 0
        self.profile_calls = 0
        self.list_calls = 0
        self.body_calls = 0
        self.history_calls = 0
        self.modify_calls = 0
        self.fetched_body_ids: list[str] = []
        self.overlap_pages_once = False
        self.duplicate_pages_once = False

    # -- test construction hooks (never used by connector code) -----------------------------
    def add_message(self, message: _Message) -> None:
        self.current_history_id += 1
        message.history_id = self.current_history_id
        self.messages[message.native_id] = message
        self._order.append(message.native_id)
        self._append_history(
            {"messagesAdded": [{"id": message.native_id, "threadId": message.thread_id}]}
        )

    def set_history_expired_below(self, exclusive_history_id: int) -> None:
        """Age out history: a startHistoryId below the retained window now returns 404 (C3)."""
        self.retained_history_min = exclusive_history_id

    def offer_overlapping_pages(self) -> None:
        """Next pagination step re-emits one already-served record (Gmail pages can overlap)."""
        self.overlap_pages_once = True

    def offer_duplicate_pages(self) -> None:
        """Next pagination step re-emits the identical page (Gmail can repeat a page token)."""
        self.duplicate_pages_once = True

    def modify_labels(
        self,
        native_id: str,
        *,
        add: tuple[str, ...] = (),
        remove: tuple[str, ...] = (),
    ) -> None:
        """Apply a label change with NO precondition — Gmail's C1 weakness reproduced here.

        Each touched label emits its own history record and advances the per-message
        ``historyId`` exactly as ``users.history.list`` documents.
        """
        message = self.messages[native_id]
        self.current_history_id += 1
        message.history_id = self.current_history_id
        records: dict[str, Any] = {}
        if add:
            records["labelAdded"] = [
                {"labelId": label, "messages": self._message_ref(message)} for label in add
            ]
        if remove:
            records["labelRemoved"] = [
                {"labelId": label, "messages": self._message_ref(message)} for label in remove
            ]
        for label in add:
            message.labels.add(label)
        for label in remove:
            message.labels.discard(label)
        if records:
            self._append_history(records)

    def _message_ref(self, message: _Message) -> list[dict[str, str]]:
        return [{"id": message.native_id, "threadId": message.thread_id}]

    def trash(self, native_id: str) -> None:
        self.modify_labels(native_id, add=("TRASH",), remove=("INBOX",))

    def delete_message(self, native_id: str) -> None:
        self.current_history_id += 1
        message = self.messages[native_id]
        message.history_id = self.current_history_id
        message.deleted = True
        self._append_history({"messagesDeleted": [{"id": native_id}]})

    def drop_message(self, native_id: str) -> None:
        """The provider no longer serves the message and emits NO history record for it.

        Models retention expiry rather than a user deletion: ``messages.list`` stops returning
        the id and ``messages.get`` answers 404, while no ``messagesDeleted`` record exists. A
        resync must therefore store nothing new — neither a snapshot nor a fabricated tombstone.
        """
        message = self.messages.get(native_id)
        if message is not None:
            message.deleted = True

    def _append_history(self, records: dict[str, Any]) -> None:
        entry = {"id": self.current_history_id}
        entry.update(records)
        self.history.append(entry)

    # -- HttpTransport implementation -------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: Any = None,
        access_token: str,
    ) -> HttpResult:
        if access_token != self.expected_token:
            return HttpResult(status=401)
        query = dict(params or {})
        path = url[len(_GMAIL_BASE) :] if url.startswith(_GMAIL_BASE) else url
        if path.startswith("/profile"):
            self.profile_calls += 1
            return _json(
                {
                    "id": "me",
                    "emailAddress": self.email,
                    "historyId": str(self.current_history_id),
                }
            )
        if path.startswith("/messages/"):
            native_id = unquote(path.rsplit("/", 1)[-1])
            self.body_calls += 1
            self.fetched_body_ids.append(native_id)
            message = self.messages.get(native_id)
            if message is None or message.deleted:
                return HttpResult(status=404)
            include_body = query.get("format", "full") != "metadata"
            return _json(message.resource(body=include_body))
        if path == "/messages":
            return self._list_messages(query)
        if path == "/history":
            return self._list_history(query)
        return HttpResult(status=400)

    def post(
        self,
        url: str,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        access_token: str,
    ) -> HttpResult:
        if access_token != self.expected_token:
            return HttpResult(status=401)
        del data
        path = url[len(_GMAIL_BASE) :] if url.startswith(_GMAIL_BASE) else url
        if path.endswith("/modify"):
            native_id = unquote(path.split("/")[2])
            self.modify_calls += 1
            body = json_body or {}
            self.modify_labels(
                native_id,
                add=tuple(body.get("addLabelIds", [])),
                remove=tuple(body.get("removeLabelIds", [])),
            )
            return _json(self.messages[native_id].resource(body=False))
        return HttpResult(status=400)

    def _list_messages(self, query: dict[str, Any]) -> HttpResult:
        self.list_calls += 1
        label_id = query.get("labelIds")
        include_trash = str(query.get("includeSpamTrash", "")).lower() == "true"
        ids = [
            native_id
            for native_id in self._order
            if not self.messages[native_id].deleted
            and (include_trash or "TRASH" not in self.messages[native_id].labels)
            and (label_id is None or str(label_id) in self.messages[native_id].labels)
        ]
        page = self._paginate(ids, query)
        result: dict[str, Any] = {
            "messages": [
                {"id": native_id, "threadId": self.messages[native_id].thread_id}
                for native_id in page.items
            ]
        }
        if page.next_token is not None:
            result["nextPageToken"] = page.next_token
        return _json(result)

    def _list_history(self, query: dict[str, Any]) -> HttpResult:
        self.history_calls += 1
        start_raw = query.get("startHistoryId")
        if start_raw is None:
            return HttpResult(status=400)
        start = int(str(start_raw))
        if start < self.retained_history_min or start > self.current_history_id:
            return HttpResult(status=404)  # C3: anchor aged out forces an explicit re-sync
        label_filter = query.get("labelId")
        records = [entry for entry in self.history if int(entry["id"]) > start]
        if label_filter is not None:
            records = [entry for entry in records if _entry_matches_label(entry, str(label_filter))]
        page = self._paginate(records, query)
        result: dict[str, Any] = {"history": page.items, "historyId": str(self.current_history_id)}
        if page.next_token is not None:
            result["nextPageToken"] = page.next_token
        return _json(result)

    def _paginate(self, items: list[Any], query: dict[str, Any]) -> "_Page":
        raw_token = query.get("pageToken")
        offset = int(str(raw_token)) if raw_token else 0
        limit = int(str(query.get("maxResults", self.page_size) or self.page_size))
        window = items[offset : offset + limit]
        consumed = offset + limit
        if consumed >= len(items):
            return _Page(window, None)
        next_token = consumed
        if self.duplicate_pages_once:
            self.duplicate_pages_once = False
            next_token = offset  # re-emit the identical page once
        elif self.overlap_pages_once:
            self.overlap_pages_once = False
            next_token = max(offset, consumed - 1)  # re-emit the last record once
        return _Page(window, str(next_token))


def _entry_matches_label(entry: dict[str, Any], label_id: str) -> bool:
    for key in ("labelAdded", "labelRemoved"):
        for record in entry.get(key, []):
            if record.get("labelId") == label_id:
                return True
    return False


def _json(payload: dict[str, Any]) -> HttpResult:
    return HttpResult(status=200, body=json.dumps(payload).encode("utf-8"))
