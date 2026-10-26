"""D6 worker isolation and cutoff regressions; all values are synthetic."""

import io
import json
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import ClassVar

import pytest

from probation.config import load_settings
from probation.core.clock import Clock, parse_timestamp
from probation.core.enums import GateDecision
from probation.core.history import HistoryView
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.proposals import persist_proposal
from probation.workers import gmail_runtime
from probation.workers.d5_ipc import (
    BrainWebFactsClient,
    IpcMessageTooLarge,
    WebFactsRequest,
    decode_request,
    encode_message,
    serve_one,
)
from probation.workers.gmail_runtime import GmailRuntime, RuntimeRole

VALID_READER = {
    "intent": "request",
    "asks_me_to_do_something": True,
    "has_deadline": False,
    "deadline_text": None,
    "money_involved": False,
    "urgency": 1,
    "formality": "neutral",
    "asks_for_personal_info": False,
    "looks_automated": False,
}


def _request(**overrides: object) -> WebFactsRequest:
    fields: dict[str, object] = {
        "request_id": "synthetic-request",
        "situation_id": "synthetic-situation",
        "content_hash": "synthetic-content-hash",
        "features_hash": "synthetic-feature-hash",
        "semantic_identity": "synthetic-semantic-id",
        "cutoff": "2026-10-24T09:00:00Z",
        "sender_tier": "unknown",
        "reader": dict(VALID_READER),
    }
    fields.update(overrides)
    return WebFactsRequest(**fields)  # type: ignore[arg-type]


def _form(_):
    return dict(VALID_READER), True


class _FakePolicy:
    policy_version = "synthetic-d6"
    family = "email_action"
    as_of = "2026-01-01T00:00:00Z"
    is_fitted = True
    provenance: ClassVar[dict[str, object]] = {}

    def predict(self, fields):
        return "ARCHIVE", 0.99, {"ARCHIVE": 0.99, "LEAVE": 0.01}, []


class _FakeNovelty:
    def score(self, text):
        return False, 0.0


