"""Strict JSON-byte request/reply types for the Brain to ask the Webfacts role."""

import sqlite3
import struct
import threading
from collections.abc import Callable
from queue import Empty, Full, Queue
from typing import Any, BinaryIO, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from probation.core.clock import Clock, elapsed_seconds, timestamp_key
from probation.core.hashing import det_id
from probation.core.history import HistoryView
from probation.core.types import Features, Situation
from probation.llm.jobs import MailReader
from probation.web.types import VerificationCard
from probation.web.view import RestrictionOnly
from probation.workers.d5_verification import WebObservation

MAX_MESSAGE_BYTES = 65_536
MAX_WAIT_SECONDS = 180
_POLL_SECONDS = 0.5
_FRAME = struct.Struct("!I")

#: Codes a Webfacts reply may carry when no trustworthy per-request identity exists.
_REFUSED_IDENTITY: Final = "ipc-refused"
#: Reason codes. Each names one bounded failure; none carries request or message content.
REASON_MALFORMED: Final = "ipc_request_invalid"
REASON_OVERSIZED: Final = "ipc_message_too_large"
REASON_INTERNAL: Final = "webfacts_internal_failure"


class WebFactsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(default=1, ge=1, le=1)
    request_id: str = Field(min_length=1, max_length=128)
    situation_id: str = Field(min_length=1, max_length=256)
    content_hash: str = Field(min_length=1, max_length=128)
    features_hash: str = Field(min_length=1, max_length=128)
    semantic_identity: str = Field(min_length=1, max_length=128)
    cutoff: str = Field(min_length=1, max_length=40)
    sender_tier: str = Field(min_length=1, max_length=64)
    reader: dict[str, Any]

    def validate_reader(self) -> "WebFactsRequest":
        MailReader.model_validate(self.reader)
        return self


class WebFactsReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(default=1, ge=1, le=1)
    request_id: str = Field(min_length=1, max_length=128)
    situation_id: str = Field(min_length=1, max_length=256)
    content_hash: str = Field(min_length=1, max_length=128)
    features_hash: str = Field(min_length=1, max_length=128)
    semantic_identity: str = Field(min_length=1, max_length=128)
    cutoff: str = Field(min_length=1, max_length=40)
    cap: int = Field(ge=0, le=3)
    entities: list[RestrictionOnly] = Field(default_factory=list, max_length=32)
    card: VerificationCard | None = None
    reasons: list[str] = Field(default_factory=list, max_length=64)
    unavailable: bool = False

    def observation(self) -> WebObservation:
        return WebObservation(
            cap=self.cap,
            entities=[entity.model_dump(mode="json") for entity in self.entities],
            card=self.card,
            reasons=tuple(self.reasons),
        )


class IpcMessageTooLarge(OSError):
    """A framed payload exceeds the bound both roles agreed on; the request is refused."""


class IpcFrameInvalid(OSError):
    """The byte stream itself is unusable, so nothing further can be truthfully replied."""


class ByteChannel(Protocol):
    def send_bytes(self, data: bytes) -> None: ...

    def recv_bytes(self, maxlength: int) -> bytes: ...

    def poll(self, timeout: float = 0.0) -> bool: ...


