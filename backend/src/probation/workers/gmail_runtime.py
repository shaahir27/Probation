"""Always-on local runtime: one process per role, role-bound connections, status-only coordinator.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5, 7 and 11 (row 31), and
docs/CONTRACT.md section 3. Each role runs in its own process with its own bound connection and
an allowlist-built child environment carrying at most one Gmail grant. The supervisor holds no
provider; the coordinator is composed from four role-bound connections and has no credential
parameter. Every role that opens the private connector store verifies its owner-only ACL first
and migrates it when not current. An unprovisioned role is refused by ``main`` unless the
explicit ``--allow-degraded`` flag is passed; an unprovisioned stage fails with its typed
``not_provisioned`` code instead of reporting a zero count.
"""

from __future__ import annotations

import argparse
import os
import signal
import sqlite3
import struct
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from threading import Event
from types import MappingProxyType
from typing import Final, Literal

from probation.connectors.credentials import RoleCredentialProvider
from probation.connectors.credentials_state import (
    BASE_CHILD_ENV,
    EnvCredentialSource,
    ProvisionedGrant,
)
from probation.connectors.types import ConnectorError, CredentialRole
from probation.core.clock import Clock, operational_clock
from probation.core.runtime_status import (
    RoleReadiness,
    publish_runtime_status,
    runtime_status_path,
)
from probation.db.access import Role
from probation.db.connection import get_connection, get_role_connection, has_schema
from probation.db.gmail_store import ConnectorAccess, ConnectorAuthority, open_store
from probation.packs.mail.connectors.gmail_ingest import GmailIngestBridge
from probation.packs.mail.connectors.gmail_payloads import GmailPayloadStore
from probation.packs.mail.connectors.gmail_transport import GmailHttpTransport
from probation.workers.d5_ipc import BrainWebFactsClient, ByteChannel, StdioChannel
from probation.workers.gmail_brain import run_brain
from probation.workers.gmail_live import build_live_provider
from probation.workers.gmail_observation import (
    GmailObservationWorker,
    ObservationTickResult,
    ReadTransport,
)
from probation.workers.gmail_role_loops import (
    WORK_STALENESS_SECONDS,
    WorkLedger,
    decode_work_status,
    email_webfacts_verifier,
    replay_controller_for_owner,
    run_api_server,
    run_examiner,
    run_resolver,
    run_webfacts,
    write_work_status,
)
from probation.workers.gmail_runtime_provisioning import (
    EXECUTOR_LIVE_PROVISIONS,
    EXECUTOR_PROVISIONS,
    LiveExecutorDeps,
    ObservationDeps,
    RoleProvisioning,
    StepProvisioning,
    executor_steps,
    injected_provisions,
    observation_worker,
    verify_and_migrate_store,
)
from probation.workers.lifecycle import (
    LifecycleCoordinator,
    RoleConnections,
    TickResult,
    WorkerSteps,
)

Entrypoint = Callable[[Event], int]
Capability = CredentialRole | Literal["none"]
RoleState = Literal["stopped", "degraded", "failed"]
#: Non-secret identity of the single grant a child may hold, as "connection|account|reference".
#: The secret itself stays in the grant variable named by ``ProvisionedGrant.env_name``.
_GRANT_IDENTITY_ENV: Final = "PROBATION_RUNTIME_GRANT"
_LIVE_ENV: Final = "PROBATION_RUNTIME_LIVE"
_LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
#: Process exit statuses: 2 refuses an unprovisioned role, 3 records an allowed degraded start.
_EXIT_REFUSED: Final = 2
_EXIT_DEGRADED: Final = 3
_IPC_MAX_BYTES: Final = 65_536
_IPC_HEADER: Final = struct.Struct("!I")


class RuntimeRole(StrEnum):
    OBSERVATION = "observation"
    BRAIN = "brain"
    RESOLVER = "resolver"
    EXAMINER = "examiner"
    API = "api"
    WEBFACTS = "webfacts"
    EXECUTOR = "executor"


ENGINE_ROLES: Mapping[RuntimeRole, Role] = MappingProxyType(
    {
        role: Role.INGESTOR if role is RuntimeRole.OBSERVATION else Role(role.value)
        for role in RuntimeRole
    }
)

