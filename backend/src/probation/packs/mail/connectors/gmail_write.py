"""Gmail write adapter: ``MailExecutionIO`` over a provider with no compare-and-set.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1, 2, 4 and 7. ``users.messages.modify`` takes
no precondition and a Message has no ETag (C1), so the contract's atomic compare-and-set degrades
to check-then-act. That degradation is made honest here, never hidden: the ``revision`` this
adapter re-reads immediately before every write, and the ``label_versions`` evidence its undo rests
on, are computed by ``gmail_versions``, which refuses to guess either (see its fail-closed rules).

* Gmail has no idempotency key (C8): a lost answer stays ``unknown``, is journaled once, is never
  resent, and absence of evidence is never converted into a claim of failure.
* Archive drops ``INBOX`` only; trash uses the reversible ``trash``/``untrash`` methods; undo is a
  second ``apply_mail`` restoring only what Probation changed. No permanent-delete, settings or
  filter endpoint is ever addressed and no native id leaves the private store unhashed.
* A reply threads only on the original's provider-resolved identity: ``threadId`` plus
  ``In-Reply-To``/``References`` holding the RFC ``Message-ID``, plus the reviewed subject (C7).
  The frozen payload's ``in_reply_to`` is a native Gmail id and never becomes a header.
"""

from base64 import urlsafe_b64encode
from collections.abc import Mapping
from typing import Any, Final, Literal, cast

from probation.connectors.types import (
    ConnectorError,
    HttpResult,
    HttpTransport,
    MessagePayload,
    PayloadReader,
    SelectionViolation,
)
from probation.core.clock import Clock
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.capability import CapabilityGate
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_transport import quote_native_id
from probation.packs.mail.connectors.gmail_versions import (
    BASE_URL,
    INBOX,
    SENT,
    TRASH,
    AnchorStore,
    EffectAnchor,
    GmailVersioning,
    InMemoryAnchorStore,
    MessageState,
    as_sequence,
    decode_response,
    effect_operation,
    gmail_revision,
    hashed_native_ref,
    header_value,
    intended_labels,
    reply_threading,
)
from probation.packs.mail.lifecycle_io import MailConflict, MailReceipt, MailSnapshot
from probation.packs.mail.lifecycle_operations import payload_digest

_CONFLICT: Final = "mail_revision_conflict"
#: The only endpoints this adapter may ever address (C6, CONTRACT hands-off rules).
_ALLOWED_WRITE_SUFFIXES: Final = ("/trash", "/untrash", "/modify", "/send")
Outcome = Literal["confirmed", "failed", "unknown"]


