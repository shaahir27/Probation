"""Provisioning and worker composition for the local Gmail runtime.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5, 7 and 11 (row 31). This module owns the
two pieces of ``gmail_runtime`` that decide whether a role has real work behind it: private-store
verification/migration and the construction of the observation worker and executor steps. It
contains no supervisor, no spawn seam and no entrypoint policy; those stay in ``gmail_runtime``.

A stage this runtime cannot staff offline is reported as ``not_provisioned`` with a safe reason.
It is never represented by a zero count, because zero must mean "ran and processed nothing".
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from probation.connectors.acl import apply_owner_only, verify_owner_only
from probation.connectors.credentials import (
    MODIFY_SCOPE,
    SEND_SCOPE,
    RoleCredentialProvider,
)
from probation.connectors.credentials_state import ProvisionedGrant
from probation.connectors.grants import source_grant_for
from probation.connectors.types import (
    ConnectorError,
    HttpTransport,
    PayloadReader,
    SourceSelection,
)
from probation.core.clock import Clock
from probation.core.lifecycle import LifecycleError
from probation.db.access import Role, RoleAccess
from probation.db.gmail_store import (
    ConnectorAccess,
    migrate_store,
    open_store,
    store_is_current,
)
from probation.db.lifecycle_commands import CommandStore
from probation.packs.mail.connectors.capability import (
    CapabilityGate,
    build_write_manifest,
    persist_write_capabilities,
)
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_versions import InMemoryAnchorStore
from probation.packs.mail.connectors.gmail_write import GmailMailExecutionIO
from probation.workers.drift import review_outcome_events
from probation.workers.executor import Executor
from probation.workers.gmail_commands import GmailCommandConsumer
from probation.workers.gmail_observation import (
    GmailObservationWorker,
    ObservationTickResult,
    ReadTransport,
)
from probation.workers.lifecycle import Step, WorkerSteps
from probation.workers.response_resolver import resolve_responses
from probation.workers.restrictions import (
    ExecutionRestrictions,
    process_restriction_commands,
    restrictions_for,
)

ProvisionState = Literal["provisioned", "not_provisioned"]

#: The read worker needs no dependency the process cannot hold; only its transport is external.
ObservationDeps = tuple[str, str, ReadTransport, Callable[[str], ExecutionRestrictions]]

#: Fine-grained coordinator stages reported in provenance order.
STAGES: Final[tuple[str, ...]] = (
    "resolver",
    "examiner",
    "consume",
    "effects",
    "examiner_after",
    "followups",
)


@dataclass(frozen=True, slots=True)
class StepProvisioning:
    """Whether one stage has real work behind it, and why not when it has not."""

    stage: str
    status: ProvisionState
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RoleProvisioning:
    """Readiness derived from stages: any unprovisioned stage blocks it, zero counts do not."""

    steps: tuple[StepProvisioning, ...] = ()

    @property
    def ready(self) -> bool:
        return all(step.status == "provisioned" for step in self.steps)

    @property
    def not_provisioned(self) -> tuple[str, ...]:
        return tuple(step.stage for step in self.steps if step.status == "not_provisioned")

    def status_of(self, stage: str) -> ProvisionState | None:
        return next((step.status for step in self.steps if step.stage == stage), None)


def verify_and_migrate_store(path: Path) -> None:
    """Verify the owner-only store directory, then migrate the connector store if not current.

    A missing directory is created and sealed before anything is written into it; an existing
    directory is verified, never silently re-sealed, so an unexpected ACL denies startup rather
    than being repaired in place. Any ACL or migration failure is a typed denial for the caller.
    """
    directory = path.parent
    try:
        if not directory.exists():
            directory.mkdir(parents=True)
            apply_owner_only(directory, is_dir=True)
        verify_owner_only(directory)
    except (ConnectorError, OSError) as exc:
        raise ConnectorError("connector_store_acl_unverified") from exc
    try:
        conn = open_store(path)
        try:
            if not store_is_current(conn):
                migrate_store(conn)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise ConnectorError("connector_store_migration_failed") from exc


def _not_provisioned_step() -> Step:
    """A stage with no worker behind it fails with a typed code, never a silent zero."""

    def step(conn: sqlite3.Connection, as_of: str, limit: int) -> int:
        del conn, as_of, limit
        raise LifecycleError("not_provisioned")

    return step


def _restriction_gate(
    connection: sqlite3.Connection, owner: str, connection_id: str, account_id: str
) -> Callable[[str], ExecutionRestrictions]:
    """The read worker's only control path; any store doubt fails closed inside the gate."""

    def gate(as_of: str) -> ExecutionRestrictions:
        return restrictions_for(
            connection,
            owner_id=owner,
            connection_id=connection_id,
            account_id=account_id,
            resource_id="cohort",
            class_key=None,
            action="OBSERVE",
            as_of=as_of,
        )

    return gate


