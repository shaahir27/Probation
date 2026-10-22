"""Caller-owned atomic cache/exposure recording after inference has completed."""

import sqlite3
from typing import Any

from probation.core.hashing import canonical_json, det_id
from probation.db.access import Role, RoleAccess
from probation.llm.cache import store_cached_response


def record_inference(
    conn: sqlite3.Connection,
    *,
    cache_key: str,
    kind: str,
    model_id: str,
    prompt_id: str,
    prompt_version: str,
    response_data: dict[str, Any],
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    created_at: str,
    situation_id: str | None,
    redaction_counts: dict[str, int] | None,
) -> None:
    """A failed exposure insert must not leave a usable, unaccounted cache entry.

    A savepoint rolls back this pair without committing the caller's transaction.
    There is no network operation inside the savepoint. Failed HTTP-attempt and
    concurrent reservation accounting are separate WP3 work.
    """
    role = Role(getattr(conn, "bound_role", None) or Role.BRAIN)
    access = RoleAccess(conn, role)
    # Keep even the outermost transaction caller-owned (like append_ledger).
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    with access.transaction():
        store_cached_response(
            conn,
            cache_key,
            kind,
            model_id,
            prompt_id,
            prompt_version,
            response_data,
            tokens_in,
            tokens_out,
            cost_usd,
            created_at,
        )
        access.execute_write(
            "exposure_log",
            """INSERT INTO exposure_log
            (id, situation_id, call_kind, model_id, tokens_in, tokens_out,
             redaction_counts_json, cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                det_id("llm-exposure-v1", cache_key),
                situation_id,
                kind,
                model_id,
                tokens_in,
                tokens_out,
                canonical_json(redaction_counts or {}),
                cost_usd,
                created_at,
            ),
        )