def build_raw_message(values: Mapping[str, Any], *, rfc_message_id: str | None = None) -> str:
    """RFC 2822 for ``messages.send``. Header injection fails closed; bodies are never logged.

    ``values['in_reply_to']`` is a native Gmail id (frozen ``lifecycle_operations`` contract) and
    is deliberately never copied into a header: Gmail threads on the sender's ``Message-ID``.
    Threading headers come only from ``rfc_message_id``, already bracketed exactly once by
    ``gmail_versions.bracketed_message_id``. A reply without it refuses instead of guessing.
    """
    pairs = (
        ("From", "from_addr"),
        ("To", "to_addr"),
        ("Message-ID", "message_id"),
        ("Subject", "subject"),
    )
    lines = [text for text in (_header(n, values.get(k)) for n, k in pairs) if text]
    is_reply = bool(str(values.get("in_reply_to") or "").strip())
    if is_reply != bool(rfc_message_id):
        raise MailConflict("reply_threading_unavailable")
    if rfc_message_id:
        lines += [
            _header("In-Reply-To", rfc_message_id),
            _header("References", rfc_message_id),
        ]
    body = str(values.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\r\n".join(lines) + "\r\n\r\n" + body


class GmailMailExecutionIO:
    """The Executor's mail write path against Gmail. Reads stay inside the proven cohort."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        read: GmailReadConnector,
        connection_id: str,
        account_id: str,
        write_token: str,
        clock: Clock,
        gate: CapabilityGate,
        store: ConnectorAccess,
        anchors: AnchorStore | None = None,
        payload_reader: PayloadReader | None = None,
        retained_from_history_id: int = 0,
        max_history_pages: int = 10,
        sent_evidence_limit: int = 25,
    ) -> None:
        self.gate = gate
        self._transport = transport
        self._read = read
        self._connection_id = connection_id
        self._account_id = account_id
        self._token = write_token
        self._clock = clock
        self._store = store
        self._payloads = payload_reader
        self._anchors: AnchorStore = anchors or InMemoryAnchorStore()
        self._versioning = GmailVersioning(
            transport,
            read=read,
            connection_id=connection_id,
            access_token=write_token,
            store=store,
            anchors=self._anchors,
            retained_from_history_id=retained_from_history_id,
            max_history_pages=max_history_pages,
        )
        self._sent_limit = sent_evidence_limit
        self._intents: dict[str, dict[str, Any]] = {}

    # -- snapshots --------------------------------------------------------------------------
    def snapshot_mail(self, resource_id: str) -> MailSnapshot:
        native_id = self._native(resource_id)
        state = self._versioning.state(native_id)
        return MailSnapshot(
            resource_id,
            native_id,
            state.thread_id,
            state.labels,
            state.revision,
            self._versioning.label_versions(native_id, state.message_history_id),
        )

    def current_labels(self, resource_id: str) -> frozenset[str]:
        """The provider's label set for a cohort resource. Never a cached or local guess."""
        return frozenset(self._versioning.state(self._native(resource_id)).labels)

    def native_ref(self, snapshot: MailSnapshot) -> str:
        return self._ref(snapshot.native_message_id)

    def journal_state(self, operation_id: str) -> str | None:
        row = self._store.one(
            "SELECT outcome FROM gmail_effect_receipts WHERE operation_id=?", (operation_id,)
        )
        return None if row is None else str(row["outcome"])

    def _native(self, resource_id: str) -> str:
        native_id = str(resource_id)
        if not native_id or len(native_id) > 512 or any(char < " " for char in native_id):
            raise MailConflict("invalid_resource_id")
        if native_id not in self._read.proven():
            raise SelectionViolation("resource_outside_cohort")
        return native_id

    # -- effects ----------------------------------------------------------------------------
    def apply_mail(
        self,
        operation_id: str,
        payload_hash: str,
        payload: dict[str, Any],
        expected_revision: str,
    ) -> MailReceipt:
        if payload_digest(payload) != payload_hash:
            raise MailConflict("operation_payload_hash_mismatch")
        prior = self._receipt(operation_id)
        if prior is not None:
            if str(prior["payload_hash"]) != payload_hash:
                raise MailConflict("operation_payload_conflict")
            if str(prior["outcome"]) != "unknown":
                return _from_row(prior)
            # A dispatch whose answer was lost is reconciled from evidence, never re-issued.
            return self.reconcile_mail(operation_id, payload_hash)
        kind = str(payload.get("type", ""))
        if kind == "labels":
            return self._apply_labels(operation_id, payload_hash, payload, str(expected_revision))
        if kind == "send":
            return self._apply_send(operation_id, payload_hash, payload, str(expected_revision))
        raise MailConflict("unsupported_mail_operation")

    def _apply_labels(
        self,
        operation_id: str,
        payload_hash: str,
        payload: dict[str, Any],
        expected_revision: str,
    ) -> MailReceipt:
        resource_id = str(payload["resource_id"])
        add = [str(item) for item in as_sequence(payload.get("add_labels"))]
        remove = [str(item) for item in as_sequence(payload.get("remove_labels"))]
        verdict = self.gate.require(effect_operation(add, remove))
        degraded = verdict.safe_reason if verdict.degraded else None
        native_id = self._native(resource_id)
        before = self._versioning.state(native_id)
        anchor = before.message_history_id
        effect = payload.get("performed_at") is not None
        if before.revision != expected_revision:
            # Gmail would have applied this anyway. Because we re-read first, we can say it did not.
            receipt = MailReceipt("failed", safe_code=_CONFLICT, confirmed_no_effect=True)
        else:
            # An effect the reader cannot anchor in provable history could never be undone.
            baseline = self._versioning.label_versions(native_id, anchor) if effect else {}
            receipt = self._write_labels(native_id, before, add, remove, payload, degraded=degraded)
            if effect and receipt.outcome == "confirmed":
                self._anchors.save(EffectAnchor(native_id, anchor, before.revision, baseline))
        return self._journal(operation_id, payload_hash, payload, receipt, anchor)

    def _write_labels(
        self,
        native_id: str,
        before: MessageState,
        add: list[str],
        remove: list[str],
        payload: dict[str, Any],
        *,
        degraded: str | None = None,
    ) -> MailReceipt:
        """Dispatch, then verify that the intended labels really landed. Never trust the status."""
        extra = {} if degraded is None else {"degraded_reason": degraded}
        result = self._post(native_id, add, remove)
        if not result.ok:
            return MailReceipt("unknown", safe_code=f"transport_status_{result.status}")
        after = self._versioning.state(native_id)
        landed, intended = set(after.labels), intended_labels(before.labels, add, remove)
        if landed != intended:
            silent = landed == set(before.labels)
            return MailReceipt(
                "failed" if silent else "unknown",
                safe_code="mail_effect_diverged",
                after_state={"labels": sorted(landed), "intended": sorted(intended), **extra},
                confirmed_no_effect=silent,
            )
        return MailReceipt(
            "confirmed",
            self._ref(native_id),
            after_state={
                "labels": sorted(landed),
                "revision": after.revision,
                "message_history_id": after.message_history_id,
                "executed_at": payload.get("performed_at"),
                **extra,
            },
        )

    def _post(self, native_id: str, add: list[str], remove: list[str]) -> HttpResult:
        root = f"/messages/{quote_native_id(native_id)}"
        if add == [TRASH] and not remove:
            return self._dispatch(f"{root}/trash", None)
        if remove == [TRASH] and not add:
            return self._dispatch(f"{root}/untrash", None)
        return self._dispatch(f"{root}/modify", {"addLabelIds": add, "removeLabelIds": remove})

    def _dispatch(self, path: str, body: Mapping[str, object] | None) -> HttpResult:
        if not path.endswith(_ALLOWED_WRITE_SUFFIXES):
            raise MailConflict("forbidden_provider_endpoint")
        return self._transport.post(f"{BASE_URL}{path}", json_body=body, access_token=self._token)

    def _apply_send(
        self,
        operation_id: str,
        payload_hash: str,
        payload: dict[str, Any],
        expected_revision: str,
    ) -> MailReceipt:
        values = payload.get("message")
        if not isinstance(values, Mapping):
            raise MailConflict("send_binding_incomplete")
        self.gate.require("send")
        before = self._versioning.state(self._native(str(payload["resource_id"])))
        if before.revision != expected_revision:
            receipt = MailReceipt("failed", safe_code=_CONFLICT, confirmed_no_effect=True)
        else:
            receipt = self._dispatch_send(values, str(payload["resource_id"]))
        return self._journal(
            operation_id, payload_hash, payload, receipt, before.message_history_id
        )

    def _dispatch_send(self, values: Mapping[str, Any], resource_id: str) -> MailReceipt:
        """Send once, threading a reply on the original's provider-resolved identity (C7, C8).

        ``threadId`` plus ``In-Reply-To``/``References`` plus the reviewed subject are all
        required. If the original's RFC ``Message-ID`` or thread id cannot be resolved from the
        payload store, nothing is posted: a fabricated or native header would start a new thread.
        """
        try:
            thread_id, rfc_id = self._reply_address(values, resource_id)
        except MailConflict:
            return MailReceipt(
                "failed", safe_code="reply_threading_unavailable", confirmed_no_effect=True
            )
        raw = build_raw_message(values, rfc_message_id=rfc_id).encode("utf-8")
        body: dict[str, object] = {"raw": _b64url(raw)}
        if thread_id:
            body["threadId"] = thread_id
        result = self._dispatch("/messages/send", body)
        created = {} if not result.ok else decode_response(result)
        native_id = str(created.get("id", ""))
        if not native_id:
            return MailReceipt("unknown", safe_code="transport_ambiguous")
        return MailReceipt(
            "confirmed",
            self._ref(native_id),
            after_state={
                "thread_id": str(created.get("threadId", "")),
                "executed_at": str(values.get("sent_at", "")),
            },
        )

    def _reply_address(self, values: Mapping[str, Any], resource_id: str) -> tuple[str, str | None]:
        """(thread id, bracketed RFC id) for a reply; ("", None) for a forward/new message."""
        reviewed_native = str(values.get("in_reply_to") or "").strip()
        if not reviewed_native:
            return "", None
        if reviewed_native != resource_id:
            # The reviewed payload names a different original than the resource it binds.
            raise MailConflict("reply_threading_unavailable")
        original = self._original_payload(resource_id)
        if original is None:
            raise MailConflict("reply_threading_unavailable")
        return reply_threading(
            original, resource_id=resource_id, reviewed_thread_id=values.get("thread_id")
        )

    def _original_payload(self, resource_id: str) -> MessagePayload | None:
        """The persisted original behind ``resource_id``. Missing content refuses, never degrades."""
        if self._payloads is None:
            return None
        row = self._store.one(
            "SELECT payload_ref FROM gmail_observations WHERE connection_id=? AND account_id=?"
            " AND native_message_id=? AND payload_ref IS NOT NULL"
            " ORDER BY history_id DESC LIMIT 1",
            (self._connection_id, self._account_id, resource_id),
        )
        ref = None if row is None else row["payload_ref"]
        if not isinstance(ref, str) or not ref:
            return None
        try:
            return self._payloads.read(ref)
        except (ConnectorError, OSError):
            # A missing or hash-mismatched payload store fails closed: no header is invented.
            return None

    # -- reconciliation ---------------------------------------------------------------------
    def reconcile_mail(self, operation_id: str, payload_hash: str) -> MailReceipt:
        row = self._receipt(operation_id)
        if row is None:
            return MailReceipt("unknown", safe_code="receipt_not_found")
        if str(row["payload_hash"]) != payload_hash:
            raise MailConflict("operation_payload_conflict")
        if str(row["outcome"]) != "unknown":
            return _from_row(row)
        payload = self._intents.get(operation_id)
        if payload is None:
            # Nothing in this process can say what was dispatched. An unknown is never converted
            # into a claim, and a send is never re-issued on the strength of a missing receipt.
            return MailReceipt("unknown", safe_code="needs_reconciliation")
        if str(payload.get("type")) == "send":
            found = self._find_sent(payload)
            if found is not None:
                return found
        return _from_row(row)

    def _find_sent(self, payload: Mapping[str, Any]) -> MailReceipt | None:
        """Bounded SENT search (C8), correlated on the RFC Message-ID we authored. Never a guess."""
        values = payload.get("message")
        if not isinstance(values, Mapping):
            return None
        listed = decode_response(
            self._transport.get(
                f"{BASE_URL}/messages",
                params={"labelId": SENT, "maxResults": self._sent_limit},
                access_token=self._token,
            )
        )
        rfc_id = str(values.get("message_id", ""))
        for item in as_sequence(listed.get("messages")):
            native_id = str(item.get("id", "")) if isinstance(item, Mapping) else ""
            if not native_id:
                continue
            found = decode_response(
                self._transport.get(
                    f"{BASE_URL}/messages/{quote_native_id(native_id)}",
                    params={"format": "metadata", "metadataHeaders": "Message-ID"},
                    access_token=self._token,
                )
            )
            if header_value(found, "Message-ID") == rfc_id:
                return MailReceipt(
                    "confirmed",
                    self._ref(native_id),
                    after_state={"resolved_from": "bounded_sent_evidence_c8"},
                )
        return MailReceipt("unknown", safe_code="needs_reconciliation")

    # -- private journal ----------------------------------------------------------------------
    def _receipt(self, operation_id: str) -> Any:
        return self._store.one(
            "SELECT * FROM gmail_effect_receipts WHERE operation_id=?", (operation_id,)
        )

    def _journal(
        self,
        operation_id: str,
        payload_hash: str,
        payload: dict[str, Any],
        receipt: MailReceipt,
        anchor_history_id: int | None,
    ) -> MailReceipt:
        """One immutable private row per dispatch: the local half of correlation, never Gmail's."""
        self._intents[operation_id] = payload
        undo = str(payload.get("type")) == "labels" and payload.get("performed_at") is None
        self._store.write(
            "gmail_effect_receipts",
            """INSERT INTO gmail_effect_receipts
 (operation_id,connection_id,account_id,action_id,operation,outcome,native_ref_hash,
  anchor_history_id,payload_hash,safe_code,verified_no_effect,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                operation_id,
                self._connection_id,
                self._account_id,
                operation_id.rsplit(":", 1)[0],
                "undo" if undo else "execute",
                receipt.outcome,
                receipt.native_ref,
                anchor_history_id,
                payload_hash,
                receipt.safe_code,
                1 if receipt.confirmed_no_effect else 0,
                self._clock.now_iso(),
            ),
        )
        return receipt

    def _ref(self, native_message_id: str) -> str:
        return hashed_native_ref(
            connection_id=self._connection_id,
            account_id=self._account_id,
            native_message_id=native_message_id,
        )


def _from_row(row: Any) -> MailReceipt:
    return MailReceipt(
        cast("Outcome", str(row["outcome"])),
        None if row["native_ref_hash"] is None else str(row["native_ref_hash"]),
        safe_code=None if row["safe_code"] is None else str(row["safe_code"]),
        confirmed_no_effect=bool(row["verified_no_effect"]),
    )


def _header(name: str, value: object) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if any(char in text for char in ("\r", "\n", "\x00")):
        raise MailConflict(f"unsafe_{name.lower()}_header")
    return f"{name}: {text}"


def _b64url(raw: bytes) -> str:
    """base64url, unpadded: exactly what ``messages.send`` expects."""
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


#: ``gmail_versions`` owns the version maths; these names stay importable from the adapter.
__all__ = ["BASE_URL", "INBOX", "gmail_revision"]
