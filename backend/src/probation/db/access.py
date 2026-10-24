"""Per-process database write helpers enforcing access boundaries.

Authority: docs/CONTRACT.md section 3.
Only designated workers/modules may write to specific tables.
"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from probation.db.guards import AccessError as AccessError
from probation.db.guards import ReadConnection, ReadCursor, statement_guard

if TYPE_CHECKING:
    from probation.core.types import Situation


class Role(StrEnum):
    """Worker process roles."""

    INGESTOR = "ingestor"
    BRAIN = "brain"
    RESOLVER = "resolver"
    EXAMINER = "examiner"
    WEBFACTS = "webfacts"
    EXECUTOR = "executor"
    API = "api"


# `budget_scopes` is deliberately absent from every role: a cap is provisioned only by an
# operator-initiated administration step (W3-D03 section 4), and a worker that finds no row
# for its scope denies the call rather than pricing itself.
ROLE_ALLOWED_WRITE_TABLES: dict[Role, frozenset[str]] = {
    Role.INGESTOR: frozenset({"sources", "raw_items", "situations"}),
    Role.BRAIN: frozenset(
        {
            "situations",
            "features",
            "llm_cache",
            "proposals",
            "drafts",
            "exposure_log",
            "ledger",
            "llm_requests",
            "llm_attempts",
        }
    ),
    Role.RESOLVER: frozenset({"outcomes", "ledger", "outcome_events", "command_receipts"}),
    Role.EXAMINER: frozenset(
        {
            "licence_cache",
            "exam_runs",
            "exam_cases",
            "drift_state",
            "family_shift",
            "habits",
            "chains",
            "class_stats",
            "llm_cache",
            "exposure_log",
            "ledger",
            "admin_commands",
            "drift_receipts",
            "llm_requests",
            "llm_attempts",
            "command_receipts",
        }
    ),
    Role.WEBFACTS: frozenset(
        {
            "web_facts",
            "tavily_calls",
            "extractions",
            "quarantine_outputs",
            "llm_cache",
            "exposure_log",
            "ledger",
            "llm_requests",
            "llm_attempts",
        }
    ),
    Role.EXECUTOR: frozenset(
        {
            "actions",
            "outcomes",
            "ledger",
            "outcome_events",
            "command_receipts",
            "execution_attempts",
        }
    ),
    Role.API: frozenset({"user_responses", "admin_commands", "command_requests"}),
}


class RoleAccess:
    """Connection wrapper enforcing per-process write isolation."""

    def __init__(self, conn: sqlite3.Connection, role: Role) -> None:
        self._connection = conn
        self.role = role
        self.allowed_tables = ROLE_ALLOWED_WRITE_TABLES[role]
        bound_role = getattr(conn, "bound_role", None)
        if bound_role is not None and bound_role != role.value:
            raise AccessError("Cannot change the role of a dedicated connection")
        self._savepoint = 0

    @property
    def conn(self) -> ReadConnection:
        """Expose reads, never the underlying unrestricted connection."""
        return ReadConnection(self._connection)

    def verify_write(self, table: str) -> None:
        """Verify that current role has write permission for the target table."""
        if table not in self.allowed_tables:
            raise AccessError(
                f"Role '{self.role.value}' is prohibited from writing to table '{table}'. "
                f"Permitted tables: {sorted(self.allowed_tables)}"
            )

    def execute_write(self, table: str, query: str, params: tuple[Any, ...] = ()) -> ReadCursor:
        """Execute write query after permission verification."""
        if table in {
            "llm_requests",
            "llm_attempts",
            "outcome_events",
            "command_receipts",
            "execution_attempts",
            "command_requests",
        }:
            raise AccessError("Spend writes require the row-scoped SpendStore")
        if self.role == Role.BRAIN and table == "situations":
            raise AccessError("Brain situation writes require the typed chain repository")
        if self.role == Role.EXECUTOR and table == "outcomes":
            raise AccessError("Executor outcome writes require the typed undo repository")
        return self._execute_write(table, query, params)

    def _execute_write(self, table: str, query: str, params: tuple[Any, ...] = ()) -> ReadCursor:
        self.verify_write(table)
        cursor = self._connection.cursor()
        with statement_guard(
            self._connection, self.allowed_tables, target=table, role=self.role.value
        ):
            cursor.execute(query, params)
        return ReadCursor(self._connection, cursor)

    def executemany_write(
        self, table: str, query: str, seq_of_params: list[tuple[Any, ...]]
    ) -> ReadCursor:
        """Execute batch write query after permission verification."""
        if table in {
            "llm_requests",
            "llm_attempts",
            "outcome_events",
            "command_receipts",
            "execution_attempts",
            "command_requests",
        }:
            raise AccessError("Spend writes require the row-scoped SpendStore")
        if self.role == Role.BRAIN and table == "situations":
            raise AccessError("Brain situation writes require the typed chain repository")
        if self.role == Role.EXECUTOR and table == "outcomes":
            raise AccessError("Executor outcome writes require the typed undo repository")
        self.verify_write(table)
        cursor = self._connection.cursor()
        with statement_guard(
            self._connection, self.allowed_tables, target=table, role=self.role.value
        ):
            cursor.executemany(query, seq_of_params)
        return ReadCursor(self._connection, cursor)

    def insert_chain_situation(self, situation: "Situation") -> None:
        """The brain owns chain follow-up variants, never ordinary ingested rows."""
        if self.role != Role.BRAIN or (
            situation.pack != "chains"
            or situation.family != "chain_followup"
            or situation.variant not in {"REPLY", "BLOCK_TIME", "CREATE_TASK"}
        ):
            raise AccessError("Only a validated chain follow-up may be inserted by brain")
        self._execute_write(
            "situations",
            """INSERT INTO situations
            (id,pack,family,raw_item_id,occurred_at,sender_key,content_hash,redacted_text,
             hands_off_reason,variant,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                situation.id,
                situation.pack,
                situation.family,
                situation.raw_item_id,
                situation.occurred_at,
                situation.sender_key,
                situation.content_hash,
                situation.redacted_text,
                situation.hands_off_reason,
                situation.variant,
                situation.created_at,
            ),
        )

    def commit(self) -> None:
        """Commit transaction."""
        self._connection.commit()

    def store_undo_outcome(self, action_id: str, known_at: str, ledger_seq: int) -> None:
        """Executor may record only a correction for its actually undone action."""
        if self.role != Role.EXECUTOR:
            raise AccessError("Undo outcome storage requires Executor")
        row = self.conn.execute(
            """SELECT p.situation_id FROM actions a JOIN proposals p
            ON p.id=a.proposal_id WHERE a.id=? AND a.status='UNDONE'""",
            (action_id,),
        ).fetchone()
        if row is None:
            raise AccessError("Undo outcome requires an UNDONE action")
        self._execute_write(
            "outcomes",
            """INSERT OR REPLACE INTO outcomes
            (situation_id,observed_action,strength,source,observed_at,known_at,details_json,ledger_seq)
            VALUES (?,'UNDO','STRONG','undo',?,?,'{}',?)""",
            (row["situation_id"], known_at, known_at, ledger_seq),
        )

    def append_ledger(
        self, kind: str, ref_id: str, payload: dict[str, Any], created_at: str
    ) -> int:
        """Append through the same actual-target guard without exposing a raw writer."""
        from probation.db.ledger import append_ledger

        self.verify_write("ledger")
        with statement_guard(
            self._connection, self.allowed_tables, target="ledger", role=self.role.value
        ):
            return append_ledger(self._connection, kind, ref_id, payload, created_at)

    @contextmanager
    def transaction(self) -> Generator["RoleAccess"]:
        """Own an outer transaction or a nested savepoint, without committing its parent."""
        nested = self._connection.in_transaction
        self._savepoint += 1
        name = f"role_uow_{self._savepoint}"
        self._connection.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
        try:
            yield self
        except BaseException:
            if nested:
                self._connection.execute(f"ROLLBACK TO {name}")
                self._connection.execute(f"RELEASE {name}")
            else:
                self._connection.rollback()
            raise
        else:
            if nested:
                self._connection.execute(f"RELEASE {name}")
            else:
                self._connection.commit()


# Factory helpers
def get_role_access(conn: sqlite3.Connection, role: Role) -> RoleAccess:
    """Return access controller for the designated role."""
    return RoleAccess(conn, role)
