"""Local always-on runtime: role-bound connections, one grant per child, status-only coordinator.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5 and 11 (row 31),
docs/OCT29_DEMO_BUILD_PLAN.md 10 and docs/CONTRACT.md section 3. Everything is synthetic and
offline: the parent environment carries obviously fake grant material, no process is started
for real (launchers are recorded fakes), and no provider is contacted.
"""

import subprocess
from collections.abc import Callable, Mapping, Sequence
from inspect import signature
from pathlib import Path
from threading import Event

import pytest

import probation.workers.gmail_runtime as runtime_module
import probation.workers.gmail_runtime_provisioning as provisioning_module
from probation.connectors.acl import PrivatePathRejected, apply_owner_only
from probation.connectors.credentials_state import ProvisionedGrant
from probation.connectors.types import ConnectorError, HttpResult
from probation.core.clock import Clock, parse_timestamp
from probation.core.lifecycle import CommandIntent, CommandScope
from probation.db.access import Role, RoleAccess
from probation.db.connection import get_role_connection, init_db
from probation.db.gmail_store import (
    ConnectorAccess,
    migrate_store,
    open_store,
    store_is_current,
)
from probation.db.guards import AccessError
from probation.db.lifecycle_commands import CommandStore
from probation.workers.gmail_observation import GmailObservationWorker
from probation.workers.gmail_runtime import (
    CREDENTIAL_ROLES,
    ENGINE_ROLES,
    GmailRuntime,
    RuntimeRole,
    build_coordinator,
    build_role_context,
)
from probation.workers.gmail_runtime import (
    main as runtime_main,
)
from probation.workers.gmail_runtime_provisioning import RoleProvisioning, StepProvisioning
from probation.workers.lifecycle import TickResult, WorkerSteps

READ_GRANT = ProvisionedGrant(
    role="read",
    connection_id="conn-fake-1",
    account_id="acct-fake-1",
    credential_ref="cred-read-1",
)
WRITE_GRANT = ProvisionedGrant(
    role="write",
    connection_id="conn-fake-1",
    account_id="acct-fake-1",
    credential_ref="cred-write-1",
)
FOREIGN_GRANT_ENV = "PROBATION_GMAIL_GRANT_READ_CRED_FOREIGN_0000000000"


class _FakeProcess:
    """A spawned process stand-in whose only effects are recorded."""

    def __init__(self, exit_code: int | None = None) -> None:
        self.returncode = exit_code
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-role", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


Launcher = Callable[[Sequence[str], Mapping[str, str]], "_FakeProcess"]


def _role_of(command: Sequence[str]) -> RuntimeRole:
    return RuntimeRole(command[list(command).index("--role") + 1])


def _recording(calls: list[tuple[list[str], dict[str, str]]]) -> Launcher:
    def launch(command: Sequence[str], env: Mapping[str, str]) -> _FakeProcess:
        calls.append((list(command), dict(env)))
        return _FakeProcess()

    return launch


def _env_with(*grants: ProvisionedGrant) -> dict[str, str]:
    env = {
        "PATH": "C:/fake/bin",
        "SYSTEMROOT": "C:/fake/windows",
        "PROBATION_RUNTIME_CONNECTION_ID": "conn-fake-1",
        "PROBATION_RUNTIME_ACCOUNT_ID": "acct-fake-1",
        "PROBATION_RUNTIME_CREDENTIAL_REF": "cred-fake-ref",
        "PARENT_ONLY_SECRET": "never-inherited",
        FOREIGN_GRANT_ENV: "foreign-read-material",
    }
    for grant in grants:
        env[grant.env_name] = f"fake-refresh-{grant.role}"
    return env


def _zero(conn: object, as_of: str, limit: int) -> int:
    del conn, as_of, limit
    return 0


def _zero_steps() -> WorkerSteps:
    return WorkerSteps(_zero, _zero, _zero, _zero)


@pytest.fixture
def engine(tmp_path: Path) -> Path:
    path = tmp_path / "engine.db"
    init_db(path)
    return path


@pytest.fixture
def private_store(tmp_path: Path) -> Path:
    path = tmp_path / "private" / "gmail_metadata.db"
    path.parent.mkdir(parents=True)
    apply_owner_only(path.parent, is_dir=True)  # the runtime verifies, never repairs, this ACL
    conn = open_store(path)
    assert migrate_store(conn) is True
    conn.close()
    return path


