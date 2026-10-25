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
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from threading import Event
from types import MappingProxyType
from typing import Final, Literal

from probation.connectors.credentials import RoleCredentialProvider, build_child_env
from probation.connectors.credentials_state import (
    BASE_CHILD_ENV,
    EnvCredentialSource,
    ProvisionedGrant,
)
from probation.connectors.types import ConnectorError, CredentialRole
from probation.core.clock import Clock, get_clock
from probation.db.access import Role
from probation.db.connection import get_connection, get_role_connection, has_schema
from probation.db.gmail_store import ConnectorAccess, ConnectorAuthority, open_store
from probation.packs.mail.connectors.gmail_ingest import GmailIngestBridge
from probation.packs.mail.connectors.gmail_payloads import GmailPayloadStore
from probation.packs.mail.connectors.gmail_transport import GmailHttpTransport
from probation.workers.gmail_live import build_live_provider
from probation.workers.gmail_observation import (
    GmailObservationWorker,
    ObservationTickResult,
    ReadTransport,
)
from probation.workers.gmail_runtime_provisioning import (
    EXECUTOR_LIVE_PROVISIONS,
    EXECUTOR_PROVISIONS,
    LiveExecutorDeps,
    ObservationDeps,
    RoleProvisioning,
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


class RuntimeRole(StrEnum):
    OBSERVATION = "observation"
    BRAIN = "brain"
    RESOLVER = "resolver"
    EXAMINER = "examiner"
    API = "api"
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
    on_status: Callable[[TickResult], None] | None = None,
    live: bool = False,
) -> RoleContext:
    """Open this role's own bound connection and expose the one entrypoint it may run."""
    if not isinstance(role, RuntimeRole):
        raise ConnectorError("unknown_runtime_role")
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
        entrypoint = partial(coordinator.run, on_result=on_status)
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
    )


@dataclass(frozen=True, slots=True)
class RoleStatus:
    """Per-role outcome: ids, states and safe codes only, never content or secrets."""

    role: RuntimeRole
    state: RoleState
    capability: Capability
    capability_ready: bool
    detail: str | None = None


class RuntimeReport(dict[RuntimeRole, RoleStatus]):
    def status(self, role: RuntimeRole) -> RoleStatus:
        return self[role]


Launcher = Callable[[Sequence[str], Mapping[str, str]], RoleProcess]
Spawner = Callable[[RuntimeRole, Mapping[str, str]], RoleProcess]


def _launch(command: Sequence[str], env: Mapping[str, str]) -> RoleProcess:
    return subprocess.Popen(list(command), env=dict(env))


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
    ) -> None:
        self.db_path, self.private_store_path = Path(db_path), Path(private_store_path)
        self.env, self.clock = dict(env), clock
        self._grants = None if grants is None else dict(grants)
        self._launcher = launcher or _launch
        self._spawn = spawn or self._default_spawn

    def command_for(self, role: RuntimeRole) -> list[str]:
        head = [sys.executable, "-m", "probation.workers.gmail_runtime", "--role", role.value]
        if self.env.get(_LIVE_ENV) == "1":
            head.append("--live")
        return [*head, "--db", str(self.db_path), "--private-store", str(self.private_store_path)]

    def _default_spawn(self, role: RuntimeRole, env: Mapping[str, str]) -> RoleProcess:
        return self._launcher(self.command_for(role), env)

    def _grant(self, role: RuntimeRole) -> ProvisionedGrant | None:
        if self._grants is None:
            return grant_from_env(role, self.env)
        return _grant_for(role, self._grants, self.env)

    def _child_env(self, role: RuntimeRole, grant: ProvisionedGrant | None) -> dict[str, str]:
        extra = (
            (_GRANT_IDENTITY_ENV, _LIVE_ENV)
            if self.env.get(_LIVE_ENV) == "1"
            else (_GRANT_IDENTITY_ENV,)
        )
        if grant is not None:
            return build_child_env(self.env, grant, extra_allow=extra)
        child = {key: value for key, value in self.env.items() if key.upper() in BASE_CHILD_ENV}
        if self.env.get(_LIVE_ENV) == "1":
            child[_LIVE_ENV] = "1"
        return child

    def plan(self) -> dict[RuntimeRole, tuple[dict[str, str], Capability, bool]]:
        plans: dict[RuntimeRole, tuple[dict[str, str], Capability, bool]] = {}
        for role in RuntimeRole:
            grant = self._grant(role)
            child_env = self._child_env(role, grant)
            ready = CREDENTIAL_ROLES[role] is None or (
                grant is not None and grant.env_name in child_env
            )
            plans[role] = (child_env, CREDENTIAL_ROLES[role] or "none", ready)
        return plans

    def run(
        self, stop: Event, *, join_timeout: float = 5.0, poll_seconds: float = 0.1
    ) -> RuntimeReport:
        """Start every role, wait for the stop event, then join or stop each process."""
        if join_timeout < 0 or poll_seconds <= 0:
            raise ValueError("invalid supervision interval")
        plans, handles, failures = self.plan(), {}, {}
        for role, (child_env, _, _) in plans.items():
            try:
                handles[role] = self._spawn(role, child_env)
            except (OSError, ConnectorError, ValueError) as exc:
                failures[role] = str(getattr(exc, "safe_code", type(exc).__name__))
        if handles:
            while not stop.is_set() and not all(h.poll() is not None for h in handles.values()):
                stop.wait(poll_seconds)
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
        if failure is not None:
            return RoleStatus(role, "failed", capability, ready, failure)
        if handle is None:
            return RoleStatus(role, "failed", capability, ready)
        state, detail = _shutdown(handle, join_timeout)
        if state == "stopped" and not ready:
            state = "degraded"
        return RoleStatus(role, state, capability, ready, detail)


def main(argv: Sequence[str] | None = None) -> int:
    """Run exactly one role. An unprovisioned role is refused unless ``--allow-degraded``."""
    parser = argparse.ArgumentParser(prog="probation.workers.gmail_runtime")
    parser.add_argument("--role", required=True, choices=[role.value for role in RuntimeRole])
    parser.add_argument("--db", required=True)
    parser.add_argument("--private-store", required=True)
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
        context = build_role_context(
            role,
            db_path=db_path,
            private_store_path=private,
            env=dict(os.environ),
            clock=get_clock(),
            live=args.live,
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
