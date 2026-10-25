"""Examiner-owned control consumption and read-only current execution restrictions."""

import json
import sqlite3
from dataclasses import dataclass

from probation.core.clock import format_timestamp
from probation.core.history import HistoryView
from probation.core.lifecycle import ApprovalBinding, CommandScope, LifecycleError
from probation.db.access import Role, RoleAccess
from probation.db.guards import ReadConnection
from probation.db.lifecycle_commands import CommandStore
from probation.db.lifecycle_receipts import ReceiptStore


@dataclass(frozen=True, slots=True)
class ExecutionRestrictions:
    revision: str = "0"
    paused: bool = False
    revoked: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.paused or self.revoked


def restrictions_for(
    conn: sqlite3.Connection | ReadConnection,
    *,
    owner_id: str,
    connection_id: str,
    account_id: str,
    resource_id: str,
    class_key: str | None,
    action: str,
    as_of: str,
) -> ExecutionRestrictions:
    paused, revoked, revision = False, False, "0"
    paused_scopes: set[tuple[str | None, ...]] = set()
    pending_pause = False
    reasons: list[str] = []
    try:
        if not all((owner_id, connection_id, account_id, resource_id, action)):
            raise ValueError("missing_execution_scope")
        for record in HistoryView(conn, as_of).control_records():
            scope = CommandScope.model_validate(json.loads(record["scope_json"]))
            if (
                record["owner_id"] != owner_id
                or scope.connection_id != connection_id
                or scope.account_id != account_id
                or scope.resource_id not in {None, resource_id}
                or scope.action not in {None, action}
                or (class_key is not None and scope.class_key not in {None, class_key})
            ):
                continue
            completed = record["receipt_state"] == "succeeded"
            kind = record["type"]
            scope_key = (
                scope.connection_id,
                scope.account_id,
                scope.resource_id,
                scope.class_key,
                scope.action,
            )
            if completed:
                revision = str(record["id"])
                if kind == "pause":
                    paused_scopes.add(scope_key)
                elif kind == "revoke":
                    revoked = True
                elif kind == "resume":
                    paused_scopes.discard(scope_key)
            elif kind in {"pause", "revoke"}:
                if kind == "pause":
                    pending_pause = True
                else:
                    revoked = True
                reasons.append(f"pending_{kind}")
        paused = pending_pause or bool(paused_scopes)
        return ExecutionRestrictions(revision, paused, revoked, tuple(reasons))
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return ExecutionRestrictions("unavailable", True, True, ("restriction_store_unavailable",))


def current_restrictions(
    conn: sqlite3.Connection | ReadConnection,
    binding: ApprovalBinding,
    as_of: str,
    *,
    class_key: str | None = None,
) -> ExecutionRestrictions:
    return restrictions_for(
        conn,
        owner_id=binding.owner_id,
        connection_id=binding.connection_id,
        account_id=binding.account_id,
        resource_id=binding.resource_id,
        class_key=class_key,
        action=binding.action,
        as_of=as_of,
    )


def current_web_cap(conn: sqlite3.Connection, proposal_id: str, as_of: str) -> int:
    """Re-read current entity restrictions before autonomous effect; no provider calls."""
    from probation.web.derive import extract_email_domains
    from probation.web.view import WebFactsView

    history = HistoryView(conn, as_of)
    record = history.get_execution_features(proposal_id)
    if record is None:
        return 3
    raw = history.get_raw_item(str(record["raw_item_id"]))
    if raw is None:
        return 3
    try:
        payload = json.loads(raw["payload_json"])
        sender, links = extract_email_domains(record.get("sender_key"), payload)
        domains = [sender, *links]
        facts = [WebFactsView(conn).get_entity_facts(value, as_of) for value in domains]
        return min((fact.web_cap for fact in facts if fact is not None), default=3)
    except (sqlite3.Error, ValueError, TypeError):
        return 3


def process_restriction_commands(conn: sqlite3.Connection, *, as_of: str, limit: int = 100) -> int:
    if conn.in_transaction:
        raise ValueError("Control consumption requires committed intents")
    now = format_timestamp(as_of)
    access = RoleAccess(conn, Role.EXAMINER)
    commands, receipts = CommandStore(access), ReceiptStore(access)
    consumed = 0
    for command in commands.pending(now, limit=limit):
        with access.transaction():
            claim = receipts.claim_command(
                command.request_id, now=now, owner="examiner-controls-v1"
            )
            if claim is None:
                continue
            try:
                CommandScope.model_validate(command.scope.model_dump())
                receipts.finish(
                    claim,
                    now=now,
                    status="succeeded",
                    result={"kind": command.type, "revision": command.request_id},
                )
            except LifecycleError as exc:
                receipts.finish(claim, now=now, status="failed", safe_code=exc.code)
            consumed += 1
    return consumed