@pytest.fixture
def clock() -> Clock:
    return Clock.replay(parse_timestamp("2026-10-24T09:00:00Z"))


class _NullTransport:
    """ReadTransport stand-in: construction must not contact any provider."""

    def get(
        self, url: str, *, params: "dict[str, object] | None" = None, access_token: str
    ) -> HttpResult:
        del url, params, access_token
        raise AssertionError("transport must not be called during role construction")


_CONNECTION_SQL = """INSERT INTO gmail_connections
 (connection_id,account_id,owner_id,state,selection_revision,label_ids,credential_ref,
  granted_scopes,created_at,updated_at) VALUES(?,?,?,?,?,'["COHORT"]',?,'["gmail.readonly"]',?,?)"""


def _register(
    store: Path,
    *,
    connection_id: str = "conn-fake-1",
    account_id: str = "acct-fake-1",
    owner: str = "owner-1",
    state: str = "ACTIVE",
    at: str = "2026-10-24T08:00:00Z",
) -> None:
    """Bootstrap one connection row through the administration authority."""
    conn = open_store(store)
    try:
        ConnectorAccess(conn, "administration").write(
            "gmail_connections",
            _CONNECTION_SQL,
            (connection_id, account_id, owner, state, 1, "cred-write-1", at, at),
        )
    finally:
        conn.close()


def _context(
    role: RuntimeRole,
    engine: Path,
    store: Path,
    clock: Clock,
    grants: Mapping[RuntimeRole, ProvisionedGrant] | None = None,
    env: Mapping[str, str] | None = None,
) -> runtime_module.RoleContext:
    return build_role_context(
        role,
        db_path=engine,
        private_store_path=store,
        env={} if env is None else env,
        clock=clock,
        grants={} if grants is None else grants,
    )