def observation_worker(
    deps: ObservationDeps | None,
    *,
    grant: ProvisionedGrant | None,
    connectors: tuple[ConnectorAccess, ...],
    provider: RoleCredentialProvider | None,
    transport: ReadTransport | None,
    connection: sqlite3.Connection,
    clock: Clock,
    on_tick: Callable[[ObservationTickResult], None] | None = None,
) -> tuple[GmailObservationWorker | None, StepProvisioning]:
    """Build the real observation worker from role-bound pieces; never duplicate its logic."""
    if deps is None:
        if grant is None or provider is None:
            return None, StepProvisioning("observation", "not_provisioned", "read_grant_absent")
        if transport is None:
            return None, StepProvisioning(
                "observation", "not_provisioned", "observation_transport_absent"
            )
        if len(connectors) != 2:
            return None, StepProvisioning(
                "observation", "not_provisioned", "observation_store_absent"
            )
        row = connectors[0].one(
            "SELECT owner_id,account_id FROM gmail_connections WHERE connection_id=?",
            (grant.connection_id,),
        )
        if row is None:
            return None, StepProvisioning(
                "observation", "not_provisioned", "connection_unregistered"
            )
        owner, account = str(row["owner_id"]), str(row["account_id"])
        if account != grant.account_id:
            raise ConnectorError("grant_account_mismatch")
        deps = (
            grant.connection_id,
            owner,
            transport,
            _restriction_gate(connection, owner, grant.connection_id, account),
        )
    if provider is None or len(connectors) != 2:
        return None, StepProvisioning("observation", "not_provisioned", "read_worker_inputs_absent")
    connection_id, owner, read_transport, restrictions = deps
    worker = GmailObservationWorker(
        connection_id=connection_id,
        owner=owner,
        ingest=connectors[0],
        capabilities=connectors[1],
        credentials=provider,
        transport=read_transport,
        clock=clock,
        restrictions=restrictions,
        on_tick=on_tick,
    )
    return worker, StepProvisioning("observation", "provisioned")


@dataclass(frozen=True, slots=True)
class LiveExecutorDeps:
    transport: HttpTransport
    provider: RoleCredentialProvider
    payloads: PayloadReader
    forward_allowlist: tuple[str, ...] = ()


def _live_effects(
    connection: sqlite3.Connection,
    connectors: tuple[ConnectorAccess, ...],
    clock: Clock,
    live: LiveExecutorDeps,
) -> Step:
    administration = next((item for item in connectors if item.authority == "administration"), None)
    executor_access = next((item for item in connectors if item.authority == "executor"), None)
    if administration is None or executor_access is None:
        raise ConnectorError("effects_need_executor_and_administration")
    rows = administration.query(
        "SELECT owner_id,connection_id,account_id,selection_revision,label_ids"
        " FROM gmail_connections"
    )
    if len(rows) != 1:
        raise ConnectorError("live_executor_requires_one_connection")
    row = rows[0]
    owner = str(row["owner_id"])
    connection_id = str(row["connection_id"])
    account_id = str(row["account_id"])
    label_ids = json.loads(str(row["label_ids"]))
    if (
        not isinstance(label_ids, list)
        or len(label_ids) != 1
        or not isinstance(label_ids[0], str)
        or not label_ids[0]
    ):
        raise ConnectorError("live_executor_requires_one_label")
    owner_label = label_ids[0]
    grant = source_grant_for(administration, owner, connection_id, account_id)
    if grant is None:
        raise ConnectorError("source_grant_unavailable")

    def token() -> str:
        return live.provider.resolve_access(
            "conditional_write", (MODIFY_SCOPE, SEND_SCOPE)
        ).reveal()

    read = GmailReadConnector(
        live.transport,
        connection_id=connection_id,
        account_id=account_id,
        access_token="",
        clock=clock,
        owner_label=owner_label,
        token_provider=token,
    )
    selection = SourceSelection(
        connection_id=connection_id,
        account_id=account_id,
        selection_revision=int(row["selection_revision"]),
        label_ids=(owner_label,),
    )
    read.enumerate_cohort(selection)
    manifest = build_write_manifest(read, granted_scopes=live.provider.granted_scopes())
    persist_write_capabilities(
        executor_access,
        connection_id=connection_id,
        account_id=account_id,
        manifest=manifest,
    )
    io = GmailMailExecutionIO(
        live.transport,
        read=read,
        connection_id=connection_id,
        account_id=account_id,
        write_token="",
        clock=clock,
        gate=CapabilityGate(manifest, allow_degraded_cas=True),
        store=executor_access,
        anchors=InMemoryAnchorStore(),
        payload_reader=live.payloads,
        token_provider=token,
    )
    executor = Executor(
        connection,
        world=cast(Any, io),
        clock=clock,
        grant_resolver=lambda binding: source_grant_for(
            administration, binding.owner_id, binding.connection_id, binding.account_id
        ),
        allowed_forward_recipients=live.forward_allowlist,
        worker_id="executor",
    )

    def effects(conn: sqlite3.Connection, as_of: str, limit: int) -> int:
        del conn
        consumed = executor.process_responses(as_of, limit)
        return consumed + len(executor.process_queue(as_of))

    return effects


