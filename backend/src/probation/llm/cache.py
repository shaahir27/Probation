"""Deterministic LLM response caching.

Authority: docs/CONTRACT.md invariant I-16 and docs/DATA_MODEL.md table llm_cache.

Two identities exist here and they are deliberately different sizes. `compute_cache_key` is the
contract's four-part outer key; `content_hash` is whatever the caller proves it sent, so a
production job must digest the whole semantic envelope (prompt text, model, provider, limits and
every version) or an old row silently answers a new question.
"""

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, cast

from probation.core.hashing import canonical_json, det_id
from probation.db.access import Role, RoleAccess
from probation.llm.budget import units_from_persisted

EXPOSURE_ID_PREFIX = "llm-exposure-v1"


class CacheProvenance(ValueError):
    """A cache row exists but its accounting pair does not vouch for it."""

    def __init__(self, cache_key: str) -> None:
        super().__init__("cached answer lacks its exposure provenance")
        self.cache_key = cache_key


@dataclass(frozen=True, slots=True)
class SemanticEnvelope:
    """The complete identity of one request: change any part of it and the answer is stale.

    A validated model output is cached against this digest and nothing else. Drafts restored for
    a human are separate rows in `proposals`; one can never be read as the other.
    """

    prompt_id: str
    prompt_version: str
    model_id: str
    provider: str
    purpose: str
    system: str
    user: str
    max_tokens: int
    temperature: float
    template_hash: str
    schema_fingerprint: str
    context_version: str
    validator_version: str

    def parts(self) -> dict[str, Any]:
        return asdict(self)

    def content_hash(self) -> str:
        return semantic_content_hash(self.parts())

    def cache_key(self) -> str:
        return compute_cache_key(
            self.content_hash(), self.prompt_id, self.prompt_version, self.model_id
        )


def semantic_content_hash(parts: Mapping[str, Any]) -> str:
    """Canonical digest of every semantic input part, so an absent field cannot be a free match."""
    return hashlib.sha256(canonical_json(dict(parts)).encode("utf-8")).hexdigest()


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


def get_cache_row(conn: sqlite3.Connection, cache_key: str) -> sqlite3.Row | None:
    """The stored row with its identity and accounting columns, or nothing."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cache_key, model_id, prompt_id, prompt_version, response_json,
               tokens_in, tokens_out, cost_usd
        FROM llm_cache WHERE cache_key = ?;
        """,
        (cache_key,),
    )
    return cast("sqlite3.Row | None", cursor.fetchone())


def get_exposure_row(conn: sqlite3.Connection, cache_key: str) -> sqlite3.Row | None:
    """The spend record written atomically with a cache row, if it is still there."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT model_id, tokens_in, tokens_out, cost_usd FROM exposure_log WHERE id = ?;",
        (det_id(EXPOSURE_ID_PREFIX, cache_key),),
    )
    return cast("sqlite3.Row | None", cursor.fetchone())


def usable_cached_answer(
    conn: sqlite3.Connection, envelope: SemanticEnvelope
) -> dict[str, Any] | None:
    """Return a cached answer only when its own row and its spend record both still agree.

    A row whose `exposure_log` pair is gone is a data-integrity finding, not free credit: the
    answer is refused rather than re-bought, and the caller decides what to report.
    """
    cache_key = envelope.cache_key()
    row = get_cache_row(conn, cache_key)
    if row is None:
        return None
    if (
        row["model_id"] != envelope.model_id
        or row["prompt_id"] != envelope.prompt_id
        or row["prompt_version"] != envelope.prompt_version
    ):
        return None
    exposure = get_exposure_row(conn, cache_key)
    if exposure is None or exposure["model_id"] != envelope.model_id:
        raise CacheProvenance(cache_key)
    for source in (row, exposure):
        for column in ("tokens_in", "tokens_out"):
            value = source[column]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CacheProvenance(cache_key)
        try:
            units_from_persisted(source["cost_usd"])
        except Exception:
            raise CacheProvenance(cache_key) from None
        if int(source["tokens_in"]) != int(row["tokens_in"]) or int(source["tokens_out"]) != int(
            row["tokens_out"]
        ):
            raise CacheProvenance(cache_key)
    data = json.loads(row["response_json"])
    if not isinstance(data, dict):
        raise CacheProvenance(cache_key)
    return cast("dict[str, Any]", data)


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
    # Cache values are validated data, not ledger material: keep their precision.
    response_json = json.dumps(response_data, sort_keys=True, ensure_ascii=False, allow_nan=False)
    access = RoleAccess(conn, Role(getattr(conn, "bound_role", None) or Role.BRAIN))
    access.execute_write(
        "llm_cache",
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
