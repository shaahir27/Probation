"""Per-process database write helpers enforcing access boundaries.

Authority: docs/CONTRACT.md section 3.
Only designated workers/modules may write to specific tables.
"""

import sqlite3
from enum import StrEnum
from typing import Any


class AccessError(Exception):
    """Raised when an unauthorized component attempts to write to a restricted table."""

    pass


class Role(StrEnum):
    """Worker process roles."""

    INGESTOR = "ingestor"
    BRAIN = "brain"
    RESOLVER = "resolver"
    EXAMINER = "examiner"
    WEBFACTS = "webfacts"
    EXECUTOR = "executor"
    API = "api"


ROLE_ALLOWED_WRITE_TABLES: dict[Role, frozenset[str]] = {
    Role.INGESTOR: frozenset({"sources", "raw_items", "situations"}),
    Role.BRAIN: frozenset(
        {"situations", "features", "llm_cache", "proposals", "drafts", "exposure_log", "ledger"}
    ),
    Role.RESOLVER: frozenset({"outcomes", "ledger"}),
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
        }
    ),
    Role.EXECUTOR: frozenset({"actions", "outcomes", "ledger"}),
    Role.API: frozenset({"user_responses"}),
}


class RoleAccess:
    """Connection wrapper enforcing per-process write isolation."""

    def __init__(self, conn: sqlite3.Connection, role: Role) -> None:
        self.conn = conn
        self.role = role
        self.allowed_tables = ROLE_ALLOWED_WRITE_TABLES[role]

    def verify_write(self, table: str) -> None:
        """Verify that current role has write permission for the target table."""
        if table not in self.allowed_tables:
            raise AccessError(
                f"Role '{self.role.value}' is prohibited from writing to table '{table}'. "
                f"Permitted tables: {sorted(self.allowed_tables)}"
            )

    def execute_write(self, table: str, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute write query after permission verification."""
        self.verify_write(table)
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor

    def executemany_write(
        self, table: str, query: str, seq_of_params: list[tuple[Any, ...]]
    ) -> sqlite3.Cursor:
        """Execute batch write query after permission verification."""
        self.verify_write(table)
        cursor = self.conn.cursor()
        cursor.executemany(query, seq_of_params)
        return cursor

    def commit(self) -> None:
        """Commit transaction."""
        self.conn.commit()


# Factory helpers
def get_role_access(conn: sqlite3.Connection, role: Role) -> RoleAccess:
    """Return access controller for the designated role."""
    return RoleAccess(conn, role)