def test_worker_settings_ignore_dotenv_and_use_only_process_environment(
    monkeypatch,
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = load_settings({"PROBATION_WORKER_ROLE": "brain"})
    assert settings.llm_api_key == ""


def test_worker_marker_rejects_unknown_role() -> None:

    with pytest.raises(ValueError, match="invalid_worker_role"):
        load_settings({"PROBATION_WORKER_ROLE": "unknown"})


def test_owner_key_accepts_legacy_name_when_canonical_is_empty(monkeypatch) -> None:
    monkeypatch.delenv("PROBATION_WORKER_ROLE", raising=False)
    monkeypatch.setenv("PROBATION_GMAIL_OWNER_API_KEY", "")
    monkeypatch.setenv("PROBATION_OWNER_API_KEY", "synthetic-legacy-owner-key")
    assert load_settings().probation_gmail_owner_api_key == "synthetic-legacy-owner-key"


def test_runtime_child_environment_is_role_scoped() -> None:
    runtime = GmailRuntime(
        db_path=Path("data/private/engine.db"),
        private_store_path=Path("data/private/gmail.db"),
        clock=Clock.replay(),
        env={
            "PATH": "synthetic-path",
            "LLM_API_KEY": "synthetic-llm-secret",
            "TAVILY_API_KEY": "synthetic-tavily-secret",
            "PROBATION_GMAIL_OWNER_API_KEY": "synthetic-owner-secret",
            "PROBATION_GMAIL_OWNER_ID": "synthetic-owner",
            "PROBATION_GMAIL_STORE": "synthetic-private-store",
            "PROBATION_GMAIL_BIND_HOST": "127.0.0.1",
            "UNRELATED_SECRET": "synthetic-foreign-secret",
        },
    )
    brain = runtime._child_env(RuntimeRole.BRAIN, None)
    webfacts = runtime._child_env(RuntimeRole.WEBFACTS, None)
    examiner = runtime._child_env(RuntimeRole.EXAMINER, None)
    api = runtime._child_env(RuntimeRole.API, None)
    assert brain["LLM_API_KEY"] == "synthetic-llm-secret"
    assert "TAVILY_API_KEY" not in brain
    assert webfacts["LLM_API_KEY"] == "synthetic-llm-secret"
    assert webfacts["TAVILY_API_KEY"] == "synthetic-tavily-secret"
    assert "PROBATION_GMAIL_OWNER_ID" in examiner
    assert "PROBATION_GMAIL_OWNER_ID" not in brain
    assert all("UNRELATED_SECRET" not in child for child in (brain, webfacts, examiner))
    assert api["PROBATION_GMAIL_OWNER_API_KEY"] == "synthetic-owner-secret"
    assert api["PROBATION_GMAIL_STORE"] == "synthetic-private-store"
    assert "LLM_API_KEY" not in api and "TAVILY_API_KEY" not in api


def test_history_view_proposal_lookup_obeys_its_cutoff(
    memory_db, basic_situation: Situation
) -> None:
    proposal = Proposal(
        id="d6-proposal",
        situation_id=basic_situation.id,
        family=basic_situation.family,
        class_key="mail|request|known",
        action="REPLY",
        p_max=0.6,
        novel=False,
        licence_level=0,
        cap=0,
        gate=GateDecision.ASK,
        policy_version="synthetic-v1",
        features_hash="synthetic-features",
        proposed_at="2026-01-02T00:00:00Z",
    )
    persist_proposal(RoleAccess(memory_db, Role.BRAIN), proposal)
    before = HistoryView(memory_db, "2026-01-01T00:00:00Z")
    after = HistoryView(memory_db, "2026-01-03T00:00:00Z")
    assert basic_situation.id not in before.proposed_situation_ids()
    assert basic_situation.id in after.proposed_situation_ids()


def test_webfacts_ipc_carries_validated_reader_fields_only() -> None:

    reader = {
        "intent": "request",
        "asks_me_to_do_something": True,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": False,
        "urgency": 1,
        "formality": "neutral",
        "asks_for_personal_info": False,
        "looks_automated": False,
    }
    request = WebFactsRequest(
        request_id="synthetic-request",
        situation_id="synthetic-situation",
        content_hash="synthetic-content-hash",
        features_hash="synthetic-feature-hash",
        semantic_identity="synthetic-semantic-id",
        cutoff="2026-10-24T09:00:00Z",
        sender_tier="unknown",
        reader=reader,
    )
    assert decode_request(encode_message(request)) == request
    with pytest.raises(ValueError, match="ipc_request_invalid"):
        decode_request(
            json.dumps({**request.model_dump(), "raw_email_body": "synthetic body"}).encode()
        )


def test_webfacts_timeout_uses_operational_duration_not_replay_clock(monkeypatch) -> None:
    import probation.workers.d5_ipc as ipc

    values = iter((10.0, 11.0))
    monkeypatch.setattr(ipc, "elapsed_seconds", lambda: next(values))
    monkeypatch.setattr(ipc, "_POLL_SECONDS", 0.0)
    monkeypatch.setattr(ipc, "MAX_WAIT_SECONDS", 1.0)

    class SilentChannel:
        sends = 0

        def send_bytes(self, data: bytes) -> None:
            assert data
            self.sends += 1

        def poll(self, timeout: float = 0.0) -> bool:
            return False

        def recv_bytes(self, maxlength: int) -> bytes:
            raise AssertionError("timeout must not read a response")

    request = WebFactsRequest(
        request_id="timeout-request",
        situation_id="situation",
        content_hash="content",
        features_hash="features",
        semantic_identity="semantic",
        cutoff="2026-10-24T09:00:00Z",
        sender_tier="unknown",
        reader={"intent": "unknown"},
    )
    channel = SilentChannel()
    client = BrainWebFactsClient(channel)
    result = client.verify(request)
    assert result.reasons == ("webfacts_timeout",)
    assert result.cap == 0
    assert client.verify(request).reasons == ("webfacts_unavailable",)
    assert channel.sends == 1


def test_webfacts_rejects_future_cutoff(memory_db) -> None:
    from probation.core.clock import parse_timestamp

    # ``intent`` was previously "unknown", which failed reader validation first, so this case
    # never reached the cutoff check. The assertions are unchanged; the fixture now exercises
    # the cutoff rejection it names.
    request = WebFactsRequest(
        request_id="future-request",
        situation_id="synthetic-situation",
        content_hash="synthetic-content",
        features_hash="synthetic-features",
        semantic_identity="synthetic-semantic",
        cutoff="2099-01-01T00:00:00Z",
        sender_tier="unknown",
        reader={
            "intent": "other",
            "asks_me_to_do_something": False,
            "has_deadline": False,
            "deadline_text": None,
            "money_involved": False,
            "urgency": 1,
            "formality": "neutral",
            "asks_for_personal_info": False,
            "looks_automated": False,
        },
    )

    class SingleRequestChannel:
        def recv_bytes(self, maxlength: int) -> bytes:
            return encode_message(request)

        def send_bytes(self, data: bytes) -> None:
            raise AssertionError("future cutoff must be rejected before replying")

    result = serve_one(
        SingleRequestChannel(),
        conn=memory_db,
        clock=Clock.replay(parse_timestamp("2026-01-01T00:00:00Z")),
        semantic_identity=lambda: "synthetic-semantic",
        verify=lambda *_: (_ for _ in ()).throw(AssertionError("lookup must not run")),
    )
    assert result is False


def test_replay_lock_io_failure_keeps_examiner_loop_running(memory_db, monkeypatch) -> None:
    from probation.workers import gmail_role_loops
    from probation.workers.replay_lock import ReplayLock

    class OneTickStop:
        done = False

        def is_set(self) -> bool:
            return self.done

        def wait(self, timeout: float | None = None) -> bool:
            self.done = True
            return True

    def broken_acquire(_self) -> bool:
        raise OSError("synthetic lock path failure")

    monkeypatch.setattr(ReplayLock, "acquire", broken_acquire)
    ticks = gmail_role_loops.run_examiner(
        memory_db,
        clock=Clock.replay(),
        stop=OneTickStop(),
        replay_controller=object(),
        lock_path=Path("synthetic/replay.lock"),
    )
    assert ticks == 1


# -- 1. an unavailable Webfacts channel restricts, never clears ------------------------------
def test_absent_webfacts_channel_fails_closed_to_a_zero_cap(memory_db, basic_situation) -> None:
    from probation.engine.prediction import PredictionSnapshot
    from probation.workers.d5_verification import predict_verified_email
    from probation.workers.gmail_brain import webfacts_verifier

    verify = webfacts_verifier(None, "synthetic-semantic-id")
    result = predict_verified_email(
        memory_db,
        basic_situation,
        PredictionSnapshot(_FakePolicy(), _FakeNovelty(), "d6", 0),
        clock=Clock.replay(parse_timestamp(basic_situation.occurred_at)),
        verify=verify,
        reader_callable=_form,
        licence_level=3,
    )
    assert result.web.cap == 0
    assert result.web.reasons == ("webfacts_role_unavailable",)
    assert result.prediction.gate in {GateDecision.SHADOW, GateDecision.ASK}


def test_available_channel_is_the_only_one_that_builds_a_request(memory_db) -> None:
    from probation.workers.gmail_brain import webfacts_verifier

    class Silent:
        def send_bytes(self, data: bytes) -> None:
            raise OSError("synthetic closed channel")

        def recv_bytes(self, maxlength: int) -> bytes:
            raise AssertionError("a closed channel must not be read")

        def poll(self, timeout: float = 0.0) -> bool:
            return False

    observation = webfacts_verifier(BrainWebFactsClient(Silent()), "id")(
        Situation(
            id="s",
            pack="mail",
            family="email_action",
            raw_item_id="r",
            occurred_at="2026-01-01T00:00:00Z",
            content_hash="h",
            created_at="2026-01-01T00:00:00Z",
        ),
        _features(),
        HistoryView(memory_db, "2026-01-02T00:00:00Z"),
    )
    assert observation.cap == 0


# -- 2. one outstanding verification per Brain --------------------------------------------------
def test_second_concurrent_verification_is_refused_not_interleaved(monkeypatch) -> None:
    import probation.workers.d5_ipc as ipc
    from probation.workers.d5_ipc import WebFactsReply

    monkeypatch.setattr(ipc, "_POLL_SECONDS", 0.01)
    monkeypatch.setattr(ipc, "MAX_WAIT_SECONDS", 30.0)

    class BlockingChannel:
        def __init__(self) -> None:
            self.sent: list[bytes] = []
            self.started = threading.Event()
            self.release = threading.Event()

        def send_bytes(self, data: bytes) -> None:
            self.sent.append(data)
            self.started.set()

        def poll(self, timeout: float = 0.0) -> bool:
            self.release.wait(10)
            return True

        def recv_bytes(self, maxlength: int) -> bytes:
            request = decode_request(self.sent[-1])
            return encode_message(
                WebFactsReply(
                    request_id=request.request_id,
                    situation_id=request.situation_id,
                    content_hash=request.content_hash,
                    features_hash=request.features_hash,
                    semantic_identity=request.semantic_identity,
                    cutoff=request.cutoff,
                    cap=0,
                    reasons=["webfacts_unavailable"],
                    unavailable=True,
                )
            )

    channel = BlockingChannel()
    client = BrainWebFactsClient(channel)
    answers: list[object] = []
    first = threading.Thread(
        target=lambda: answers.append(client.verify(_request(request_id="first")))
    )
    first.start()
    assert channel.started.wait(5)
    refused = client.verify(_request(request_id="second"))
    assert refused.cap == 0
    assert refused.reasons == ("webfacts_busy",)
    channel.release.set()
    first.join(10)
    assert len(channel.sent) == 1  # the refused caller wrote nothing to the frame stream
    assert decode_request(channel.sent[0]).request_id == "first"
    assert answers and answers[0].cap == 0  # type: ignore[union-attr]


# -- 3. malformed input is answered truthfully, and the role keeps serving -----------------------
class _ScriptedChannel:
    def __init__(self, payloads: list[bytes]) -> None:
        self.payloads = list(payloads)
        self.replies: list[object] = []
        self.receive_error: Exception | None = None

    def recv_bytes(self, maxlength: int) -> bytes:
        if self.receive_error is not None:
            raise self.receive_error
        if not self.payloads:
            raise EOFError("synthetic drained channel")
        return self.payloads.pop(0)

    def send_bytes(self, data: bytes) -> None:
        from probation.workers.d5_ipc import decode_reply

        self.replies.append(decode_reply(data))

    def poll(self, timeout: float = 0.0) -> bool:
        return bool(self.payloads)


def _serve(channel: _ScriptedChannel, memory_db, calls: list[int]):
    from probation.workers.d5_ipc import serve_one as serve

    def forbidden(*_args):
        calls.append(1)
        raise AssertionError("a refused request must never reach the paid verifier")

    return serve(
        channel,
        conn=memory_db,
        clock=Clock.replay(parse_timestamp("2026-10-24T10:00:00Z")),
        semantic_identity=lambda: "synthetic-semantic-id",
        verify=forbidden,
    )


def test_malformed_request_gets_an_unavailable_reply_and_serving_continues(memory_db) -> None:
    calls: list[int] = []
    channel = _ScriptedChannel([b"{not json"])
    assert _serve(channel, memory_db, calls) is True
    assert channel.replies[0].unavailable is True  # type: ignore[union-attr]
    assert channel.replies[0].cap == 0  # type: ignore[union-attr]
    assert channel.replies[0].reasons == ["ipc_request_invalid"]  # type: ignore[union-attr]
    assert calls == []


def test_unknown_field_request_is_refused_without_a_paid_lookup(memory_db) -> None:
    calls: list[int] = []
    payload = json.dumps({**_request().model_dump(), "raw_email_body": "synthetic body"}).encode()
    channel = _ScriptedChannel([payload])
    assert _serve(channel, memory_db, calls) is True
    assert calls == []
    assert channel.replies[0].unavailable is True  # type: ignore[union-attr]
    assert channel.replies[0].reasons == ["ipc_request_invalid"]  # type: ignore[union-attr]


def test_oversized_request_is_refused_at_both_layers(memory_db) -> None:
    calls: list[int] = []
    oversized = _request().model_dump_json().encode() + b"x" * 70_000
    assert _serve(_ScriptedChannel([oversized]), memory_db, calls) is True
    assert calls == []

    channel = _ScriptedChannel([])
    channel.receive_error = IpcMessageTooLarge("ipc_message_too_large")
    assert _serve(channel, memory_db, calls) is True
    assert channel.replies[0].unavailable is True  # type: ignore[union-attr]
    assert calls == []


def test_genuine_framing_failure_still_ends_the_loop(memory_db) -> None:
    channel = _ScriptedChannel([])
    channel.receive_error = OSError("synthetic broken pipe")
    assert _serve(channel, memory_db, []) is False
    assert channel.replies == []


def test_mismatched_reply_identity_is_not_retried() -> None:
    from probation.workers.d5_ipc import WebFactsReply

    class MismatchedChannel:
        def __init__(self) -> None:
            self.sends = 0

        def send_bytes(self, data: bytes) -> None:
            self.sends += 1

        def poll(self, timeout: float = 0.0) -> bool:
            return True

        def recv_bytes(self, maxlength: int) -> bytes:
            return encode_message(
                WebFactsReply(
                    request_id="someone-elses-request",
                    situation_id="other",
                    content_hash="other",
                    features_hash="other",
                    semantic_identity="other",
                    cutoff="2026-10-24T09:00:00Z",
                    cap=3,
                )
            )

    channel = MismatchedChannel()
    client = BrainWebFactsClient(channel)
    result = client.verify(_request())
    assert result.cap == 0 and result.reasons == ("webfacts_response_mismatch",)
    assert client.verify(_request()).cap == 0
    assert channel.sends == 1  # never re-sent: a paid lookup is not retried by the Brain


def test_webfacts_loop_survives_a_malformed_request(memory_db) -> None:
    from probation.workers import gmail_role_loops

    class OneServeStop:
        def __init__(self) -> None:
            self.served = 0

        def is_set(self) -> bool:
            return self.served > 0

        def wait(self, timeout: float | None = None) -> bool:
            return True

    channel = _ScriptedChannel([b"{not json"])

    def counting_stop() -> OneServeStop:
        stop = OneServeStop()

        original = channel.send_bytes

        def send(data: bytes) -> None:
            original(data)
            stop.served += 1

        channel.send_bytes = send  # type: ignore[method-assign]
        return stop

    stop = counting_stop()
    ticks = gmail_role_loops.run_webfacts(
        memory_db,
        channel=channel,
        clock=Clock.replay(parse_timestamp("2026-10-24T10:00:00Z")),
        stop=stop,  # type: ignore[arg-type]
        semantic_identity=lambda: "synthetic-semantic-id",
        verify=lambda *_: (_ for _ in ()).throw(AssertionError("paid lookup")),
    )
    assert ticks == 1  # the refusal was served, counted, and the loop kept going
    assert channel.replies[0].unavailable is True  # type: ignore[union-attr]


def _features():
    from probation.core.types import Features

    return Features(
        situation_id="s",
        deterministic={"sender_tier": "unknown"},
        reader=dict(VALID_READER),
        reader_ok=True,
        featurizer_version="synthetic",
        features_hash="synthetic-hash",
    )


# -- 4. readiness comes from real role work, never from a hard-coded stage -------------------------
class _RoleProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic-role", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


class _StopAfter:
    """A stop seam that lets a role loop run a fixed number of ticks without sleeping."""

    def __init__(self, ticks: int = 1) -> None:
        self._planned = ticks
        self._done = 0

    def is_set(self) -> bool:
        return self._done >= self._planned

    def wait(self, timeout: float | None = None) -> bool:
        del timeout
        self._done += 1
        return self._done >= self._planned


def _supervised(tmp_path, clock, work=None):
    runtime = GmailRuntime(
        db_path=Path(tmp_path) / "engine.db",
        private_store_path=Path(tmp_path) / "private" / "gmail_metadata.db",
        env={"PATH": "C:/fake/bin", "SYSTEMROOT": "C:/fake/windows"},
        clock=clock,
        launcher=lambda _command, _env: _RoleProcess(),
        work=work,
    )
    stop = threading.Event()
    stop.set()
    return runtime.run(stop, join_timeout=0.01)


def test_engine_role_without_a_tick_is_never_reported_ready(tmp_path) -> None:
    from probation.workers.gmail_role_loops import WorkLedger

    clock = Clock.replay(parse_timestamp("2026-01-01T00:00:00Z"))
    report = _supervised(tmp_path, clock, WorkLedger())
    for role in (
        RuntimeRole.BRAIN,
        RuntimeRole.RESOLVER,
        RuntimeRole.EXAMINER,
        RuntimeRole.WEBFACTS,
    ):
        status = report.status(role)
        assert status.capability_ready is False
        assert status.detail == "work_status_absent"


def test_a_fresh_successful_tick_makes_the_role_ready(tmp_path) -> None:
    from probation.workers.gmail_role_loops import WorkLedger

    clock = Clock.replay(parse_timestamp("2026-01-01T00:00:00Z"))
    ledger = WorkLedger()
    ledger.success("brain", clock.now_iso(), ("gmail_verification", "authority_followups"))
    status = _supervised(tmp_path, clock, ledger).status(RuntimeRole.BRAIN)
    assert status.capability_ready is True
    assert status.state == "stopped"


def test_a_stale_tick_stops_proving_readiness(tmp_path) -> None:
    from probation.workers.gmail_role_loops import WORK_STALENESS_SECONDS, WorkLedger

    clock = Clock.replay(parse_timestamp("2026-01-01T00:00:00Z"))
    ledger = WorkLedger()
    ledger.success("brain", clock.now_iso(), ("gmail_verification",))
    clock.advance_seconds(WORK_STALENESS_SECONDS + 1)
    status = _supervised(tmp_path, clock, ledger).status(RuntimeRole.BRAIN)
    assert status.capability_ready is False
    assert status.detail == "work_status_stale"


def test_a_failed_tick_is_reported_as_degraded(tmp_path) -> None:
    from probation.workers.gmail_role_loops import WorkLedger

    clock = Clock.replay(parse_timestamp("2026-01-01T00:00:00Z"))
    ledger = WorkLedger()
    ledger.failure("examiner", clock.now_iso(), "OperationalError")
    status = _supervised(tmp_path, clock, ledger).status(RuntimeRole.EXAMINER)
    assert status.capability_ready is False
    assert status.state == "degraded"
    assert status.detail == "work_tick_failed_OperationalError"


def test_role_loops_record_their_own_completed_stages(memory_db) -> None:
    from probation.workers import gmail_role_loops
    from probation.workers.gmail_role_loops import WorkLedger

    ledger = WorkLedger()
    assert (
        gmail_role_loops.run_resolver(
            memory_db,
            clock=Clock.replay(),
            stop=_StopAfter(1),
            work=ledger,  # type: ignore[arg-type]
        )
        == 1
    )
    evidence = ledger.evidence("resolver")
    assert evidence is not None
    assert evidence.stages == ("owner_responses",)
    assert evidence.succeeded


# -- 6. exact per-role credential allowlist ---------------------------------------------------------
def _grant(role: str, ref: str):
    from probation.connectors.credentials_state import ProvisionedGrant

    return ProvisionedGrant(
        role=role, connection_id="conn-1", account_id="a@b.test", credential_ref=ref
    )


READ_GRANT = _grant("read", "cred-read-1")
WRITE_GRANT = _grant("write", "cred-write-1")


def _grant_env() -> dict[str, str]:
    return {
        "PATH": "C:/fake/bin",
        "SYSTEMROOT": "C:/fake/windows",
        "LLM_API_KEY": "synthetic-model-secret",
        "LLM_BASE_URL": "https://synthetic.invalid",
        "TAVILY_API_KEY": "synthetic-web-secret",
        READ_GRANT.env_name: "synthetic-read-bundle",
        WRITE_GRANT.env_name: "synthetic-write-bundle",
        "PROBATION_GMAIL_OWNER_API_KEY": "synthetic-owner-key",
        "PROBATION_GMAIL_OWNER_ID": "synthetic-owner",
        "PROBATION_GMAIL_STORE": "synthetic-private-store",
        "PARENT_ONLY_SECRET": "never-inherited",
    }


def test_live_child_flag_is_limited_to_live_capable_roles(tmp_path) -> None:
    runtime = GmailRuntime(
        db_path=Path(tmp_path) / "engine.db",
        private_store_path=Path(tmp_path) / "private" / "gmail_metadata.db",
        env={"PROBATION_RUNTIME_LIVE": "1"},
        clock=Clock.replay(),
    )
    live_roles = {
        RuntimeRole.OBSERVATION,
        RuntimeRole.BRAIN,
        RuntimeRole.EXAMINER,
        RuntimeRole.WEBFACTS,
        RuntimeRole.EXECUTOR,
    }
    for role in RuntimeRole:
        assert ("--live" in runtime.command_for(role)) is (role in live_roles), role


def test_api_child_holds_owner_metadata_and_no_provider_or_gmail_grant(tmp_path) -> None:
    runtime = GmailRuntime(
        db_path=Path(tmp_path) / "engine.db",
        private_store_path=Path(tmp_path) / "private" / "gmail_metadata.db",
        env=_grant_env(),
        clock=Clock.replay(),
    )
    api = runtime._child_env(RuntimeRole.API, None)
    assert api["PROBATION_GMAIL_OWNER_API_KEY"] == "synthetic-owner-key"
    assert api["PROBATION_GMAIL_OWNER_ID"] == "synthetic-owner"
    assert api["PROBATION_GMAIL_STORE"] == "synthetic-private-store"
    assert not [key for key in api if key.startswith("LLM_")]
    assert not [key for key in api if key.startswith("TAVILY_")]
    assert not [key for key in api if key.startswith("PROBATION_GMAIL_GRANT_")]
    assert "PARENT_ONLY_SECRET" not in api
    for role in (
        RuntimeRole.BRAIN,
        RuntimeRole.RESOLVER,
        RuntimeRole.EXAMINER,
        RuntimeRole.WEBFACTS,
    ):
        child = runtime._child_env(role, None)
        assert not [key for key in child if key.startswith("PROBATION_GMAIL_GRANT_")], role


def test_each_role_gets_exactly_its_credential_category(tmp_path) -> None:
    runtime = GmailRuntime(
        db_path=Path(tmp_path) / "engine.db",
        private_store_path=Path(tmp_path) / "private" / "gmail_metadata.db",
        env=_grant_env(),
        clock=Clock.replay(),
        grants={
            RuntimeRole.OBSERVATION: READ_GRANT,
            RuntimeRole.EXECUTOR: WRITE_GRANT,
        },
    )
    observation = runtime._child_env(RuntimeRole.OBSERVATION, READ_GRANT)
    executor = runtime._child_env(RuntimeRole.EXECUTOR, WRITE_GRANT)
    assert observation[READ_GRANT.env_name] == "synthetic-read-bundle"
    assert WRITE_GRANT.env_name not in observation
    assert "LLM_API_KEY" not in observation and "TAVILY_API_KEY" not in observation
    assert executor[WRITE_GRANT.env_name] == "synthetic-write-bundle"
    assert READ_GRANT.env_name not in executor
    assert "LLM_API_KEY" not in executor and "TAVILY_API_KEY" not in executor
    brain = runtime._child_env(RuntimeRole.BRAIN, None)
    assert brain["LLM_API_KEY"] == "synthetic-model-secret"
    assert "TAVILY_API_KEY" not in brain
    assert READ_GRANT.env_name not in brain and WRITE_GRANT.env_name not in brain
    webfacts = runtime._child_env(RuntimeRole.WEBFACTS, None)
    assert webfacts["LLM_API_KEY"] == "synthetic-model-secret"
    assert webfacts["TAVILY_API_KEY"] == "synthetic-web-secret"
    examiner = runtime._child_env(RuntimeRole.EXAMINER, None)
    assert examiner["LLM_API_KEY"] == "synthetic-model-secret"
    assert "TAVILY_API_KEY" not in examiner
    resolver = runtime._child_env(RuntimeRole.RESOLVER, None)
    assert not [key for key in resolver if key.startswith(("LLM_", "TAVILY_", "PROBATION_GMAIL_"))]


def test_supervision_never_mutates_the_parent_environment(tmp_path) -> None:
    import os

    before = dict(os.environ)
    runtime = GmailRuntime(
        db_path=Path(tmp_path) / "engine.db",
        private_store_path=Path(tmp_path) / "private" / "gmail_metadata.db",
        env=_grant_env(),
        clock=Clock.replay(),
        launcher=lambda _command, _env: _RoleProcess(),
    )
    stop = threading.Event()
    stop.set()
    runtime.run(stop, join_timeout=0.01)
    assert dict(os.environ) == before
    child = runtime._child_env(RuntimeRole.BRAIN, None)
    assert child is not runtime.env and runtime.env["LLM_API_KEY"] == "synthetic-model-secret"


# -- 7. no silent drops and no repeated fitting ------------------------------------------------------
def test_fitted_snapshot_is_built_once_across_ticks(memory_db, monkeypatch) -> None:
    from probation.engine.prediction import PredictionSnapshot
    from probation.workers import gmail_brain
    from probation.workers.gmail_brain import run_brain
    from probation.workers.gmail_role_loops import WorkLedger

    builds: list[str] = []

    def fitting(_conn, _family, cutoff):
        builds.append(cutoff)
        return PredictionSnapshot(_FakePolicy(), _FakeNovelty(), "d6", 0)

    monkeypatch.setattr(gmail_brain, "build_runtime_snapshot", fitting)
    ledger = WorkLedger()
    ticks = run_brain(
        memory_db,
        clock=Clock.replay(),
        stop=_StopAfter(3),  # type: ignore[arg-type]
        work=ledger,
    )
    assert ticks == 3
    assert builds == ["2026-01-01T00:00:00Z"]  # refit only after a restart or a cohort change
    evidence = ledger.evidence("brain")
    assert evidence is not None and evidence.succeeded


def test_a_failed_batch_is_not_counted_as_a_successful_tick(memory_db, monkeypatch) -> None:
    from probation.workers import gmail_brain
    from probation.workers.gmail_brain import run_brain
    from probation.workers.gmail_role_loops import WorkLedger

    def broken(_self, _limit: int):
        raise sqlite3.OperationalError("synthetic cohort read failure")

    monkeypatch.setattr(gmail_brain.HistoryView, "pending_gmail_situations", broken)
    ledger = WorkLedger()
    assert (
        run_brain(
            memory_db,
            clock=Clock.replay(),
            stop=_StopAfter(1),
            work=ledger,  # type: ignore[arg-type]
        )
        == 0
    )
    evidence = ledger.evidence("brain")
    assert evidence is not None and evidence.failure == "OperationalError"
    assert not evidence.succeeded


def test_a_per_situation_failure_is_reported_not_swallowed(memory_db, monkeypatch) -> None:
    from probation.engine.prediction import PredictionSnapshot
    from probation.workers import gmail_brain
    from probation.workers.gmail_brain import process_pending_mail

    def fitted(_conn, _family, _cutoff):
        return PredictionSnapshot(_FakePolicy(), _FakeNovelty(), "d6", 0)

    def refusing_persist(*_args, **_kwargs):
        raise sqlite3.IntegrityError("synthetic durable write refusal")

    monkeypatch.setattr(gmail_brain, "build_runtime_snapshot", fitted)
    monkeypatch.setattr(gmail_brain, "persist_verified_email", refusing_persist)
    at = "2026-01-01T09:00:00Z"
    with memory_db:
        memory_db.execute(
            "INSERT INTO sources VALUES('d6-src','mail','gmail_live','cohort',?)", (at,)
        )
        memory_db.execute(
            """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,occurred_at,known_at,
               payload_json,content_hash) VALUES('d6-raw','d6-src','mail','mail_in','r',?,?,?,?)""",
            (at, at, json.dumps({"subject": "synthetic"}), "d6-hash"),
        )
        memory_db.execute(
            """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,content_hash,
               redacted_text,created_at) VALUES('d6-sit','d6-raw','mail','email_action',?,?,?,?)""",
            (at, "d6-hash", "synthetic redacted text", at),
        )
    tick = process_pending_mail(
        memory_db, clock=Clock.replay(parse_timestamp("2026-01-02T00:00:00Z"))
    )
    assert tick.processed == 0
    assert tick.ok is False
    assert tick.failures and tick.failures[0].startswith("verification:")
    assert tick.stages == ("gmail_verification", "authority_followups")


# -- 8. follow-ups run through the existing Brain-owned processor -----------------------------------
def _fitted_policy(as_of: str):
    from probation.engine.policy import Policy

    policy = Policy("email_action", cold_start_min=2)
    policy.fit(
        [{"has_deadline": False}] * 60 + [{"has_deadline": True}] * 60,
        ["ARCHIVE"] * 60 + ["LEAVE"] * 60,
        ["2025-12-31T00:00:00Z"] * 120,
        as_of=as_of,
    )
    assert policy.is_fitted
    return policy


def _seed_cancelled_authority(memory_db) -> str:
    from probation.db.ledger import append_ledger

    at = "2026-01-01T09:00:00Z"
    with memory_db:
        memory_db.execute("INSERT INTO sources VALUES('fu-src','mail','synthetic','fu',?)", (at,))
        memory_db.execute(
            """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,occurred_at,known_at,
               payload_json,content_hash) VALUES('fu-raw','fu-src','mail','mail_in','fu',?,?,?,?)""",
            (at, at, json.dumps({"body": "synthetic"}), "fu-hash"),
        )
        memory_db.execute(
            """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,content_hash,created_at)
               VALUES('fu-sit','fu-raw','mail','email_action',?,?,?)""",
            (at, "fu-hash", at),
        )
    persist_proposal(
        RoleAccess(memory_db, Role.BRAIN),
        Proposal(
            id="fu-proposal",
            situation_id="fu-sit",
            family="email_action",
            class_key="mail|request|known",
            action="ARCHIVE",
            p_max=0.6,
            novel=False,
            licence_level=0,
            cap=0,
            gate=GateDecision.SUGGEST,
            policy_version="synthetic-v1",
            features_hash="fu-features",
            proposed_at=at,
        ),
    )
    memory_db.execute(
        """INSERT INTO actions(id,proposal_id,pack,type,params_json,level_required,recallable,
           status,authority_kind,created_at,updated_at)
           VALUES('fu-action','fu-proposal','mail','ARCHIVE','{}',2,1,'CANCELLED','autonomous',?,?)""",
        (at, at),
    )
    append_ledger(
        memory_db,
        "action",
        "fu-action",
        {
            "action_id": "fu-action",
            "status": "CANCELLED",
            "reason": "licence_lost",
            "licence_lost_followup_requested": True,
        },
        at,
    )
    memory_db.commit()
    return at


def test_followups_run_through_the_existing_brain_processor_once(memory_db, monkeypatch) -> None:
    from probation.engine.prediction import PredictionSnapshot
    from probation.workers import gmail_brain
    from probation.workers.gmail_brain import process_pending_mail

    at = _seed_cancelled_authority(memory_db)
    snapshot = PredictionSnapshot(_fitted_policy(at), _FakeNovelty(), "d6", 0)
    monkeypatch.setattr(gmail_brain, "build_runtime_snapshot", lambda *_a, **_k: snapshot)
    clock = Clock.replay(parse_timestamp("2026-01-02T00:00:00Z"))

    first = process_pending_mail(memory_db, clock=clock)
    assert first.followups == 1
    assert first.ok
    rows = memory_db.execute(
        "SELECT gate FROM proposals WHERE followup_of_action_id='fu-action'"
    ).fetchall()
    assert len(rows) == 1
    assert str(rows[0]["gate"]) in {"SUGGEST", "ASK", "SHADOW"}

    second = process_pending_mail(memory_db, clock=clock)
    assert second.followups == 0  # an existing outcome is never duplicated
    followups = memory_db.execute(
        "SELECT COUNT(*) FROM proposals WHERE id LIKE 'followup-%'"
    ).fetchone()[0]
    assert followups == 1


# -- 9. the examiner's operational clock is injectable ------------------------------------------------
class _RecordingController:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def process_pending(
        self, *, operational_at: str, initial_simulated_at: str, limit: int
    ) -> None:
        del initial_simulated_at, limit
        self.seen.append(operational_at)

    def advance(self, *, elapsed_seconds: float, operational_at: str) -> None:
        del elapsed_seconds
        self.seen.append(operational_at)

    def pause_and_finish(self, operational_at: str) -> None:
        self.seen.append(operational_at)


def test_examiner_operational_clock_is_injected_not_invented(memory_db) -> None:
    from probation.workers import gmail_role_loops

    controller = _RecordingController()
    assert (
        gmail_role_loops.run_examiner(
            memory_db,
            clock=Clock.replay(parse_timestamp("2026-01-01T00:00:00Z")),
            stop=_StopAfter(1),  # type: ignore[arg-type]
            replay_controller=controller,  # type: ignore[arg-type]
            operational_clock=Clock.replay(parse_timestamp("2026-05-05T00:00:00Z")),
        )
        == 1
    )
    assert controller.seen == ["2026-05-05T00:00:00Z"] * 3  # no sleeping, no invented wall clock


def test_examiner_records_its_completed_stages(memory_db) -> None:
    from probation.workers import gmail_role_loops
    from probation.workers.gmail_role_loops import WorkLedger

    ledger = WorkLedger()
    gmail_role_loops.run_examiner(
        memory_db,
        clock=Clock.replay(),
        stop=_StopAfter(1),
        work=ledger,  # type: ignore[arg-type]
    )
    evidence = ledger.evidence("examiner")
    assert evidence is not None and evidence.succeeded
    assert "outcome_review" in evidence.stages


def test_work_status_lines_are_typed_and_untrusted_lines_are_ignored() -> None:
    """Only a well-formed status line is readable; logs and malformed JSON never count."""
    from probation.workers.gmail_role_loops import (
        WORK_STATUS_PREFIX,
        WorkEvidence,
        decode_work_status,
        encode_work_status,
        write_work_status,
    )

    evidence = WorkEvidence(at="2026-01-01T00:00:00Z", stages=("gmail_verification",))
    line = f"{WORK_STATUS_PREFIX}{encode_work_status('brain', evidence)}"
    assert decode_work_status(line) == ("brain", evidence)
    buffer = io.BytesIO()
    write_work_status(buffer, "brain", evidence)
    assert decode_work_status(buffer.getvalue().decode().strip()) == ("brain", evidence)
    for noise in (
        "runtime_refused: loopback_host_required",
        "",
        "runtime_work not json",
        'runtime_work {"role":"brain","at":5,"stages":[]}',
        'runtime_work {"role":"brain","at":"x","stages":[1]}',
        'runtime_work {"role":"brain","at":"x","stages":[],"failure":7}',
        "runtime_work [1,2]",
    ):
        assert decode_work_status(noise) is None


def test_supervisor_readiness_comes_from_a_child_status_line(tmp_path: Path) -> None:
    """A real tick reported by a child makes the role ready; absence and staleness do not."""
    from probation.workers.gmail_role_loops import (
        WORK_STATUS_PREFIX,
        WorkEvidence,
        WorkLedger,
        encode_work_status,
    )

    ledger = WorkLedger()
    assert ledger.state("brain", "2026-01-01T00:00:30Z").code == "work_status_absent"

    class _Child:
        stderr = io.BytesIO(
            (
                f"runtime_degraded: role=brain steps=webfacts_ipc\n"
                f"{WORK_STATUS_PREFIX}"
                f"{encode_work_status('brain', WorkEvidence(at='2026-01-01T00:00:01Z', stages=('verify',)))}\n"
                f"{WORK_STATUS_PREFIX}"
                f"{encode_work_status('brain', WorkEvidence(at='2026-01-01T00:00:05Z', stages=('verify', 'followups')))}\n"
            ).encode()
        )

    thread = gmail_runtime._pump_role_status(_Child(), "brain", ledger)  # type: ignore[arg-type]
    thread.join(timeout=2)
    state = ledger.state("brain", "2026-01-01T00:00:06Z")
    assert state.ready is True
    assert ledger.state("brain", "2026-01-01T03:00:00Z").code == "work_status_stale"

    failed = WorkLedger()
    gmail_runtime._pump_role_status(
        type(
            "Handle",
            (),
            {
                "stderr": io.BytesIO(
                    f"{WORK_STATUS_PREFIX}"
                    f"{encode_work_status('brain', WorkEvidence(at='2026-01-01T00:00:01Z', stages=(), failure='BudgetExceeded'))}\n".encode()
                )
            },
        )(),
        "brain",
        failed,
    ).join(timeout=2)
    assert failed.state("brain", "2026-01-01T00:00:02Z").code == "work_tick_failed_BudgetExceeded"
