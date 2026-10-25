"""Local Gmail observation worker: leases, control gating, bounded retries and restart safety.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 4-7 and 9 (D4-07 ids), and
docs/OCT29_DEMO_BUILD_PLAN.md 10.1. The worker is exercised against the real private store with
real authorities and the faithful fake provider; control gating reuses the existing examiner
restriction machinery (``workers/restrictions.py``) end-to-end. Everything is offline and synthetic.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

from probation.connectors.credentials import RoleCredentialProvider, TokenBundle
from probation.connectors.credentials_state import (
    CredentialSource,
    ProvisionedGrant,
    SecretMaterial,
)
from probation.connectors.readiness import READINESS_VERSION
from probation.connectors.types import (
    ConnectorError,
    HttpResult,
    ProviderUnavailable,
    TransportFailure,
)
from probation.core.clock import Clock, ClockMode, timestamp_key
from probation.core.lifecycle import CommandIntent, CommandScope
from probation.db.access import Role, RoleAccess
from probation.db.gmail_store import ConnectorAccess, StoreAccessError, migrate_store, open_store
from probation.db.lifecycle_commands import CommandStore
from probation.workers.gmail_observation import (
    AuthorizationFailed,
    GmailObservationWorker,
    ObservationTickResult,
    RetryingReadTransport,
)
from probation.workers.restrictions import (
    ExecutionRestrictions,
    process_restriction_commands,
    restrictions_for,
)

CONNECTION = "conn-1"
ACCOUNT = "acct-1"
OWNER = "owner-1"
LABEL = "COHORT"
STRANGER = "m-stranger"
T0 = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)

_CONNECTION = """INSERT INTO gmail_connections
 (connection_id,account_id,owner_id,state,selection_revision,label_ids,credential_ref,
  granted_scopes,created_at,updated_at) VALUES(?,?,?,?,?,'["COHORT"]','cred-ref-1',
  '["gmail.readonly"]',?,?)"""


def _clock() -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=T0)


def _message(native_id: str, labels: set[str]) -> _Message:
    return _Message(
        native_id,
        thread_id=f"t-{native_id}",
        from_addr="alice@sender.test",
        to_addr="bob@owner.test",
        subject=f"subj {native_id}",
        date="Tue, 14 Nov 2023 22:13:20 +0000",
        message_id=f"<{native_id}@sender.test>",
        internal_date_ms=1700000000000,
        labels=labels,
        text="synthetic body",
    )


def _fake() -> FakeGmailTransport:
    fake = FakeGmailTransport(expected_token="read-token", page_size=2)
    fake.add_message(_message("m1", {LABEL, "INBOX"}))
    fake.add_message(_message("m2", {LABEL, "INBOX"}))
    fake.add_message(_message(STRANGER, {"INBOX"}))
    return fake


class _Source(CredentialSource):
    def fetch(self, role: str, credential_ref: str) -> SecretMaterial:
        raise ConnectorError("refresh_material_not_provisioned")


def _provider(
    clock: Clock, *, token: str = "read-token", role: str = "read"
) -> RoleCredentialProvider:
    grant = ProvisionedGrant(
        role=role,  # type: ignore[arg-type]
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        credential_ref="cred-ref-1",
    )
    provider = RoleCredentialProvider(grant=grant, source=_Source(), clock=clock)
    provider.install_bundle(
        TokenBundle(
            account_id=ACCOUNT,
            granted_scopes=("https://www.googleapis.com/auth/gmail.readonly",),
            expires_in_seconds=3000,
            access=SecretMaterial(value=token, kind="access"),
        )
    )
    return provider


def _never_restricted(as_of: str) -> ExecutionRestrictions:
    del as_of
    return ExecutionRestrictions()


class _Handles:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conns: list[ConnectorAccess] = []

    def access(self, authority: str) -> ConnectorAccess:
        conn = open_store(self.path)
        access = ConnectorAccess(conn, authority)  # type: ignore[arg-type]
        self._conns.append(access)
        return access

    def close(self) -> None:
        for access in self._conns:
            access.conn.close()


@pytest.fixture
def handles(tmp_path: Path) -> Iterator[_Handles]:
    path = tmp_path / "gmail_metadata.db"
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    bag = _Handles(path)
    yield bag
    bag.close()


def register(handles: _Handles, state: str = "AUTHORIZED") -> None:
    admin = handles.access("administration")
    now = "2026-10-24T09:00:00Z"
    admin.write("gmail_connections", _CONNECTION, (CONNECTION, ACCOUNT, OWNER, state, 1, now, now))


def build(
    handles: _Handles,
    clock: Clock,
    fake: FakeGmailTransport,
    *,
    owner: str = "reader-a",
    restrictions=_never_restricted,
    transport: object = None,
    token: str = "read-token",
) -> GmailObservationWorker:
    return GmailObservationWorker(
        connection_id=CONNECTION,
        owner=owner,
        ingest=handles.access("ingestor"),
        capabilities=handles.access("read_worker"),
        credentials=_provider(clock, token=token),
        transport=transport or fake,  # type: ignore[arg-type]
        clock=clock,
        restrictions=restrictions,
        page_size=2,
    )


def _cursor(handles: _Handles) -> tuple[int, int, str, str]:
    row = handles.access("api").one(
        "SELECT committed_history_id,fence,claim_owner,updated_at FROM gmail_sync_cursors"
        " WHERE connection_id=? AND resource_key='cohort'",
        (CONNECTION,),
    )
    return (
        int(row["committed_history_id"]),
        int(row["fence"]),
        str(row["claim_owner"]),
        str(row["updated_at"]),
    )  # type: ignore[index]


def _obs_count(handles: _Handles) -> int:
    return int(handles.access("api").one("SELECT count(*) AS n FROM gmail_observations")["n"])  # type: ignore[index]


def _readiness_rows(handles: _Handles) -> dict[str, tuple[int, str | None]]:
    rows = handles.access("api").query(
        "SELECT name,supported,reason FROM gmail_capabilities WHERE owner_role='read'"
    )
    return {
        str(r["name"]): (int(r["supported"]), None if r["reason"] is None else str(r["reason"]))
        for r in rows
    }


# -- happy loop and restart ----------------------------------------------------------------------
def test_tick_bootstraps_persists_progress_and_readiness(handles: _Handles) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    result = build(handles, clock, fake).tick(Event())
    assert result.action == "observed" and result.observations_written >= 2
    assert result.readiness is not None and result.readiness.version == READINESS_VERSION
    assert result.readiness.freshness.fresh is True
    assert _readiness_rows(handles)["read"] == (1, None)
    assert _obs_count(handles) == 2  # the stranger message was never stored, in any form
    for table in ("gmail_observations", "gmail_history_events"):
        assert not any(
            STRANGER in str(dict(r)) for r in handles.access("api").query(f"SELECT * FROM {table}")
        )


def test_second_tick_uses_the_incremental_history_path(handles: _Handles) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    worker = build(handles, clock, fake)
    assert worker.tick(Event()).action == "observed"
    fake.add_message(_message("m3", {"INBOX"}))
    fake.modify_labels("m3", add=(LABEL,))  # the owner label defines the cohort (contract 4)
    history_before = fake.history_calls
    result = worker.tick(Event())
    assert result.action == "observed" and fake.history_calls > history_before
    events = handles.access("api").query(
        "SELECT * FROM gmail_history_events WHERE native_message_id='m3'"
    )
    assert len(events) == 1 and str(events[0]["event_type"]) == "labelAdded"
    assert _cursor(handles)[1] > 1  # a re-claim strictly advances the fencing token


# -- two workers on one cursor -------------------------------------------------------------------
def test_two_competing_workers_exactly_one_advances(handles: _Handles, monkeypatch) -> None:
    register(handles)
    clock = _clock()
    winner = build(handles, clock, _fake(), owner="reader-a")
    monkeypatch.setattr(winner, "_release", lambda: None)  # simulate a long in-flight iteration
    assert winner.tick(Event()).action == "observed"
    before, written = _cursor(handles), _obs_count(handles)
    loser_fake = _fake()
    loser = build(handles, clock, loser_fake, owner="reader-b")
    result = loser.tick(Event())
    assert result.action == "backoff" and result.safe_reason == "lease_held_by_active_worker"
    assert _cursor(handles) == before  # committed id, fence, owner and updated_at all unchanged
    assert _obs_count(handles) == written
    assert (loser_fake.profile_calls, loser_fake.list_calls, loser_fake.body_calls) == (0, 0, 0)
    clock.advance_seconds(61)  # the lease expires against the injected clock, not wall time
    assert loser.tick(Event()).action == "observed"
    after = _cursor(handles)
    assert after[2] == "reader-b" and after[1] > before[1]


# -- pause / revoke / connection state ------------------------------------------------------------
def _gate(db: object) -> object:
    def gate(as_of: str) -> ExecutionRestrictions:
        return restrictions_for(
            db,  # type: ignore[arg-type]
            owner_id=OWNER,
            connection_id=CONNECTION,
            account_id=ACCOUNT,
            resource_id="cohort",
            class_key=None,
            action="OBSERVE",
            as_of=as_of,
        )

    return gate


def _submit(db: object, key: str, kind: str, at: str) -> None:
    CommandStore(RoleAccess(db, Role.API)).submit(  # type: ignore[arg-type]
        CommandIntent(
            request_id=key,
            owner_id=OWNER,
            type=kind,  # type: ignore[arg-type]
            scope=CommandScope(connection_id=CONNECTION, account_id=ACCOUNT),
            created_at=at,
        )
    )


def test_pause_blocks_dispatch_and_advance_until_consumed_resume(
    handles: _Handles, memory_db
) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    worker = build(handles, clock, fake, restrictions=_gate(memory_db))
    assert worker.tick(Event()).action == "observed"
    before, calls = _cursor(handles), (fake.list_calls, fake.history_calls)
    _submit(memory_db, "p1", "pause", "2026-10-24T08:59:30Z")
    blocked = worker.tick(Event())
    assert blocked.action == "blocked" and blocked.safe_reason == "control_paused"
    assert _cursor(handles) == before  # no claim, no advance while paused
    assert (fake.list_calls, fake.history_calls) == calls  # no dispatch of any affected request
    assert process_restriction_commands(memory_db, as_of="2026-10-24T09:00:00Z") == 1
    _submit(memory_db, "r1", "resume", "2026-10-24T08:59:45Z")
    process_restriction_commands(memory_db, as_of="2026-10-24T09:00:00Z")
    assert worker.tick(Event()).action == "observed"


def test_pending_revocation_blocks_before_next_effect(handles: _Handles, memory_db) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    worker = build(handles, clock, fake, restrictions=_gate(memory_db))
    assert worker.tick(Event()).action == "observed"
    before = _cursor(handles)
    _submit(memory_db, "v1", "revoke", "2026-10-24T08:59:30Z")
    assert worker.tick(Event()).safe_reason == "control_revoked"
    assert _cursor(handles) == before
    assert fake.body_calls == 2  # nothing dispatched after the revocation appeared


def test_non_observing_state_blocks_and_disconnect_stops_loop(handles: _Handles) -> None:
    register(handles, state="PAUSED")
    fake = _fake()
    result = build(handles, _clock(), fake).tick(Event())
    assert result.action == "blocked" and result.safe_reason == "connection_state_paused"
    assert (fake.profile_calls, fake.list_calls, fake.body_calls) == (0, 0, 0)
    admin = handles.access("administration")
    admin.write(
        "gmail_connections", "UPDATE gmail_connections SET state='DISCONNECTED' WHERE 1=1", ()
    )
    results: list[ObservationTickResult] = []
    ticks = build(handles, _clock(), fake).run(Event(), max_ticks=3, on_result=results.append)
    assert ticks == 1 and results[0].action == "stopped" and results[0].stops_loop


# -- retries, auth and dispatch limits ------------------------------------------------------------
class _Flaky(FakeGmailTransport):
    def __init__(
        self, *, fail_times: int, status: int = 503, retry_after: float | None = None
    ) -> None:
        super().__init__(expected_token="read-token", page_size=2)
        self.remaining = fail_times
        self.status = status
        self.retry_after = retry_after
        self.profile_attempts = 0

    def get(self, url, *, params=None, access_token):  # type: ignore[no-untyped-def]
        if url.endswith("/profile"):
            self.profile_attempts += 1
            if self.remaining > 0:
                self.remaining -= 1
                return HttpResult(status=self.status, retry_after_seconds=self.retry_after)
        return super().get(url, params=params, access_token=access_token)


def test_safe_read_retry_honours_retry_after_on_the_clock(handles: _Handles) -> None:
    register(handles)
    clock = _clock()
    flaky = _Flaky(fail_times=1, retry_after=7.0)
    result = build(handles, clock, flaky).tick(Event())
    assert result.action == "observed" and flaky.profile_attempts == 2
    # The backoff was spent on the injected clock, never on wall time.
    assert timestamp_key(clock.now_iso()) - timestamp_key("2026-10-24T09:00:00Z") >= 7_000_000


def test_retries_are_bounded_and_degrade_without_advancing(handles: _Handles) -> None:
    register(handles)
    clock = _clock()
    flaky = _Flaky(fail_times=99)
    result = build(handles, clock, flaky).tick(Event())
    assert result.action == "degraded" and result.safe_reason == "read_retries_exhausted_503"
    assert flaky.profile_attempts == 3  # exactly max_attempts, then it stops
    assert _cursor(handles)[3] == "2026-10-24T09:00:00Z"  # cursor row untouched


class _Counting:
    """Counts raw GET dispatches so 'never spins on auth' is provable at the transport seam."""

    def __init__(self, inner: FakeGmailTransport) -> None:
        self._inner = inner
        self.gets = 0

    def get(self, url, *, params=None, access_token):  # type: ignore[no-untyped-def]
        self.gets += 1
        return self._inner.get(url, params=params, access_token=access_token)


def test_authorization_failure_halts_and_never_spins(handles: _Handles) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    counter = _Counting(fake)
    worker = build(handles, clock, fake, transport=counter, token="wrong-token")
    results: list[ObservationTickResult] = []
    ticks = worker.run(Event(), max_ticks=5, on_result=results.append)
    assert ticks == 1 and results[0].action == "halted"
    assert counter.gets == 1  # one attempt, no retry spin on an auth refusal
    assert _readiness_rows(handles)["read"][1] == "authorization_denied"
    assert _cursor(handles)[0] == 0  # no cursor was ever advanced


def test_worker_is_structurally_unable_to_dispatch_or_retry_effects(handles: _Handles) -> None:
    class _GetOnly:
        def __init__(self, inner: FakeGmailTransport) -> None:
            self._inner = inner

        def get(self, url, *, params=None, access_token):  # type: ignore[no-untyped-def]
            return self._inner.get(url, params=params, access_token=access_token)

    register(handles)
    clock, fake = _clock(), _fake()
    only = _GetOnly(fake)
    assert build(handles, clock, fake, transport=only).tick(Event()).action == "observed"
    retry = RetryingReadTransport(only, clock, Event())
    assert not hasattr(retry, "post")  # an effectful request can neither be sent nor retried here
    with pytest.raises(ConnectorError, match="read_only_grant"):
        GmailObservationWorker(
            connection_id=CONNECTION,
            owner="x",
            ingest=handles.access("ingestor"),
            capabilities=None,
            credentials=_provider(clock, role="write"),
            transport=only,
            clock=clock,
            restrictions=_never_restricted,
        )
    ingest = handles.access("ingestor")
    with pytest.raises(StoreAccessError):
        ingest.write("gmail_effect_receipts", "SELECT 1")  # executor-owned rows are unwritable here


# -- crash safety, resync and write-grant truthfulness ---------------------------------------------
def test_crash_after_commit_repeats_safely_before_acknowledgement(
    handles: _Handles, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    doomed = build(handles, clock, fake)

    def boom(readiness: object, account_id: str) -> None:
        del readiness, account_id
        raise RuntimeError("crash after commit, before readiness ack")

    monkeypatch.setattr(doomed, "_persist", boom)
    with pytest.raises(RuntimeError):
        doomed.tick(Event())
    assert _obs_count(handles) == 2 and _cursor(handles)[0] > 0  # progress persisted first
    assert _readiness_rows(handles) == {}  # the ack never landed
    restarted = build(handles, clock, fake)
    assert restarted.tick(Event()).action == "observed"
    assert _obs_count(handles) == 2  # the PK dedupe makes the repeat safe, not duplicated


def test_resync_gap_degrades_readiness_and_blocks_dependence(handles: _Handles) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    worker = build(handles, clock, fake)
    committed = worker.tick(Event()).committed_history_id
    fake.set_history_expired_below(committed + 1)  # the durable anchor aged out (C3)
    result = worker.tick(Event())
    assert result.action == "degraded" and result.safe_reason == "resync_required"
    readiness = result.readiness
    assert readiness is not None and not readiness.freshness.fresh
    assert readiness.blocking_reason == "resync_required"
    assert not readiness.dependent_autonomy_permitted
    assert readiness.state("undo_history_proof").reason == "resync_blocks_undo_proof"  # type: ignore[union-attr]
    assert readiness.supports("read") is True  # observation itself is not revoked by a resync
    assert _cursor(handles)[0] == committed  # a failed catch-up advanced nothing


def test_failed_write_grant_keeps_observation_and_degrades_write_readiness(
    handles: _Handles,
) -> None:
    register(handles)
    executor = handles.access("executor")
    executor.write(
        "gmail_capabilities",
        "INSERT INTO gmail_capabilities VALUES(?,?,?,?,?,?,?,?,?)",
        (
            CONNECTION,
            ACCOUNT,
            "send",
            "write",
            0,
            "unsupported",
            "scope_not_granted_gmail_send",
            1,
            "2026-10-24T09:00:00Z",
        ),
    )
    result = build(handles, _clock(), _fake()).tick(Event())
    assert (
        result.action == "observed"
    )  # the approved observation ran untouched by the write failure
    assert result.readiness.supports("send") is False
    assert result.readiness.state("send").reason == "scope_not_granted_gmail_send"  # type: ignore[union-attr]
    assert result.readiness.supports("read") is True
    assert _readiness_rows(handles)["read"] == (
        1,
        None,
    )  # read row owned and written by read_worker


def _seed_unfinished_resync(handles: _Handles, *, sequence: int = 1) -> None:
    """The durable state a crashed resync leaves: an attempt with no terminal marker."""
    now = "2026-10-24T09:00:00Z"
    handles.access("ingestor").write(
        "gmail_sync_cursors",
        "INSERT INTO gmail_sync_cursors (connection_id,account_id,resource_key,role,"
        "filter_revision,bootstrap_history_id,page_token,created_at,updated_at)"
        " VALUES(?,?,?,'read',1,2,'in_progress',?,?)",
        (CONNECTION, ACCOUNT, f"resync:cohort:{sequence}", now, now),
    )


def _write_rows(handles: _Handles) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in handles.access("api").query(
            "SELECT name,supported,reason,verified_at FROM gmail_capabilities"
            " WHERE owner_role='write' ORDER BY name"
        )
    ]


def test_completed_resync_clears_degraded_but_does_not_restore_authority(
    handles: _Handles,
) -> None:
    register(handles)
    executor = handles.access("executor")
    executor.write(
        "gmail_capabilities",
        "INSERT INTO gmail_capabilities VALUES(?,?,?,?,?,?,?,?,?)",
        (
            CONNECTION,
            ACCOUNT,
            "send",
            "write",
            0,
            "unsupported",
            "scope_not_granted_gmail_send",
            1,
            "2026-10-24T09:00:00Z",
        ),
    )
    clock, fake = _clock(), _fake()
    worker = build(handles, clock, fake)
    committed = worker.tick(Event()).committed_history_id
    _seed_unfinished_resync(handles)

    held = worker.tick(Event())
    assert held.action == "degraded" and held.safe_reason == "resync_in_progress"
    assert held.resync.in_progress is True
    assert held.readiness is not None
    assert held.readiness.blocking_reason == "resync_in_progress"
    assert held.readiness.dependent_autonomy_permitted is False

    fake.set_history_expired_below(committed + 1)
    fake.add_message(_message("m3", {LABEL}))
    recovered = worker.tick(Event())
    assert recovered.action == "observed" and recovered.safe_reason is None
    assert recovered.resync.in_progress is False
    assert recovered.resync.last_successful_at is not None
    assert recovered.resync.last_failure_code is None
    readiness = recovered.readiness
    assert readiness is not None and readiness.freshness.fresh is True
    assert readiness.freshness.resync_in_progress is False
    assert readiness.freshness.last_successful_resync_at == recovered.resync.last_successful_at
    assert readiness.freshness.last_resync_failure_code is None
    assert readiness.blocking_reason is None
    # Freshness recovered; authority did not. A completed resync restores no capability: the
    # Executor-owned row is byte-identical and read readiness still reports send unsupported.
    assert readiness.supports("send") is False
    assert _write_rows(handles) == [
        {
            "name": "send",
            "supported": 0,
            "reason": "scope_not_granted_gmail_send",
            "verified_at": "2026-10-24T09:00:00Z",
        }
    ]
    assert _obs_count(handles) == 3


def test_run_polls_on_the_injected_clock_and_stop_ends_it(handles: _Handles) -> None:
    register(handles)
    clock, fake = _clock(), _fake()
    worker = build(handles, clock, fake)
    stop = Event()
    seen: list[ObservationTickResult] = []

    def first_then_stop(result: ObservationTickResult) -> None:
        seen.append(result)
        if len(seen) == 1:
            first_then_stop.t0 = clock.now_iso()  # type: ignore[attr-defined]

    ticks = worker.run(stop, max_ticks=2, on_result=first_then_stop)
    assert ticks == 2
    elapsed = timestamp_key(clock.now_iso()) - timestamp_key(first_then_stop.t0)  # type: ignore[attr-defined]
    assert 29_000_000 <= elapsed <= 31_000_000  # the 30s default poll is clock-driven
    stop.set()
    assert worker.run(stop, max_ticks=3) == 0  # a set stop event ends the loop with zero dispatch


def test_retry_transport_retries_transport_failure_bounded() -> None:
    clock = _clock()
    stop = Event()
    calls = 0

    class MockInner:
        def get(
            self, url: str, *, params: dict[str, object] | None = None, access_token: str
        ) -> HttpResult:
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise TransportFailure("transport_timeout")
            return HttpResult(
                status=200, body=b"{}", retry_after_seconds=None, request_id_hash=None
            )

    transport = RetryingReadTransport(MockInner(), clock=clock, stop=stop, max_attempts=3)  # type: ignore[arg-type]
    result = transport.get("https://example.test", access_token="tok")
    assert result.status == 200
    assert calls == 3


def test_retry_transport_exhausts_transport_failures() -> None:
    clock = _clock()
    stop = Event()

    class MockInner:
        def get(
            self, url: str, *, params: dict[str, object] | None = None, access_token: str
        ) -> HttpResult:
            raise TransportFailure("transport_connect_failed")

    transport = RetryingReadTransport(MockInner(), clock=clock, stop=stop, max_attempts=3)  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailable) as exc_info:
        transport.get("https://example.test", access_token="tok")
    assert exc_info.value.safe_code == "read_retries_exhausted_transport"


def test_retry_transport_never_retries_auth() -> None:
    clock = _clock()
    stop = Event()
    calls = 0

    class MockInner:
        def get(
            self, url: str, *, params: dict[str, object] | None = None, access_token: str
        ) -> HttpResult:
            nonlocal calls
            calls += 1
            return HttpResult(
                status=401, body=b"{}", retry_after_seconds=None, request_id_hash=None
            )

    transport = RetryingReadTransport(MockInner(), clock=clock, stop=stop, max_attempts=3)  # type: ignore[arg-type]
    with pytest.raises(AuthorizationFailed) as exc_info:
        transport.get("https://example.test", access_token="tok")
    assert "provider_status_401" in str(exc_info.value)
    assert calls == 1