#: The only Google credential a role may ever hold; the engine roles hold none at all.
_CREDENTIAL_OVERRIDES: Mapping[RuntimeRole, CredentialRole] = {
    RuntimeRole.OBSERVATION: "read",
    RuntimeRole.EXECUTOR: "write",
}
CREDENTIAL_ROLES: Mapping[RuntimeRole, CredentialRole | None] = MappingProxyType(
    {role: _CREDENTIAL_OVERRIDES.get(role) for role in RuntimeRole}
)

#: Private-store authority is separate from the engine role and is never widened by it.
_CONNECTOR_AUTHORITIES: Mapping[RuntimeRole, tuple[ConnectorAuthority, ...]] = MappingProxyType(
    {
        RuntimeRole.OBSERVATION: ("ingestor", "read_worker"),
        # The command consumer needs administration; the effect path keeps executor only.
        RuntimeRole.EXECUTOR: ("executor", "administration"),
        RuntimeRole.API: ("api",),
    }
)


def _wait(stop: Event) -> int:
    stop.wait()
    return 0


#: The supervision-only surface of a spawned process; a test may inject any look-alike.
RoleProcess = subprocess.Popen[bytes]


@dataclass(frozen=True, slots=True)
class RoleContext:
    """One role's own connection, connector authorities, credential and entrypoint."""

    role: RuntimeRole
    connection: sqlite3.Connection
    connectors: tuple[ConnectorAccess, ...]
    grant: ProvisionedGrant | None
    provider: RoleCredentialProvider | None
    entrypoint: Entrypoint
    provisioning: RoleProvisioning
    coordinator: LifecycleCoordinator | None = None
    worker: GmailObservationWorker | None = None
    transport: GmailHttpTransport | None = None
    work: WorkLedger | None = None

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
        for connector in self.connectors:
            connector.conn.close()
        if self.coordinator is not None:
            for connection in self.coordinator.connections.all():
                connection.close()
        self.connection.close()


def grant_from_env(role: RuntimeRole, env: Mapping[str, str]) -> ProvisionedGrant | None:
    """The single grant this process was provisioned, or None. No secret is read here."""
    expected = CREDENTIAL_ROLES[role]
    parts = env.get(_GRANT_IDENTITY_ENV, "").split("|")
    if expected is None or len(parts) != 3:
        return None
    try:
        grant = ProvisionedGrant(expected, *parts)
    except ConnectorError:
        return None
    return grant if grant.env_name in env else None


def _grant_for(
    role: RuntimeRole,
    grants: Mapping[RuntimeRole, ProvisionedGrant] | None,
    env: Mapping[str, str],
) -> ProvisionedGrant | None:
    expected = CREDENTIAL_ROLES[role]
    if expected is None:
        return None  # a grant offered to an engine role is ignored, never installed
    grant = grants.get(role) if grants is not None else grant_from_env(role, env)
    if grant is not None and grant.role != expected:
        raise ConnectorError("grant_role_mismatch")
    return grant


def _gmail_api_ready(env: Mapping[str, str], private_store_path: Path) -> bool:
    store = env.get("PROBATION_GMAIL_STORE", "").strip()
    if not (
        env.get("PROBATION_GMAIL_OWNER_API_KEY", "").strip()
        and env.get("PROBATION_GMAIL_OWNER_ID", "").strip()
        and store
        and env.get("PROBATION_GMAIL_BIND_HOST", "127.0.0.1").strip() in _LOOPBACK_HOSTS
        and private_store_path.is_file()
    ):
        return False
    try:
        return Path(store).resolve() == private_store_path.resolve()
    except OSError:
        return False


def build_coordinator(
    *,
    db_path: Path | str,
    clock: Clock,
    steps: WorkerSteps,
    executor_connection: sqlite3.Connection | None = None,
) -> tuple[LifecycleCoordinator, RoleConnections]:
    """Compose the coordinator from four bound connections. No credential parameter exists."""
    executor = (
        executor_connection
        if executor_connection is not None
        else get_role_connection(db_path, Role.EXECUTOR)
    )
    connections = RoleConnections(
        resolver=get_role_connection(db_path, Role.RESOLVER),
        examiner=get_role_connection(db_path, Role.EXAMINER),
        executor=executor,
        brain=get_role_connection(db_path, Role.BRAIN),
    )
    return LifecycleCoordinator(connections, steps, clock=clock), connections


