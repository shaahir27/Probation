"""Bridge committed Gmail observations into the existing engine ingest path.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 4, 7, 11 (row 30) and 12, docs/CONTRACT.md
section 3. Selected Gmail resources are read by the D4 connector and committed to the private
store; this bridge only turns committed, in-cohort INCOMING observations into ordinary
``sources``/``raw_items`` rows and lets the unchanged ``ingest_situations`` worker have the mail
pack build ``situations``. Each arrival's relative ``payload_ref`` is resolved through an injected
``PayloadReader``, so the raw item carries the persisted sender, recipients, subject, body, thread
and RFC identity instead of a contentless shell. SENT is an observation, never a decision; label
events and tombstones never name an arrival. A missing, escaping, foreign or hash-mismatched
payload raises a typed safe code before any row is written, so an empty situation cannot exist.
No provider call, no LLM call, no second pipeline, and no write outside the ingestor's three tables.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Final

from probation.connectors.grants import gmail_source_id
from probation.connectors.types import ConnectorError, MessagePayload, PayloadReader
from probation.core.clock import Clock
from probation.db.access import Role, RoleAccess
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.gmail_projection import GmailProjector, ProjectedMessage
from probation.workers.ingestor import ingest_situations

GMAIL_PACK: Final = "mail"
GMAIL_SOURCE_KIND: Final = "gmail_live"
_MAX_PAYLOAD_REF: Final = 512

_SOURCE_SQL = """INSERT INTO sources (id,pack,kind,ref,imported_at)
 VALUES(?,?,?,?,?) ON CONFLICT(id) DO NOTHING"""

_RAW_ITEM_SQL = """INSERT OR IGNORE INTO raw_items
 (id,source_id,pack,item_kind,source_ref,occurred_at,known_at,payload_json,content_hash)
 VALUES(?,?, 'mail',?,?,?,?,?,?)"""


@dataclass(frozen=True)
class IngestResult:
    """What one bridge run stored and what the existing ingestor extracted, safe to log."""

    raw_items_stored: int
    situations_built: int


def source_id_for(connection_id: str) -> str:
    """Deterministic engine source id for one opaque connector connection."""
    return gmail_source_id(connection_id)


def raw_item_id_for(connection_id: str, native_message_id: str) -> str:
    """Deterministic raw-item id; the native Gmail id, never a history id or RFC Message-ID."""
    return f"gmail:{connection_id}:{native_message_id}"


def _relative_payload_ref(payload_ref: object, connection_id: str) -> str:
    """Accept exactly ``<connection>/<file>.json`` below the payload root; refuse escapes.

    The injected reader verifies the file's ACL and content hash. This boundary check is separate
    so an absolute path, a Windows path, a traversal segment or another connection's ref is never
    even handed to the reader.
    """
    if not isinstance(payload_ref, str) or not payload_ref or len(payload_ref) > _MAX_PAYLOAD_REF:
        raise ConnectorError("invalid_payload_ref")
    if any(ord(char) < 32 for char in payload_ref):
        raise ConnectorError("invalid_payload_ref")
    if payload_ref.startswith(("/", "\\")) or payload_ref[1:2] == ":" or "\\" in payload_ref:
        raise ConnectorError("payload_ref_escapes_root")
    parts = payload_ref.split("/")
    if len(parts) != 2 or any(part in ("", ".", "..") for part in parts):
        raise ConnectorError("payload_ref_escapes_root")
    if parts[0] != connection_id:
        raise ConnectorError("payload_ref_foreign_connection")
    if not parts[1].endswith(".json") or len(parts[1]) == len(".json"):
        raise ConnectorError("invalid_payload_ref")
    return payload_ref


def _content_fields(message: ProjectedMessage, payload: MessagePayload) -> dict[str, Any]:
    """The raw-item keys the mail pack consumes, taken only from the verified payload."""
    return {
        "from": payload.from_addr,
        "to": ", ".join(payload.to_addr),
        "cc": ", ".join(payload.cc_addrs),
        "subject": payload.subject,
        "body": payload.body_text,
        "has_attachment": payload.attachment_present,
        "thread_id": payload.thread_id or message.thread_id,
        "rfc_message_id": payload.rfc_message_id or message.rfc_message_id,
    }


class GmailIngestBridge:
    """Feed committed Gmail observations to the engine through the unchanged ingest path."""

    def __init__(
        self,
        *,
        access: ConnectorAccess,
        engine: sqlite3.Connection,
        clock: Clock,
        connection_id: str,
        account_id: str,
        payloads: PayloadReader,
    ) -> None:
        if not isinstance(access, ConnectorAccess) or access.authority != "ingestor":
            raise ConnectorError("bridge_needs_ingestor_authority")
        if getattr(engine, "bound_role", None) != Role.INGESTOR.value:
            raise ValueError("Gmail ingest bridge requires a permanently bound ingestor connection")
        if not connection_id or not account_id:
            raise ValueError("Gmail ingest bridge requires a connection and account identity")
        if not callable(getattr(payloads, "read", None)):
            raise ConnectorError("payload_reader_unconfigured")
        self._access = access
        self._engine = engine
        self._clock = clock
        self._connection_id = connection_id
        self._account_id = account_id
        self._payloads = payloads
        self._role = RoleAccess(engine, Role.INGESTOR)

    @property
    def source_id(self) -> str:
        return source_id_for(self._connection_id)

    def run(self) -> IngestResult:
        """Store new arrivals, then let the existing ingestor build their situations.

        The two units commit separately: a crash after the raw items but before extraction leaves
        durable input that the next run extracts, and re-observation cannot duplicate either row.
        """
        self._register_source()
        stored = self._store_new_arrivals()
        with self._role.transaction():
            built = ingest_situations(self._engine)
        return IngestResult(raw_items_stored=stored, situations_built=built)

    def _register_source(self) -> None:
        source_id = self.source_id
        with self._role.transaction():
            self._role.execute_write(
                "sources",
                _SOURCE_SQL,
                (source_id, GMAIL_PACK, GMAIL_SOURCE_KIND, self._account_id, self._clock.now_iso()),
            )
        row = self._role.conn.execute(
            "SELECT pack,kind,ref FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        if row is None or (row["pack"], row["kind"], row["ref"]) != (
            GMAIL_PACK,
            GMAIL_SOURCE_KIND,
            self._account_id,
        ):
            raise ConnectorError("source_row_conflict")

    def _store_new_arrivals(self) -> int:
        projection = GmailProjector(
            access=self._access,
            clock=self._clock,
            connection_id=self._connection_id,
            account_id=self._account_id,
        ).project()
        source_id = self.source_id
        stored = 0
        with self._role.transaction():
            for message in projection.incoming():
                params = self._raw_item_params(message, source_id)
                if params is None:
                    continue
                stored += self._role.execute_write("raw_items", _RAW_ITEM_SQL, params).rowcount
        return stored

    def _raw_item_params(self, message: ProjectedMessage, source_id: str) -> tuple[Any, ...] | None:
        item_id = raw_item_id_for(self._connection_id, message.native_message_id)
        if self._role.conn.execute("SELECT 1 FROM raw_items WHERE id=?", (item_id,)).fetchone():
            return None  # already ingested; payload retention must never break a repeat run
        if not message.has_body:
            if message.payload_ref is None and message.content_hash:
                raise ConnectorError("payload_ref_missing")
            return None  # a label-only record, or a tombstone that names no arrival
        payload = self._read_payload(message)
        item = message.as_raw_item()
        if item is None:
            return None
        body: dict[str, Any] = json.loads(item["payload_json"])
        body.update(_content_fields(message, payload))
        # The mail pack reads "labels" to skip SPAM/DRAFT and "message_id" to match a reply.
        body["labels"] = list(message.label_ids)
        body["message_id"] = (
            payload.rfc_message_id or message.rfc_message_id or message.native_message_id
        )
        # Section 12: occurrence is the provider's ``internalDate``, never local knowledge time.
        occurred_at = payload.occurred_at or item["occurred_at"]
        return (
            item_id,
            source_id,
            item["item_kind"],
            message.native_message_id,
            occurred_at,
            item["known_at"],
            json.dumps(body, sort_keys=True),
            item["content_hash"],
        )

    def _read_payload(self, message: ProjectedMessage) -> MessagePayload:
        """Read the observation's own payload; a changed or foreign file is never a message."""
        payload_ref = _relative_payload_ref(message.payload_ref, self._connection_id)
        payload = self._payloads.read(payload_ref)
        if payload.native_message_id != message.native_message_id:
            raise ConnectorError("payload_identity_mismatch")
        if payload.content_hash != message.content_hash:
            raise ConnectorError("payload_hash_mismatch")
        return payload