class StdioChannel:
    """Length-framed private child stdio reserved exclusively for JSON IPC."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self._reader, self._writer = reader, writer
        self._messages: Queue[bytes | None] = Queue(maxsize=1)
        self._pending: bytes | None = None
        self._write_lock = threading.Lock()
        threading.Thread(target=self._read_loop, daemon=True, name="d6-ipc-reader").start()

    def send_bytes(self, data: bytes) -> None:
        if not 0 < len(data) <= MAX_MESSAGE_BYTES:
            raise ValueError("ipc_message_size_invalid")
        with self._write_lock:
            self._writer.write(_FRAME.pack(len(data)))
            self._writer.write(data)
            self._writer.flush()

    def poll(self, timeout: float = 0.0) -> bool:
        if self._pending is not None:
            return True
        try:
            self._pending = self._messages.get(timeout=max(0.0, timeout))
        except Empty:
            return False
        return self._pending is not None

    def recv_bytes(self, maxlength: int) -> bytes:
        if self._pending is None and not self.poll():
            raise EOFError("ipc_message_absent")
        payload, self._pending = self._pending, None
        if payload is None:
            raise IpcFrameInvalid("ipc_channel_closed")
        if len(payload) > maxlength:
            raise IpcMessageTooLarge("ipc_message_too_large")
        return payload

    def _read_loop(self) -> None:
        try:
            while True:
                header = self._read_exact(_FRAME.size)
                size = _FRAME.unpack(header)[0]
                if not 0 < size <= MAX_MESSAGE_BYTES:
                    raise IpcFrameInvalid("ipc_frame_size_invalid")
                self._messages.put(self._read_exact(size))
        except (EOFError, OSError):
            try:
                self._messages.put_nowait(None)
            except Full:
                pass

    def _read_exact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self._reader.read(remaining)
            if not chunk:
                raise EOFError("ipc_channel_closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def encode_message(model: BaseModel) -> bytes:
    payload = model.model_dump_json().encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("ipc_message_too_large")
    return payload


def decode_request(payload: bytes) -> WebFactsRequest:
    if len(payload) > MAX_MESSAGE_BYTES:
        raise IpcMessageTooLarge(REASON_OVERSIZED)
    try:
        return WebFactsRequest.model_validate_json(payload).validate_reader()
    except (ValidationError, UnicodeDecodeError) as exc:
        raise ValueError(REASON_MALFORMED) from exc


def decode_reply(payload: bytes) -> WebFactsReply:
    if len(payload) > MAX_MESSAGE_BYTES:
        raise IpcMessageTooLarge(REASON_OVERSIZED)
    try:
        return WebFactsReply.model_validate_json(payload)
    except (ValidationError, UnicodeDecodeError) as exc:
        raise ValueError("ipc_reply_invalid") from exc


class BrainWebFactsClient:
    """Synchronous bounded RPC client; it transmits no mail text or feature payload.

    The plan allows one outstanding verification per Brain, so the whole request→reply cycle is
    exclusive. A second concurrent caller is refused with a restriction cap rather than queued or
    interleaved on the shared frame stream: queuing would hold the Brain's batch hostage and a
    single frame lock cannot keep request and reply paired across two callers.
    """

    def __init__(self, channel: ByteChannel) -> None:
        self._channel = channel
        self._cycle = threading.Lock()
        self._usable = True

    def verify(self, request: WebFactsRequest) -> WebObservation:
        if not self._usable:
            return WebObservation(cap=0, reasons=("webfacts_unavailable",))
        if not self._cycle.acquire(blocking=False):
            return WebObservation(cap=0, reasons=("webfacts_busy",))
        try:
            return self._verify(request)
        finally:
            self._cycle.release()

    def _verify(self, request: WebFactsRequest) -> WebObservation:
        try:
            self._channel.send_bytes(encode_message(request))
        except (OSError, ValueError):
            self._usable = False
            return WebObservation(cap=0, reasons=("webfacts_unavailable",))
        started = elapsed_seconds()
        while not self._channel.poll(_POLL_SECONDS):
            if elapsed_seconds() - started >= MAX_WAIT_SECONDS:
                self._usable = False
                return WebObservation(cap=0, reasons=("webfacts_timeout",))
        try:
            reply = decode_reply(self._channel.recv_bytes(MAX_MESSAGE_BYTES))
        except (EOFError, OSError, ValueError):
            self._usable = False
            return WebObservation(cap=0, reasons=("webfacts_unavailable",))
        if any(
            getattr(reply, field) != getattr(request, field)
            for field in (
                "request_id",
                "situation_id",
                "content_hash",
                "features_hash",
                "semantic_identity",
                "cutoff",
            )
        ):
            self._usable = False
            return WebObservation(cap=0, reasons=("webfacts_response_mismatch",))
        if reply.unavailable:
            return WebObservation(cap=0, reasons=tuple(reply.reasons) or ("webfacts_unavailable",))
        return reply.observation()


def make_verifier(
    client: BrainWebFactsClient,
    semantic_identity: str,
) -> Callable[[Situation, Features, HistoryView], WebObservation]:
    """Build the D5 callback using only validated reader fields and opaque identities."""

    def verify(situation: Situation, features: Features, history: HistoryView) -> WebObservation:
        if not features.reader_ok or features.reader is None:
            return WebObservation(cap=0, reasons=("reader_unavailable",))
        reader = MailReader.model_validate(features.reader).model_dump(mode="json")
        request = WebFactsRequest(
            request_id=det_id(
                "d6-webfacts-request-v1",
                situation.id,
                situation.content_hash,
                features.features_hash,
                history.as_of,
            ),
            situation_id=situation.id,
            content_hash=situation.content_hash,
            features_hash=features.features_hash,
            semantic_identity=semantic_identity,
            cutoff=history.as_of,
            sender_tier=str(features.deterministic.get("sender_tier", "unknown")),
            reader=reader,
        )
        return client.verify(request)

    return verify


class _RequestRefused(Exception):
    """A request that cannot be answered truthfully; the reply is an unavailable observation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _AuthorityLost(Exception):
    """This role cannot establish the source of truth the request depends on; stop serving."""


