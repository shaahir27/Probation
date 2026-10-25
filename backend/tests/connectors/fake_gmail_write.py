"""Fake Gmail provider for the WRITE side, faithful to Gmail's documented weaknesses.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 2 and 6, and CONTRACT invariant I-17.
This file extends the read fake by subclassing it; it never edits it. The rules it enforces are
exactly the rules the REST reference documents, and in particular it enforces NONE of the rules
Gmail does not offer:

* ``messages.modify``, ``trash`` and ``untrash`` accept **no precondition** (C1). A write issued
  against a stale snapshot succeeds here just as it succeeds against Gmail. If the fake rejected
  stale writes, the adapter's check-then-act would look like provider atomicity it never has.
* every message carries its own ``historyId``, advanced by the provider on each change (C2), and
  each label transition is observable in ``users.history.list``;
* the retained history window can expire, and a ``startHistoryId`` below it answers HTTP 404 (C3);
* ``messages.send`` has no idempotency key (C8): an applied-but-erroring write is indistinguishable
  from a never-issued one, so the fake can apply the effect and still return a failure status.

Test hooks are explicit and named; nothing here is reachable by connector code.
"""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

from fake_gmail_read import FakeGmailTransport, _json, _Message

from probation.connectors.types import HttpResult

INBOX = "INBOX"
TRASH = "TRASH"
SENT = "SENT"
_PERSONAL = "CATEGORY_PERSONAL"
_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class FakeGmailWriteTransport(FakeGmailTransport):
    """Deterministic Gmail write surface: modify, trash, untrash and send, over the read endpoints."""

    def __init__(
        self,
        *,
        account_id: str = "acct-1",
        email: str = "owner@example.test",
        page_size: int = 2,
        expected_token: str = "write-token",
    ) -> None:
        super().__init__(
            account_id=account_id,
            email=email,
            page_size=page_size,
            expected_token=expected_token,
        )
        self.send_calls = 0
        self.trash_calls = 0
        self.untrash_calls = 0
        self.metadata_calls = 0
        self.write_calls = 0
        self.post_paths: list[str] = []
        self.send_bodies: list[dict[str, Any]] = []
        self.sent_raw: list[str] = []
        self._divert: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        self._ambiguous: tuple[int, bool] | None = None
        self._drop_next = False
        self._dropped_once = False

    # -- test construction hooks (never used by connector code) -----------------------------
    def external_edit(
        self, native_id: str, *, add: tuple[str, ...] = (), remove: tuple[str, ...] = ()
    ):
        """An unrelated actor changes the same message. Gmail gives no way to stop it (C1)."""
        self.modify_labels(native_id, add=add, remove=remove)

    def arm_diverted_modify(self, *, add: tuple[str, ...], remove: tuple[str, ...]) -> None:
        """The next modify applies a DIFFERENT label change than the one requested."""
        self._divert = (add, remove)

    def arm_ambiguous_write(self, *, status: int = 504, applied: bool = True) -> None:
        """The next write answers ``status``; when ``applied`` is set the effect really landed.

        Gmail can do exactly this: the request reaches the server and the response is lost. Absence
        of a receipt is therefore never proof that no send happened (C8).
        """
        self._ambiguous = (status, applied)

    def arm_dropped_write(self) -> None:
        """The next write answers HTTP 200 and applies nothing at all."""
        self._drop_next = True

    def _take_ambiguous(self) -> tuple[int, bool] | None:
        armed, self._ambiguous = self._ambiguous, None
        return armed

    # -- HttpTransport: writes --------------------------------------------------------------
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
        path = url.removeprefix(_GMAIL_BASE)
        body = json_body or {}
        self.post_paths.append(path)
        if path == "/messages/send":
            return self._send(body, raw=data)
        if path.endswith("/trash"):
            self.trash_calls += 1
            return self._label_write(
                path.split("/")[2], add=(TRASH,), remove=(INBOX,), endpoint="trash"
            )
        if path.endswith("/untrash"):
            self.untrash_calls += 1
            return self._label_write(
                path.split("/")[2], add=(), remove=(TRASH,), endpoint="untrash"
            )
        if path.endswith("/modify"):
            self.modify_calls += 1
            add = tuple(str(item) for item in body.get("addLabelIds", []))
            remove = tuple(str(item) for item in body.get("removeLabelIds", []))
            return self._label_write(path.split("/")[2], add=add, remove=remove)
        return HttpResult(status=400)

    def _label_write(
        self,
        native_id: str,
        *,
        add: tuple[str, ...],
        remove: tuple[str, ...],
        endpoint: str = "modify",
    ) -> HttpResult:
        self.write_calls += 1
        message = self.messages.get(native_id)
        if message is None or message.deleted:
            return HttpResult(status=404)
        armed = self._take_ambiguous()
        if self._divert is not None and endpoint == "modify":
            add, remove = self._divert
            self._divert = None
        if self._drop_next:
            self._drop_next = False
            return _json(message.resource(body=False))
        if armed is None or armed[1]:
            # NO precondition is checked here: a stale caller's write simply succeeds (C1).
            self.modify_labels(native_id, add=add, remove=remove)
        if armed is not None:
            return HttpResult(status=armed[0])
        return _json(message.resource(body=False))

    def _send(self, body: dict[str, Any], *, raw: bytes | None) -> HttpResult:
        self.write_calls += 1
        self.send_calls += 1
        encoded = raw if raw is not None else str(body.get("raw", "")).encode("ascii")
        text = _b64url_decode(encoded)
        headers, payload_text = _parse_raw(text)
        self.send_bodies.append({key: value for key, value in body.items() if key != "raw"})
        self.sent_raw.append(text)
        armed = self._take_ambiguous()
        native_id = ""
        if armed is None or armed[1]:
            native_id = f"sent-{len(self.messages) + 1}"
            thread = str(body.get("threadId") or f"thread-{native_id}")
            self.add_message(
                _Message(
                    native_id,
                    thread_id=thread,
                    from_addr=headers.get("from", ""),
                    to_addr=headers.get("to", ""),
                    subject=headers.get("subject", ""),
                    date=headers.get("date", ""),
                    message_id=headers.get("message-id", ""),
                    internal_date_ms=1700000000000 + 1000 * self.send_calls,
                    labels={SENT, _PERSONAL},
                    text=payload_text,
                    in_reply_to=headers.get("in-reply-to"),
                    references=tuple(
                        item for item in headers.get("references", "").split() if item
                    ),
                )
            )
        if armed is not None:
            return HttpResult(status=armed[0])
        message = self.messages[native_id]
        return _json(
            {
                "id": message.native_id,
                "threadId": message.thread_id,
                "labelIds": sorted(message.labels),
                "historyId": message.history_id,
            }
        )

    # -- HttpTransport: reads ---------------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: Any = None,
        access_token: str,
    ) -> HttpResult:
        query = dict(params or {})
        if url.removeprefix(_GMAIL_BASE).startswith("/messages/") and str(query.get("format")) == (
            "metadata"
        ):
            self.metadata_calls += 1
        return super().get(url, params=query, access_token=access_token)


def _b64url_decode(encoded: bytes) -> str:
    padded = encoded.decode("ascii") + "=" * (-len(encoded) % 4)
    return urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _parse_raw(text: str) -> tuple[dict[str, str], str]:
    head, _, body = text.partition("\r\n\r\n")
    headers: dict[str, str] = {}
    for line in head.split("\r\n"):
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    return headers, body


def b64url(raw: bytes) -> str:
    """Encode exactly as Gmail's ``messages.send`` expects: base64url, unpadded."""
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")
