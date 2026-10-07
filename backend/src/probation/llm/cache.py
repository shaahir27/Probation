"""Deterministic LLM response caching.

Authority: docs/CONTRACT.md invariant I-16 and docs/DATA_MODEL.md table llm_cache.
"""

import hashlib
import sqlite3
from typing import Any

from probation.core.hashing import canonical_json


def compute_cache_key(content_hash: str, prompt_id: str, prompt_version: str, model_id: str) -> str:
    """Compute deterministic cache key for an LLM request."""
    combined = f"{content_hash}|{prompt_id}|{prompt_version}|{model_id}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def get_cached_response(conn: sqlite3.Connection, cache_key: str) -> dict[str, Any] | None:
    """Retrieve cached response if present."""
    cursor = conn.cursor()
    cursor.execute("SELECT response_json FROM llm_cache WHERE cache_key = ?;", (cache_key,))
    row = cursor.fetchone()
    if row:
        import json

        return json.loads(row["response_json"])  # type: ignore[no-any-return]
    return None


def store_cached_response(
    conn: sqlite3.Connection,
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
) -> None:
    """Store deterministic response into llm_cache."""
    response_json = canonical_json(response_data)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO llm_cache (
            cache_key, kind, model_id, prompt_id, prompt_version,
            response_json, tokens_in, tokens_out, cost_usd, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            cache_key,
            kind,
            model_id,
            prompt_id,
            prompt_version,
            response_json,
            tokens_in,
            tokens_out,
            cost_usd,
            created_at,
        ),
    )
    conn.commit()