def test_each_role_gets_its_own_bound_connection(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    contexts = [_context(role, engine, private_store, clock) for role in RuntimeRole]
    try:
        assert len({id(context.connection) for context in contexts}) == len(RuntimeRole)
        for context in contexts:
            assert context.connection.bound_role == ENGINE_ROLES[context.role].value
        by_role = {context.role: context for context in contexts}
        forbidden = {
            RuntimeRole.OBSERVATION: "features",
            RuntimeRole.BRAIN: "actions",
            RuntimeRole.RESOLVER: "features",
            RuntimeRole.EXAMINER: "actions",
            RuntimeRole.API: "ledger",
            RuntimeRole.EXECUTOR: "proposals",
        }
        for role, table in forbidden.items():
            access = RoleAccess(by_role[role].connection, ENGINE_ROLES[role])
            with pytest.raises(AccessError):
                access.execute_write(table, f"INSERT INTO {table}(id) VALUES('x')")
    finally:
        for context in contexts:
            context.close()


def test_only_executor_context_holds_a_write_credential(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    grants = {RuntimeRole.OBSERVATION: READ_GRANT, RuntimeRole.EXECUTOR: WRITE_GRANT}
    observation = _context(RuntimeRole.OBSERVATION, engine, private_store, clock, grants)
    executor = _context(RuntimeRole.EXECUTOR, engine, private_store, clock, grants)
    try:
        assert observation.provider is not None
        assert observation.provider.role == "read"
        assert executor.provider is not None
        assert executor.provider.role == "write"
        with pytest.raises(ConnectorError):
            build_role_context(
                RuntimeRole.OBSERVATION,
                db_path=engine,
                private_store_path=private_store,
                env=_env_with(WRITE_GRANT),
                clock=clock,
                grants={RuntimeRole.OBSERVATION: WRITE_GRANT},
            )
    finally:
        observation.close()
        executor.close()


def test_brain_resolver_examiner_api_hold_no_google_credential(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    grants = dict.fromkeys(RuntimeRole, WRITE_GRANT)
    for role in (
        RuntimeRole.BRAIN,
        RuntimeRole.RESOLVER,
        RuntimeRole.EXAMINER,
        RuntimeRole.API,
    ):
        context = _context(role, engine, private_store, clock, grants)
        try:
            assert CREDENTIAL_ROLES[role] is None
            assert context.grant is None
            assert context.provider is None
            if role is RuntimeRole.API:
                assert [item.authority for item in context.connectors] == ["api"]
            else:
                assert context.connectors == ()
        finally:
            context.close()


def test_coordinator_receives_status_not_credentials(engine: Path, clock: Clock) -> None:
    params = set(signature(build_coordinator).parameters)
    assert not {"provider", "credentials", "grant", "env"} & params
    seen: list[TickResult] = []
    coordinator, connections = build_coordinator(db_path=engine, clock=clock, steps=_zero_steps())
    try:
        assert not hasattr(coordinator, "provider")
        assert not any("credential" in name or "grant" in name for name in vars(coordinator))
        assert coordinator.run(Event(), max_ticks=1, on_result=seen.append) == 1
        assert len(seen) == 1 and isinstance(seen[0], TickResult)
        assert not hasattr(seen[0], "credential")
    finally:
        for connection in connections.all():
            connection.close()


def test_spawn_passes_allowlisted_environment_only(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    runtime = GmailRuntime(
        db_path=engine,
        private_store_path=private_store,
        env=_env_with(READ_GRANT, WRITE_GRANT),
        clock=clock,
        grants={RuntimeRole.OBSERVATION: READ_GRANT, RuntimeRole.EXECUTOR: WRITE_GRANT},
        launcher=_recording(calls),
    )
    stop = Event()
    stop.set()
    runtime.run(stop, join_timeout=0.01)
    envs = {_role_of(command): env for command, env in calls}
    observation = envs[RuntimeRole.OBSERVATION]
    executor = envs[RuntimeRole.EXECUTOR]
    assert {key for key in observation if key.startswith("PROBATION_GMAIL_GRANT_")} == {
        READ_GRANT.env_name
    }
    assert {key for key in executor if key.startswith("PROBATION_GMAIL_GRANT_")} == {
        WRITE_GRANT.env_name
    }
    assert WRITE_GRANT.env_name not in observation
    assert READ_GRANT.env_name not in executor
    assert not {key for key in envs[RuntimeRole.BRAIN] if key.startswith("PROBATION_GMAIL_GRANT_")}
    assert FOREIGN_GRANT_ENV not in observation
    assert "PARENT_ONLY_SECRET" not in observation
    assert "PATH" in observation and "SYSTEMROOT" in observation


def test_one_role_per_process_plan(engine: Path, private_store: Path, clock: Clock) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    runtime = GmailRuntime(
        db_path=engine,
        private_store_path=private_store,
        env=_env_with(),
        clock=clock,
        launcher=_recording(calls),
    )
    stop = Event()
    stop.set()
    runtime.run(stop, join_timeout=0.01)
    assert len(calls) == len(RuntimeRole)
    assert [_role_of(command) for command, _ in calls] == list(RuntimeRole)
    for command, _ in calls:
        role = _role_of(command)
        assert command == runtime.command_for(role)
        assert command[command.index("--role") + 1] == role.value


def test_executor_credential_failure_degrades_write_not_observation(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    runtime = GmailRuntime(
        db_path=engine,
        private_store_path=private_store,
        env=_env_with(READ_GRANT),
        clock=clock,
        grants={RuntimeRole.OBSERVATION: READ_GRANT, RuntimeRole.EXECUTOR: WRITE_GRANT},
        launcher=_recording(calls),
    )
    stop = Event()
    stop.set()
    report = runtime.run(stop, join_timeout=0.01)
    observation = report.status(RuntimeRole.OBSERVATION)
    executor = report.status(RuntimeRole.EXECUTOR)
    assert (observation.capability, observation.capability_ready) == ("read", True)
    assert (executor.capability, executor.capability_ready) == ("write", False)
    assert executor.state == "degraded"
    assert {_role_of(command) for command, _ in calls} == set(RuntimeRole)


def test_stop_shuts_down_all_roles(engine: Path, private_store: Path, clock: Clock) -> None:
    handles: dict[RuntimeRole, _FakeProcess] = {}

    def launch(command: Sequence[str], env: Mapping[str, str]) -> _FakeProcess:
        del env
        handle = _FakeProcess()
        handles[_role_of(command)] = handle
        return handle

    runtime = GmailRuntime(
        db_path=engine,
        private_store_path=private_store,
        env=_env_with(READ_GRANT, WRITE_GRANT),
        clock=clock,
        grants={RuntimeRole.OBSERVATION: READ_GRANT, RuntimeRole.EXECUTOR: WRITE_GRANT},
        launcher=launch,
    )
    stop = Event()
    stop.set()
    report = runtime.run(stop, join_timeout=0.01)
    assert len(handles) == len(RuntimeRole)
    assert all(handle.terminated for handle in handles.values())
    assert {status.state for status in report.values()} == {"stopped"}


def test_role_failure_does_not_silently_hide(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    handles: dict[RuntimeRole, _FakeProcess] = {}

    def launch(command: Sequence[str], env: Mapping[str, str]) -> _FakeProcess:
        del env
        role = _role_of(command)
        handle = _FakeProcess(exit_code=1 if role is RuntimeRole.BRAIN else None)
        handles[role] = handle
        return handle

    runtime = GmailRuntime(
        db_path=engine,
        private_store_path=private_store,
        env=_env_with(READ_GRANT, WRITE_GRANT),
        clock=clock,
        grants={RuntimeRole.OBSERVATION: READ_GRANT, RuntimeRole.EXECUTOR: WRITE_GRANT},
        launcher=launch,
    )
    stop = Event()
    stop.set()
    report = runtime.run(stop, join_timeout=0.01)
    brain = report.status(RuntimeRole.BRAIN)
    assert brain.state == "failed"
    assert brain.detail == "exit_code_1"
    assert len(report) == len(RuntimeRole)
    assert report.status(RuntimeRole.OBSERVATION).state == "stopped"
    assert report.status(RuntimeRole.EXECUTOR).state == "stopped"
    assert report.status(RuntimeRole.API).state == "stopped"


def test_no_service_installation_or_admin_path() -> None:
    source = Path(runtime_module.__file__).read_text(encoding="utf-8").lower()
    for token in (
        "winreg",
        "win32service",
        "servicemanager",
        "pubsub",
        "createservice",
        "schtasks",
        "sc.exe",
        "runas",
        "shell=true",
    ):
        assert token not in source


# -- real worker composition ----------------------------------------------------------------------
def test_observation_entrypoint_constructs_the_real_worker(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    _register(private_store)
    context = build_role_context(
        RuntimeRole.OBSERVATION,
        db_path=engine,
        private_store_path=private_store,
        env=_env_with(READ_GRANT),
        clock=clock,
        grants={RuntimeRole.OBSERVATION: READ_GRANT},
        read_transport=_NullTransport(),
    )
    try:
        assert isinstance(context.worker, GmailObservationWorker)  # not a stub or a lambda
        assert context.entrypoint.__self__ is context.worker  # type: ignore[attr-defined]
        assert context.provisioning.status_of("observation") == "provisioned"
        assert context.provisioning.ready
        assert context.provider is not None and context.provider.role == "read"
        assert [item.authority for item in context.connectors] == ["ingestor", "read_worker"]
    finally:
        context.close()


# -- executor coordinator steps -------------------------------------------------------------------
def test_executor_consumes_commands_through_the_real_consumer(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    at = "2026-10-24T08:59:30Z"
    _register(private_store, at=at)
    api = get_role_connection(engine, Role.API)
    try:
        CommandStore(RoleAccess(api, Role.API)).submit(
            CommandIntent(
                request_id="pause-runtime",
                owner_id="owner-1",
                type="pause",
                scope=CommandScope(connection_id="conn-fake-1", account_id="acct-fake-1"),
                created_at=at,
            )
        )
    finally:
        api.close()
    seen: list[TickResult] = []
    stop = Event()

    def on_status(result: TickResult) -> None:
        seen.append(result)
        stop.set()  # one real runtime tick is enough; shutdown is Event-driven

    context = build_role_context(
        RuntimeRole.EXECUTOR,
        db_path=engine,
        private_store_path=private_store,
        env=_env_with(WRITE_GRANT),
        clock=clock,
        grants={RuntimeRole.EXECUTOR: WRITE_GRANT},
        on_status=on_status,
    )
    try:
        assert context.entrypoint(stop) == 1
        assert len(seen) == 1
        tick = seen[0]
        assert tick.counts.get("consume") == 1  # the real consumer applied the intent
        assert "effects:not_provisioned" in tick.errors
        administration = next(
            item for item in context.connectors if item.authority == "administration"
        )
        row = administration.one(
            "SELECT state FROM gmail_connections WHERE connection_id=?", ("conn-fake-1",)
        )
        assert row is not None and str(row["state"]) == "PAUSED"
        receipts = administration.query(
            "SELECT command_id,consumer,state,applied_state FROM gmail_command_receipts"
        )
        assert [
            (str(item["command_id"]), str(item["consumer"]), str(item["applied_state"]))
            for item in receipts
        ] == [("pause-runtime", "connector", "PAUSED")]
    finally:
        context.close()


def test_unprovisioned_step_reports_not_provisioned_not_zero(
    engine: Path, private_store: Path, clock: Clock
) -> None:
    context = _context(RuntimeRole.EXECUTOR, engine, private_store, clock)
    try:
        provisioning = context.provisioning
        assert provisioning.status_of("resolver") == "provisioned"
        assert provisioning.status_of("consume") == "provisioned"
        assert provisioning.status_of("effects") == "not_provisioned"
        assert provisioning.status_of("followups") == "not_provisioned"
        assert not provisioning.ready
        assert context.coordinator is not None
        tick = context.coordinator.tick(Event())
        # A provisioned stage that ran and found nothing is a truthful zero...
        assert tick.counts.get("resolver") == 0
        assert tick.counts.get("consume") == 0
        # ...an unprovisioned stage is never reported as a zero: it carries its typed code.
        assert "effects" not in tick.counts
        assert "effects:not_provisioned" in tick.errors
        assert "followups" not in tick.counts
    finally:
        context.close()


# -- startup store provisioning -------------------------------------------------------------------
def test_startup_denies_on_acl_failure(
    engine: Path, private_store: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(path: Path) -> None:
        del path
        raise PrivatePathRejected("test_acl_denied")

    monkeypatch.setattr(provisioning_module, "verify_owner_only", deny)
    with pytest.raises(ConnectorError) as caught:
        _context(RuntimeRole.API, engine, private_store, clock)
    assert caught.value.safe_code == "connector_store_acl_unverified"


def test_startup_migrates_connector_store_when_missing(
    engine: Path, tmp_path: Path, clock: Clock
) -> None:
    store = tmp_path / "private" / "gmail_metadata.db"
    assert not store.exists()
    context = _context(RuntimeRole.API, engine, store, clock)
    try:
        assert store.is_file()
        probe = open_store(store)
        try:
            assert store_is_current(probe) is True
        finally:
            probe.close()
    finally:
        context.close()


# -- main refuses an unprovisioned role -----------------------------------------------------------
class _FakeContext:
    """Minimal look-alike: only the surface ``main`` is allowed to consult."""

    def __init__(self) -> None:
        self.provisioning = RoleProvisioning(
            (
                StepProvisioning("consume", "provisioned"),
                StepProvisioning("effects", "not_provisioned", "gmail_write_path_not_provisioned"),
            )
        )
        self.ran = False
        self.closed = False

    def entrypoint(self, stop: Event) -> int:
        del stop
        self.ran = True
        return 0

    def close(self) -> None:
        self.closed = True


def test_main_refuses_unprovisioned_role_without_explicit_flag(
    engine: Path,
    private_store: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("PROBATION_RUNTIME_HOST", raising=False)
    context = _FakeContext()
    monkeypatch.setattr(runtime_module, "build_role_context", lambda *_a, **_k: context)
    argv = ["--role", "executor", "--db", str(engine), "--private-store", str(private_store)]

    assert runtime_main(argv) == 2
    assert context.ran is False and context.closed is True
    assert "role_not_provisioned steps=effects" in capsys.readouterr().err

    context.closed = False
    assert runtime_main([*argv, "--allow-degraded"]) == 3
    assert context.ran is True and context.closed is True
    assert "runtime_degraded: role=executor steps=effects" in capsys.readouterr().err