def _refused_reply(code: str) -> WebFactsReply:
    """A typed unavailable reply with no identity, because none could be trusted."""
    sentinel = f"{_REFUSED_IDENTITY}:{code}"[:128]
    return WebFactsReply(
        request_id=sentinel,
        situation_id=sentinel,
        content_hash=sentinel,
        features_hash=sentinel,
        semantic_identity=sentinel,
        cutoff="1970-01-01T00:00:00Z",
        cap=0,
        reasons=[code],
        unavailable=True,
    )


def _reply(channel: ByteChannel, message: WebFactsReply) -> bool:
    try:
        channel.send_bytes(encode_message(message))
    except (EOFError, OSError, ValueError):
        return False
    return True


def serve_one(
    channel: ByteChannel,
    *,
    conn: sqlite3.Connection,
    clock: Clock,
    semantic_identity: Callable[[], str],
    verify: Callable[[Situation, Features, HistoryView], WebObservation],
) -> bool:
    """Validate a request against Webfacts-owned bounded source rows, then return typed facts.

    Only a genuine framing/transport failure, or a cutoff this role cannot authorize, ends the
    loop. A malformed, oversized or unknown-field request is answered with an explicit unavailable
    reply, so the Brain fails closed immediately instead of burning its full wait, and the role
    keeps serving. A refused request never reaches the verifier, so no paid lookup is retried.
    """
    try:
        payload = channel.recv_bytes(MAX_MESSAGE_BYTES)
    except IpcMessageTooLarge:
        return _reply(channel, _refused_reply(REASON_OVERSIZED))
    except (EOFError, OSError):
        return False
    try:
        request = decode_request(payload)
    except IpcMessageTooLarge:
        return _reply(channel, _refused_reply(REASON_OVERSIZED))
    except ValueError:
        return _reply(channel, _refused_reply(REASON_MALFORMED))
    try:
        observation = _verify_request(
            request,
            conn=conn,
            clock=clock,
            semantic_identity=semantic_identity,
            verify=verify,
        )
    except _AuthorityLost:
        return False
    except _RequestRefused as refused:
        return _reply(channel, _refused_reply(refused.code))
    except Exception:
        observation = WebObservation(cap=0, reasons=(REASON_INTERNAL,))
        return _reply(channel, _request_reply(request, observation, unavailable=True))
    return _reply(channel, _request_reply(request, observation))


def _verify_request(
    request: WebFactsRequest,
    *,
    conn: sqlite3.Connection,
    clock: Clock,
    semantic_identity: Callable[[], str],
    verify: Callable[[Situation, Features, HistoryView], WebObservation],
) -> WebObservation:
    if timestamp_key(request.cutoff) > timestamp_key(clock.now_iso()):
        raise _AuthorityLost
    history = HistoryView(conn, request.cutoff)
    row = next(
        (
            item
            for item in history.get_situations(pack="mail", family="email_action")
            if str(item["id"]) == request.situation_id
        ),
        None,
    )
    raw = None if row is None else history.get_raw_item(str(row["raw_item_id"]))
    if (
        row is None
        or raw is None
        or str(row["content_hash"]) != request.content_hash
        or semantic_identity() != request.semantic_identity
        or str(row["occurred_at"]) > request.cutoff
    ):
        raise _RequestRefused("ipc_source_mismatch")
    situation = Situation.model_validate(dict(row))
    # Webfacts receives only validated reader data and the public sender tier. The complete
    # deterministic feature row remains Brain-owned and never crosses this boundary.
    features = Features(
        situation_id=request.situation_id,
        deterministic={"sender_tier": request.sender_tier},
        reader=request.reader,
        reader_ok=True,
        featurizer_version=request.semantic_identity,
        features_hash=request.features_hash,
    )
    return verify(situation, features, history)


def _request_reply(
    request: WebFactsRequest, observation: WebObservation, *, unavailable: bool = False
) -> WebFactsReply:
    return WebFactsReply(
        request_id=request.request_id,
        situation_id=request.situation_id,
        content_hash=request.content_hash,
        features_hash=request.features_hash,
        semantic_identity=request.semantic_identity,
        cutoff=request.cutoff,
        cap=observation.cap,
        entities=[RestrictionOnly.model_validate(entity) for entity in observation.entities],
        card=observation.card,
        reasons=list(observation.reasons),
        unavailable=unavailable,
    )