def _ingest_on_tick(ingest: GmailIngestBridge) -> Callable[[ObservationTickResult], None]:
    """Run the ingest bridge after each observation tick; the tick's own result is unused."""

    def on_tick(result: ObservationTickResult) -> None:
        del result
        ingest.run()

    return on_tick


def _forward_allowlist(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = env.get("PROBATION_GMAIL_FORWARD_ALLOWLIST", "")
    return tuple(dict.fromkeys(item.strip().lower() for item in raw.split(",") if item.strip()))


def build_role_context(
    role: RuntimeRole,
    *,
    db_path: Path | str,
    private_store_path: Path | str,
    env: Mapping[str, str],
    clock: Clock,
    grants: Mapping[RuntimeRole, ProvisionedGrant] | None = None,
    steps: WorkerSteps | None = None,
    observation: ObservationDeps | None = None,
    read_transport: ReadTransport | None = None,
    ipc_channel: ByteChannel | None = None,
    on_status: Callable[[TickResult], None] | None = None,
    live: bool = False,
    work: WorkLedger | None = None,
) -> RoleContext:
    """Open this role's own bound connection and expose the one entrypoint it may run."""
    if not isinstance(role, RuntimeRole):
        raise ConnectorError("unknown_runtime_role")
    ledger = WorkLedger() if work is None else work
    grant = _grant_for(role, grants, env)  # validated before any connection is opened
    live_transport: GmailHttpTransport | None = None
    provider: RoleCredentialProvider | None = None
    if live and grant is not None:
        live_transport = GmailHttpTransport()
        try:
            provider = build_live_provider(
                grant=grant, env=env, clock=clock, api_transport=live_transport
            )
        except Exception:
            live_transport.close()
            raise
    else:
        provider = (
            None
            if grant is None
            else RoleCredentialProvider(
                grant=grant, source=EnvCredentialSource(dict(env), grant), clock=clock
            )
        )
    authorities = _CONNECTOR_AUTHORITIES.get(role, ())
    if authorities:
        verify_and_migrate_store(Path(private_store_path))
    connection = get_role_connection(db_path, ENGINE_ROLES[role])
    connectors = tuple(
        ConnectorAccess(open_store(private_store_path), authority) for authority in authorities
    )
    coordinator: LifecycleCoordinator | None = None
    worker: GmailObservationWorker | None = None
    if role is RuntimeRole.OBSERVATION:
        ingest = (
            None
            if grant is None
            else GmailIngestBridge(
                access=connectors[0],
                engine=connection,
                clock=clock,
                connection_id=grant.connection_id,
                account_id=grant.account_id,
                payloads=GmailPayloadStore(
                    Path(private_store_path).parent / "payloads", grant.connection_id
                ),
            )
        )
        transport = live_transport if live_transport is not None else read_transport
        worker, provision = observation_worker(
            observation,
            grant=grant,
            connectors=connectors,
            provider=provider,
            transport=transport,
            connection=connection,
            clock=clock,
            on_tick=None if ingest is None else _ingest_on_tick(ingest),
        )
        provisioning = RoleProvisioning((provision,))
        entrypoint = _wait if worker is None else worker.run
    elif role is RuntimeRole.EXECUTOR:
        if steps is None:
            if live_transport is not None and grant is not None and provider is not None:
                allowlist = _forward_allowlist(env)
                payloads_path = Path(private_store_path).parent / "payloads"
                payloads = GmailPayloadStore(payloads_path, grant.connection_id)
                live_deps = LiveExecutorDeps(
                    transport=live_transport,
                    provider=provider,
                    payloads=payloads,
                    forward_allowlist=allowlist,
                )
                steps, provisions = (
                    executor_steps(connection, connectors, clock, live=live_deps),
                    EXECUTOR_LIVE_PROVISIONS,
                )
            else:
                steps, provisions = (
                    executor_steps(connection, connectors, clock),
                    EXECUTOR_PROVISIONS,
                )
        else:
            provisions = injected_provisions(steps)
        coordinator, _ = build_coordinator(
            db_path=db_path, clock=clock, steps=steps, executor_connection=connection
        )
        provisioning = RoleProvisioning(provisions)
        entrypoint = partial(coordinator.run, on_result=on_status or _ledger_tick(ledger))
    elif role is RuntimeRole.BRAIN:
        provisioning = RoleProvisioning(
            (
                StepProvisioning("gmail_verification", "provisioned"),
                # Follow-ups are wired through ``brain_followups.process_followups`` each tick.
                StepProvisioning("authority_followups", "provisioned"),
                StepProvisioning(
                    "webfacts_ipc",
                    "provisioned" if ipc_channel is not None else "not_provisioned",
                    None if ipc_channel is not None else "ipc_channel_absent",
                ),
            )
        )
        webfacts = None if ipc_channel is None else BrainWebFactsClient(ipc_channel)

        def entrypoint(stop: Event) -> int:
            return run_brain(
                connection,
                clock=clock,
                stop=stop,
                webfacts=webfacts,
                allow_live_llm=env.get(_LIVE_ENV) == "1",
                work=ledger,
            )
    elif role is RuntimeRole.RESOLVER:
        provisioning = RoleProvisioning((StepProvisioning("owner_responses", "provisioned"),))

        def entrypoint(stop: Event) -> int:
            return run_resolver(connection, clock=clock, stop=stop, work=ledger)
    elif role is RuntimeRole.EXAMINER:
        owner_id = env.get("PROBATION_GMAIL_OWNER_ID")
        replay = replay_controller_for_owner(connection, owner_id=owner_id)
        provisioning = RoleProvisioning((StepProvisioning("outcome_review", "provisioned"),))

        def entrypoint(stop: Event) -> int:
            return run_examiner(
                connection,
                clock=clock,
                stop=stop,
                replay_controller=replay,
                lock_path=Path(db_path).with_suffix(".replay.lock"),
                work=ledger,
            )
    elif role is RuntimeRole.WEBFACTS:
        if ipc_channel is None:
            provisioning = RoleProvisioning(
                (StepProvisioning("brain_ipc", "not_provisioned", "ipc_channel_absent"),)
            )
            entrypoint = _wait
        else:
            from probation.llm.feature_identity import semantic_feature_version

            allow_live = env.get(_LIVE_ENV) == "1"
            verifier = email_webfacts_verifier(
                connection,
                clock=clock,
                allow_live_llm=allow_live,
                allow_live_tavily=allow_live,
            )
            # The channel is staffed either way. Offline the role truthfully answers every request
            # with a restriction cap of zero, so no web fact can be claimed that was not fetched.
            provisioning = RoleProvisioning((StepProvisioning("brain_ipc", "provisioned"),))

            def entrypoint(stop: Event) -> int:
                return run_webfacts(
                    connection,
                    channel=ipc_channel,
                    clock=clock,
                    stop=stop,
                    semantic_identity=semantic_feature_version,
                    verify=verifier,
                    work=ledger,
                )
    elif role is RuntimeRole.API:
        api_ready = _gmail_api_ready(env, Path(private_store_path))
        provisioning = RoleProvisioning(
            (
                StepProvisioning("loopback_api", "provisioned"),
                StepProvisioning(
                    "owner_api",
                    "provisioned" if api_ready else "not_provisioned",
                    None if api_ready else "owner_api_config_incomplete",
                ),
            )
        )

        def entrypoint(stop: Event) -> int:
            del stop
            return run_api_server()
    else:
        provisioning, entrypoint = RoleProvisioning(), _wait
    return RoleContext(
        role=role,
        connection=connection,
        connectors=connectors,
        grant=grant,
        provider=provider,
        entrypoint=entrypoint,
        provisioning=provisioning,
        coordinator=coordinator,
        worker=worker,
        transport=live_transport,
        work=ledger,
    )


@dataclass(frozen=True, slots=True)
class RoleStatus:
    """Per-role outcome: ids, states and safe codes only, never content or secrets."""

    role: RuntimeRole
    state: RoleState
    capability: Capability
    capability_ready: bool
    detail: str | None = None


#: Roles that hold no Google capability of their own: their readiness is their work, not a grant.
WORK_DERIVED_ROLES: Final[frozenset[RuntimeRole]] = frozenset(
    {
        RuntimeRole.BRAIN,
        RuntimeRole.RESOLVER,
        RuntimeRole.EXAMINER,
        RuntimeRole.WEBFACTS,
    }
)


class RuntimeReport(dict[RuntimeRole, RoleStatus]):
    def status(self, role: RuntimeRole) -> RoleStatus:
        return self[role]


Launcher = Callable[[Sequence[str], Mapping[str, str]], RoleProcess]
Spawner = Callable[[RuntimeRole, Mapping[str, str]], RoleProcess]


def _ledger_tick(ledger: WorkLedger) -> Callable[[TickResult], None]:
    """Turn a lifecycle tick into the same proof of work the engine loops report."""

    def record(result: TickResult) -> None:
        stages = tuple(f"{name}:{count}" for name, count in sorted(result.counts.items()) if count)
        if result.errors:
            ledger.failure("lifecycle", result.as_of, result.errors[0])
            return
        if stages:
            ledger.success("lifecycle", result.as_of, stages)

    return record


def _pump_role_status(
    handle: RoleProcess,
    role_key: str,
    ledger: WorkLedger | None,
    drain: Callable[[str], None] | None = None,
) -> threading.Thread:
    """Drain one child's stderr: a status line updates supervision, anything else is passed on.

    Reading is not optional. An undrained pipe fills and blocks the child, so the supervisor
    consumes every byte and only interprets the lines it recognises.
    """

    def pump() -> None:
        try:
            stream = handle.stderr
            if stream is None:
                return
            while True:
                raw = stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").strip()
                entry = decode_work_status(line)
                if entry is not None:
                    if ledger is not None:
                        ledger.record(role_key, entry[1])
                elif drain is not None and line:
                    drain(line)
        except (OSError, ValueError, AttributeError, TypeError):
            # A handle without a readable pipe yields no evidence, so supervision reports the
            # role unavailable rather than crashing or assuming it worked.
            return
        try:
            stream.close()
        except OSError:
            pass

    thread = threading.Thread(target=pump, name="role-status-pump", daemon=True)
    thread.start()
    return thread


def _launch(command: Sequence[str], env: Mapping[str, str]) -> RoleProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    ipc = "--ipc-stdio" in command
    return subprocess.Popen(
        list(command),
        env=dict(env),
        creationflags=flags,
        stdin=subprocess.PIPE if ipc else None,
        stdout=subprocess.PIPE if ipc else None,
        stderr=subprocess.PIPE,
    )


def _relay_ipc(source: object, destination: object) -> None:
    """Forward validated length-framed bytes between Brain and Webfacts stdio pipes."""
    reader, writer = source, destination
    try:
        while True:
            header = reader.read(_IPC_HEADER.size)  # type: ignore[attr-defined]
            if len(header) != _IPC_HEADER.size:
                return
            size = _IPC_HEADER.unpack(header)[0]
            if not 0 < size <= _IPC_MAX_BYTES:
                return
            remaining, chunks = size, []
            while remaining:
                chunk = reader.read(remaining)  # type: ignore[attr-defined]
                if not chunk:
                    return
                chunks.append(chunk)
                remaining -= len(chunk)
            writer.write(header + b"".join(chunks))  # type: ignore[attr-defined]
            writer.flush()  # type: ignore[attr-defined]
    except (OSError, ValueError):
        return


def _start_ipc_bridge(handles: Mapping[RuntimeRole, RoleProcess]) -> None:
    brain, webfacts = handles.get(RuntimeRole.BRAIN), handles.get(RuntimeRole.WEBFACTS)
    if brain is None or webfacts is None:
        return
    streams = (
        getattr(brain, "stdin", None),
        getattr(brain, "stdout", None),
        getattr(webfacts, "stdin", None),
        getattr(webfacts, "stdout", None),
    )
    if any(stream is None for stream in streams):
        return
    for source, destination in (
        (brain.stdout, webfacts.stdin),
        (webfacts.stdout, brain.stdin),
    ):
        threading.Thread(
            target=_relay_ipc,
            args=(source, destination),
            daemon=True,
            name="d6-role-ipc-bridge",
        ).start()


def _shutdown(handle: RoleProcess, join_timeout: float) -> tuple[RoleState, str | None]:
    if handle.poll() is not None:
        code = handle.returncode
        return ("stopped", None) if code in (0, None) else ("failed", f"exit_code_{code}")
    handle.terminate()
    try:
        handle.wait(join_timeout)
    except subprocess.TimeoutExpired:
        handle.kill()
        try:
            handle.wait(join_timeout)
        except subprocess.TimeoutExpired:
            pass
    return "stopped", None


class GmailRuntime:
    """Supervise one process per role; hold no provider and never copy the parent env."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        private_store_path: Path | str,
        env: Mapping[str, str],
        clock: Clock,
        grants: Mapping[RuntimeRole, ProvisionedGrant] | None = None,
        spawn: Spawner | None = None,
        launcher: Launcher | None = None,
        work: WorkLedger | None = None,
        work_staleness_seconds: float = WORK_STALENESS_SECONDS,
    ) -> None:
        self.db_path, self.private_store_path = Path(db_path), Path(private_store_path)
        self.env, self.clock = dict(env), clock
        self._grants = None if grants is None else dict(grants)
        self._launcher = launcher or _launch
        self._spawn = spawn or self._default_spawn
        self._work = work
        self._work_window = work_staleness_seconds

    def command_for(self, role: RuntimeRole) -> list[str]:
        bootstrap = Path(__file__).with_name("bootstrap.py")
        module_args = ["--role", role.value]
        if self.env.get(_LIVE_ENV) == "1":
            module_args.append("--live")
        if role in {RuntimeRole.BRAIN, RuntimeRole.WEBFACTS}:
            module_args.append("--ipc-stdio")
        module_args.extend(
            ("--db", str(self.db_path), "--private-store", str(self.private_store_path))
        )
        return [
            sys.executable,
            str(bootstrap),
            "--role",
            role.value,
            "--db",
            str(self.db_path),
            "--module",
            "probation.workers.gmail_runtime",
            "--",
            *module_args,
        ]

    def _default_spawn(self, role: RuntimeRole, env: Mapping[str, str]) -> RoleProcess:
        return self._launcher(self.command_for(role), env)

    def _grant(self, role: RuntimeRole) -> ProvisionedGrant | None:
        if self._grants is None:
            return grant_from_env(role, self.env)
        return _grant_for(role, self._grants, self.env)

    def _child_env(self, role: RuntimeRole, grant: ProvisionedGrant | None) -> dict[str, str]:
        safe_config = {
            "DB_PATH",
            "CLOCK_MODE",
        }
        if role in {RuntimeRole.OBSERVATION, RuntimeRole.EXECUTOR}:
            safe_config.add(_LIVE_ENV)
        if role in {RuntimeRole.BRAIN, RuntimeRole.EXAMINER, RuntimeRole.WEBFACTS}:
            safe_config.update(
                {
                    "LLM_API_KEY",
                    "LLM_BASE_URL",
                    "LLM_TIMEOUT_S",
                    "LLM_MAX_RETRIES",
                    "LLM_MAX_CONCURRENCY",
                    "PRICE_TABLE_PATH",
                    "BUDGET_HARD_LIMIT_USD",
                    "MODEL_READER",
                    "MODEL_WRITER",
                    "MODEL_EXAM_EDITS",
                    "MODEL_WORDING",
                    "AUDIT_SEED",
                    "AUDIT_FRACTION",
                    "ATTENTION_COST",
                    _LIVE_ENV,
                }
            )
        if role is RuntimeRole.BRAIN:
            safe_config.update(
                {
                    "COLD_START_MIN_SITUATIONS",
                    "TRAIN_HALF_LIFE_DAYS",
                    "EMBEDDING_MODEL_DIR",
                    "EMBEDDING_MANIFEST_PATH",
                    "NOVELTY_K",
                    "NOVELTY_PCTL",
                }
            )
        if role is RuntimeRole.WEBFACTS:
            safe_config.update(
                {
                    "TAVILY_API_KEY",
                    "TAVILY_BASE_URL",
                    "TAVILY_MAX_CALLS_PER_DAY",
                    "TAVILY_MONTHLY_CREDIT_BUDGET",
                    "WEB_FACTS_TTL_POSITIVE_DAYS",
                    "WEB_FACTS_TTL_NEGATIVE_DAYS",
                    "USER_NAME_TOKENS",
                }
            )
        if role is RuntimeRole.EXAMINER:
            safe_config.add("PROBATION_GMAIL_OWNER_ID")
        if role is RuntimeRole.EXECUTOR:
            safe_config.add("PROBATION_GMAIL_FORWARD_ALLOWLIST")
        if role is RuntimeRole.API:
            safe_config.update(
                {
                    "PROBATION_GMAIL_OWNER_API_KEY",
                    "PROBATION_GMAIL_OWNER_ID",
                    "PROBATION_GMAIL_STORE",
                    "PROBATION_GMAIL_BIND_HOST",
                    "PROBATION_API_PORT",
                }
            )
        allowed = BASE_CHILD_ENV | safe_config
        child = {key: value for key, value in self.env.items() if key.upper() in allowed}
        if grant is not None:
            if grant.env_name not in self.env:
                return child
            child[grant.env_name] = self.env[grant.env_name]
            child[_GRANT_IDENTITY_ENV] = "|".join(
                (grant.connection_id, grant.account_id, grant.credential_ref)
            )
        return child

    def plan(self) -> dict[RuntimeRole, tuple[dict[str, str], Capability, bool]]:
        """Configuration readiness only: what a child could be given, never what it has done.

        Work-derived readiness is applied in :meth:`_status`, because a stage can only be proven
        by a role tick that already happened.
        """
        plans: dict[RuntimeRole, tuple[dict[str, str], Capability, bool]] = {}
        for role in RuntimeRole:
            grant = self._grant(role)
            child_env = self._child_env(role, grant)
            ready = (
                _gmail_api_ready(child_env, self.private_store_path)
                if role is RuntimeRole.API
                else CREDENTIAL_ROLES[role] is None
                or (grant is not None and grant.env_name in child_env)
            )
            plans[role] = (child_env, CREDENTIAL_ROLES[role] or "none", ready)
        return plans

    def _publish_readiness(
        self,
        plans: Mapping[RuntimeRole, tuple[Mapping[str, str], str, bool]],
        handles: Mapping[RuntimeRole, RoleProcess],
        failures: Mapping[RuntimeRole, str],
    ) -> bool:
        """Publish one readiness document beside the engine database for the API to read.

        Liveness comes from the child process, work evidence from the status lines that child
        reported. A role with no reported tick stays unready no matter how healthy its process
        looks, so supervision can never certify work it has not seen.
        """
        roles: dict[str, RoleReadiness] = {}
        for role, (_child_env, _credential, _ready) in plans.items():
            handle = handles.get(role)
            work_ready, work_code = self._work_state(role)
            if role in failures:
                state, process_live = "failed", False
            elif handle is None:
                state, process_live = "absent", False
            elif handle.poll() is None:
                state, process_live = "running", True
            else:
                state, process_live = "exited", False
            evidence = None if self._work is None else self._work.evidence(role.value)
            roles[role.value] = RoleReadiness(
                role=role.value,
                state=state if work_ready or not process_live else "degraded",
                ready=process_live and work_ready,
                code=failures.get(role) or work_code,
                last_tick_at=None if evidence is None else evidence.at,
            )
        return publish_runtime_status(
            runtime_status_path(self.db_path),
            generated_at=operational_clock().now_iso(),
            clock_mode=self.clock.mode.value,
            roles=roles,
        )

    def _work_state(self, role: RuntimeRole) -> tuple[bool, str | None]:
        """A role with no credential is ready only for as long as its own ticks stay fresh."""
        if role not in WORK_DERIVED_ROLES:
            return True, None
        if self._work is None:
            return False, "work_status_absent"
        state = self._work.state(role.value, self.clock.now_iso())
        return state.ready, state.code

    def run(
        self, stop: Event, *, join_timeout: float = 5.0, poll_seconds: float = 0.1
    ) -> RuntimeReport:
        """Start every role, wait for the stop event, then join or stop each process."""
        if join_timeout < 0 or poll_seconds <= 0:
            raise ValueError("invalid supervision interval")
        plans, handles, failures = self.plan(), {}, {}
        for role, (child_env, _, _) in plans.items():
            try:
                handle = self._spawn(role, child_env)
                handles[role] = handle
                _pump_role_status(handle, role.value, self._work)
            except (OSError, ConnectorError, ValueError) as exc:
                failures[role] = str(getattr(exc, "safe_code", type(exc).__name__))
        _start_ipc_bridge(handles)
        self._publish_readiness(plans, handles, failures)
        if handles:
            try:
                while not stop.is_set() and not all(h.poll() is not None for h in handles.values()):
                    stop.wait(poll_seconds)
                    self._publish_readiness(plans, handles, failures)
            except KeyboardInterrupt:
                stop.set()
        self._publish_readiness(plans, handles, failures)
        return RuntimeReport(
            {
                role: self._status(role, spec, handles.get(role), failures.get(role), join_timeout)
                for role, spec in plans.items()
            }
        )

    def _status(
        self,
        role: RuntimeRole,
        spec: tuple[dict[str, str], Capability, bool],
        handle: RoleProcess | None,
        failure: str | None,
        join_timeout: float,
    ) -> RoleStatus:
        _, capability, ready = spec
        work_ready, work_code = self._work_state(role)
        if failure is not None:
            return RoleStatus(role, "failed", capability, ready and work_ready, failure)
        if handle is None:
            return RoleStatus(role, "failed", capability, ready and work_ready, work_code)
        state, detail = _shutdown(handle, join_timeout)
        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(handle, name, None)
            if stream is not None:
                stream.close()
        if state == "stopped" and not ready:
            state = "degraded"
        elif state == "stopped" and work_code is not None:
            detail = detail or work_code
            if work_code.startswith("work_tick_failed"):
                # A failed tick this role reported is degraded, not a clean stop.
                state = "degraded"
        return RoleStatus(role, state, capability, ready and work_ready, detail)


def main(argv: Sequence[str] | None = None) -> int:
    """Run exactly one role. An unprovisioned role is refused unless ``--allow-degraded``."""
    parser = argparse.ArgumentParser(prog="probation.workers.gmail_runtime")
    parser.add_argument("--role", required=True, choices=[role.value for role in RuntimeRole])
    parser.add_argument("--db", required=True)
    parser.add_argument("--private-store", required=True)
    parser.add_argument("--ipc-stdio", action="store_true")
    parser.add_argument(
        "--live",
        action="store_true",
        help="run against the live Gmail API; requires PROBATION_RUNTIME_LIVE=1 in environment",
    )
    parser.add_argument(
        "--allow-degraded",
        action="store_true",
        help="start a role whose required worker steps are not provisioned (reported, never hidden)",
    )
    args = parser.parse_args(argv)
    role = RuntimeRole(args.role)
    private = Path(args.private_store).resolve()
    try:
        if args.live and os.environ.get(_LIVE_ENV) != "1":
            raise ConnectorError("live_runtime_unauthorized")
        if "private" not in {parent.name.lower() for parent in private.parents}:
            raise ConnectorError("private_store_path_required")
        if os.environ.get("PROBATION_RUNTIME_HOST", "127.0.0.1") not in _LOOPBACK_HOSTS:
            raise ConnectorError("loopback_host_required")
        db_path = Path(args.db)
        if not db_path.is_file():
            raise ConnectorError("engine_database_absent")
        probe = get_connection(db_path)
        schema_ok = has_schema(probe)
        probe.close()
        if not schema_ok:
            raise ConnectorError("engine_schema_absent")
        ipc_channel = None
        if args.ipc_stdio and role in {RuntimeRole.BRAIN, RuntimeRole.WEBFACTS}:
            ipc_channel = StdioChannel(sys.stdin.buffer, sys.stdout.buffer)
            # From here on the child's stdout carries length-framed IPC only. Every log line and
            # stray print is diverted to stderr so it can never corrupt a frame the peer reads.
            sys.stdout = sys.stderr
        work = WorkLedger(
            sink=lambda name, evidence: write_work_status(sys.stderr.buffer, name, evidence)
        )
        context = build_role_context(
            role,
            db_path=db_path,
            private_store_path=private,
            env=dict(os.environ),
            clock=Clock.live(),
            live=args.live,
            ipc_channel=ipc_channel,
            work=work,
        )
    except (ConnectorError, ValueError) as exc:
        print(f"runtime_refused: {getattr(exc, 'safe_code', exc)}", file=sys.stderr)
        return _EXIT_REFUSED
    blocked = context.provisioning.not_provisioned
    if blocked and not args.allow_degraded:
        print(f"runtime_refused: role_not_provisioned steps={','.join(blocked)}", file=sys.stderr)
        context.close()
        return _EXIT_REFUSED
    if blocked:
        print(f"runtime_degraded: role={role.value} steps={','.join(blocked)}", file=sys.stderr)
    stop = Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(number, lambda *_: stop.set())
        except (ValueError, OSError):
            pass  # not the main thread: the caller still owns the stop event
    try:
        context.entrypoint(stop)
    except ConnectorError as exc:
        print(f"runtime_role_failed: {exc.safe_code}", file=sys.stderr)
        return 1
    finally:
        context.close()
    return _EXIT_DEGRADED if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