def executor_steps(
    connection: sqlite3.Connection,
    connectors: tuple[ConnectorAccess, ...],
    clock: Clock,
    *,
    live: LiveExecutorDeps | None = None,
) -> WorkerSteps:
    """The real D3 steps plus the real command consumer; absent stages fail typed, not silently."""
    administration = next((item for item in connectors if item.authority == "administration"), None)
    if administration is None:
        raise ConnectorError("command_consumer_needs_administration")
    consumer = GmailCommandConsumer(
        commands=CommandStore(RoleAccess(connection, Role.EXECUTOR)),
        store=administration,
        clock=clock,
    )

    def consume(conn: sqlite3.Connection, as_of: str, limit: int) -> int:
        del conn, as_of, limit
        return len(consumer.consume())

    def examine(conn: sqlite3.Connection, as_of: str, limit: int) -> int:
        return review_outcome_events(conn, as_of=as_of) + process_restriction_commands(
            conn, as_of=as_of, limit=limit
        )

    return WorkerSteps(
        resolver=lambda conn, as_of, limit: resolve_responses(conn, as_of=as_of, limit=limit),
        examiner=examine,
        consume=consume,
        effects=_live_effects(connection, connectors, clock, live)
        if live is not None
        else _not_provisioned_step(),
        followups=_not_provisioned_step(),
    )


#: Stages this runtime can genuinely staff offline. The Gmail write path needs a live write
#: transport and an installed grant bundle; authority-lost follow-ups are Brain-owned work and are
#: never staffed by the executor coordinator, which holds no prediction snapshot.
EXECUTOR_PROVISIONS: Final[tuple[StepProvisioning, ...]] = (
    StepProvisioning("resolver", "provisioned"),
    StepProvisioning("examiner", "provisioned"),
    StepProvisioning("consume", "provisioned"),
    StepProvisioning("effects", "not_provisioned", "gmail_write_path_not_provisioned"),
    StepProvisioning("examiner_after", "provisioned"),
    StepProvisioning("followups", "not_provisioned", "followups_owned_by_brain_role"),
)

EXECUTOR_LIVE_PROVISIONS: Final[tuple[StepProvisioning, ...]] = (
    StepProvisioning("resolver", "provisioned"),
    StepProvisioning("examiner", "provisioned"),
    StepProvisioning("consume", "provisioned"),
    StepProvisioning("effects", "provisioned"),
    StepProvisioning("examiner_after", "provisioned"),
    StepProvisioning("followups", "not_provisioned", "followups_owned_by_brain_role"),
)


def injected_provisions(steps: WorkerSteps) -> tuple[StepProvisioning, ...]:
    """An explicit step set is provisioned by its owner; a missing followup stage still is not."""
    provisions = [
        StepProvisioning(stage, "provisioned")
        for stage in STAGES
        if not (stage == "followups" and steps.followups is None)
    ]
    if steps.followups is None:
        provisions.append(StepProvisioning("followups", "not_provisioned", "followup_step_absent"))
    return tuple(provisions)
