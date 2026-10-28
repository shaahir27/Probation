"""Durable consumer for owner pause/resume/revoke intents on a Gmail connection.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5 and 7, and docs/OCT29_DEMO_BUILD_PLAN.md
10.1/12.1. D3 already records every owner command as an immutable ``command_requests`` intent;
this module is the designated consumer that moves ``gmail_connections.state`` in response. It
reads intents through the existing ``CommandStore`` (no second command path), holds the private
store's ``administration`` authority only, and imports no provider transport, credential source
or Gmail write adapter, so it is structurally unable to dispatch or retry a mail effect.

Rules enforced here:

* one immutable ``gmail_command_receipts`` row per ``(command_id, 'connector')``; a command that
  already has one is skipped, so a restart never re-applies or duplicates;
* the state change and its receipt commit in ONE ``ConnectorAccess.transaction()``;
* owner/account/scope mismatches and illegal transitions record a ``failed`` receipt with a safe
  code and change no state;
* ``applied_at`` and ``updated_at`` come from the injected Clock; the system clock is never read.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

from probation.connectors.acl import verify_owner_only
from probation.connectors.gmail_read_grant import (
    read_grant,
    token_path,
    token_root,
    write_grant,
)
from probation.connectors.types import ConnectorError
from probation.core.clock import Clock, parse_timestamp
from probation.core.lifecycle import CommandIntent
from probation.db.gmail_store import ConnectorAccess, StoreAccessError
from probation.db.lifecycle_commands import CommandStore

CommandType = Literal["pause", "resume", "revoke"]
OutcomeState = Literal["applied", "failed"]

#: The single receipt namespace this consumer may own; the DDL pins the same value.
CONSUMER: Final = "connector"
#: Receipt marker for a command whose connection does not exist. Never written to a connection.
ABSENT: Final = "UNKNOWN"
_MAX_BATCH: Final = 100

_SELECT_CANDIDATES = """SELECT id,type FROM command_requests
 WHERE type IN('pause','resume','revoke') AND created_at COLLATE UTC_TIMESTAMP <= ?
 ORDER BY created_at COLLATE UTC_TIMESTAMP,id"""

_SELECT_RECEIPT = "SELECT command_id FROM gmail_command_receipts WHERE command_id=? AND consumer=?"

_UPDATE_STATE = """UPDATE gmail_connections SET state=?,updated_at=?
 WHERE connection_id=? AND owner_id=? AND account_id=? AND state=?"""

_INSERT_RECEIPT = """INSERT INTO gmail_command_receipts
 (command_id,consumer,state,connection_id,applied_state,safe_code,applied_at)
 VALUES(?,?,?,?,?,?,?)"""


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """One command acted on. Safe to log: ids, state name and code only, never content."""

    command_id: str
    command_type: CommandType
    outcome: OutcomeState
    connection_id: str
    applied_state: str
    safe_code: str | None = None


@dataclass(frozen=True, slots=True)
class _Decision:
    """The state observed, the state to record and the refusal code, if any."""

    observed_state: str
    applied_state: str
    safe_code: str | None = None

    @property
    def refused(self) -> bool:
        return self.safe_code is not None


class GmailCommandConsumer:
    """Apply recorded owner intents to ``gmail_connections`` exactly once, atomically."""

    def __init__(
        self,
        *,
        commands: CommandStore,
        store: ConnectorAccess,
        clock: Clock,
        batch_size: int = 20,
    ) -> None:
        if store.authority != "administration":
            # Administration is the only private-store authority that may move connection state.
            raise ConnectorError("command_consumer_needs_administration")
        if not 1 <= batch_size <= _MAX_BATCH:
            raise ConnectorError("invalid_command_batch")
        self._commands = commands
        self._store = store
        self._clock = clock
        self._batch_size = batch_size

    def consume(self) -> tuple[CommandOutcome, ...]:
        """Apply at most ``batch_size`` unapplied intents visible to the injected clock.

        A single pass, oldest intent first. Applying at most ``batch_size`` per call keeps the
        effect budget bounded; every later call resumes with the remaining intents.
        """
        now = self._clock.now_iso()
        outcomes: list[CommandOutcome] = []
        for command_id, command_type in self._unapplied(now)[: self._batch_size]:
            outcome = self._apply(command_id, command_type, now)
            if outcome is not None:
                outcomes.append(outcome)
        return tuple(outcomes)

    def _unapplied(self, now: str) -> list[tuple[str, CommandType]]:
        """Intents already visible at ``now``, excluding anything already receipted.

        The receipt lives in the private store and the intent in the engine database, so the
        exclusion happens in Python after one read from each. Receipted commands are skipped,
        never re-applied; only the first ``batch_size`` survivors are acted on per call.
        """
        rows = self._commands.access.conn.execute(_SELECT_CANDIDATES, (now,)).fetchall()
        receipted = {
            str(row["command_id"])
            for row in self._store.query(
                "SELECT command_id FROM gmail_command_receipts WHERE consumer=?", (CONSUMER,)
            )
        }
        return [
            (str(row["id"]), cast(CommandType, str(row["type"])))
            for row in rows
            if str(row["id"]) not in receipted
        ]

    def _apply(self, command_id: str, command_type: CommandType, now: str) -> CommandOutcome | None:
        """One command, one transaction: state change and receipt commit together or not at all."""
        try:
            intent = self._commands.get(command_id)
        except ValueError:
            return self._finish(command_id, command_type, "", ABSENT, "invalid_command_scope", now)
        if intent is None:
            return None
        row = self._store.one(
            "SELECT state,authorized_at FROM gmail_connections WHERE connection_id=?",
            (intent.scope.connection_id,),
        )
        if (
            row is not None
            and row["authorized_at"] is not None
            and parse_timestamp(intent.created_at) < parse_timestamp(str(row["authorized_at"]))
        ):
            observed_state = str(row["state"])
            return self._finish(
                command_id,
                command_type,
                intent.scope.connection_id,
                observed_state,
                "superseded_by_reauthorization",
                now,
            )
        with self._store.transaction():
            if self._receipt(command_id) is not None:
                return None  # another consumer won the race after the candidate read
            decision = self._decide(intent)
            if decision.safe_code == "connection_unknown":
                # A command may legitimately precede its connection's registration. Leave it
                # pending with no receipt: a receipt would permanently skip it and silently drop
                # the owner's intent once the connection appears.
                return None
            if not decision.refused and decision.applied_state != decision.observed_state:
                changed = self._store.write(
                    "gmail_connections",
                    _UPDATE_STATE,
                    (
                        decision.applied_state,
                        now,
                        intent.scope.connection_id,
                        intent.owner_id,
                        intent.scope.account_id,
                        decision.observed_state,
                    ),
                )
                if changed != 1:
                    raise StoreAccessError("connection_state_changed_during_command")
            if decision.applied_state == "DISCONNECTED" and not decision.refused:
                # The state is the API-visible revocation; deleting both refresh tokens is the
                # credential-visible one. If deletion cannot be proven, the transaction rolls
                # back and the command stays pending rather than claiming a disconnect.
                self._revoke_tokens(
                    owner_id=intent.owner_id,
                    account_id=intent.scope.account_id,
                    connection_id=intent.scope.connection_id,
                )
            return self._finish(
                command_id,
                command_type,
                intent.scope.connection_id,
                decision.applied_state,
                decision.safe_code,
                now,
            )

    def _decide(self, intent: CommandIntent) -> _Decision:
        """Pure policy: no write happens until ownership, scope and transition are proven."""
        scope = intent.scope
        row = self._store.one(
            "SELECT owner_id,account_id,state FROM gmail_connections WHERE connection_id=?",
            (scope.connection_id,),
        )
        if row is None:
            return _Decision(ABSENT, ABSENT, "connection_unknown")
        state = str(row["state"])
        if str(row["owner_id"]) != intent.owner_id:
            return _Decision(state, state, "command_owner_mismatch")
        if str(row["account_id"]) != scope.account_id:
            return _Decision(state, state, "command_account_mismatch")
        if scope.resource_id is not None or scope.class_key is not None or scope.action is not None:
            # A resource- or action-scoped command must not move the whole connection.
            return _Decision(state, state, "command_scope_not_connection_wide")
        if intent.type == "pause":
            if state == "DISCONNECTED":
                return _Decision(state, state, "pause_from_disconnected")
            return _Decision(state, "PAUSED")
        if intent.type == "resume":
            if state != "PAUSED":
                return _Decision(state, state, "resume_requires_paused")
            return _Decision(state, "ACTIVE")
        # Revoke is the terminal kill switch: it is always safe to land on DISCONNECTED.
        return _Decision(state, "DISCONNECTED")

    def _revoke_tokens(self, *, owner_id: str, account_id: str, connection_id: str) -> None:
        row = self._store.one(
            "SELECT label_ids FROM gmail_connections WHERE connection_id=?", (connection_id,)
        )
        if row is None:
            return
        try:
            label = str(json.loads(str(row["label_ids"]))[0])
        except (TypeError, ValueError, IndexError, KeyError):
            return
        database = self._store.conn.execute("PRAGMA database_list").fetchone()
        if database is None or not database[2]:
            raise StoreAccessError("token_store_path_unavailable")
        store_path = Path(str(database[2]))
        for grant in (
            read_grant(owner_id, account_id, label),
            write_grant(owner_id, account_id, label),
        ):
            root = token_root(store_path, role=grant.role)
            if not root.exists():
                continue
            verify_owner_only(root)
            path = token_path(store_path, grant)
            if path.is_file():
                try:
                    path.unlink()
                except OSError as exc:
                    raise StoreAccessError("token_revocation_failed") from exc

    def _receipt(self, command_id: str) -> sqlite3.Row | None:
        return self._store.one(_SELECT_RECEIPT, (command_id, CONSUMER))

    def _finish(
        self,
        command_id: str,
        command_type: CommandType,
        connection_id: str,
        applied_state: str,
        safe_code: str | None,
        now: str,
    ) -> CommandOutcome:
        outcome: OutcomeState = "failed" if safe_code is not None else "applied"
        self._store.write(
            "gmail_command_receipts",
            _INSERT_RECEIPT,
            (command_id, CONSUMER, outcome, connection_id, applied_state, safe_code, now),
        )
        return CommandOutcome(
            command_id=command_id,
            command_type=command_type,
            outcome=outcome,
            connection_id=connection_id,
            applied_state=applied_state,
            safe_code=safe_code,
        )
