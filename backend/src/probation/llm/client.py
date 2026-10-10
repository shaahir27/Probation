"""LLM client interface for Nebius Token Factory with schema validation and budget guard.

Authority: docs/CONTRACT.md section 6, invariants I-1, I-3, I-14, I-15, I-16.
"""

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from probation.config import settings
from probation.core.hashing import canonical_json
from probation.llm.budget import BudgetGuard, calculate_cost
from probation.llm.cache import compute_cache_key, get_cached_response, store_cached_response

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(Exception):
    """Raised when LLM output fails schema validation or repair."""

    pass


class LLMClient:
    """Client for Nebius Token Factory inference with budget guard, retries, and schema fallback."""

    def __init__(
        self,
        base_url: str = settings.llm_base_url,
        api_key: str = settings.llm_api_key,
        budget_guard: BudgetGuard | None = None,
        timeout_s: float = float(settings.llm_timeout_s),
        max_retries: int = settings.llm_max_retries,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.budget_guard = budget_guard or BudgetGuard()
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.transport = transport

    def _get_http_client(self) -> httpx.Client:
        """Create an HTTP client with authorization headers."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_s,
            transport=self.transport,
        )

    def _post_with_retries(
        self, client: httpx.Client, endpoint: str, payload: dict[str, Any]
    ) -> httpx.Response:
        """Execute POST request with exponential backoff and Retry-After support."""
        attempt = 0
        backoff = 0.5

        while True:
            attempt += 1
            try:
                response = client.post(endpoint, json=payload)
                if (
                    response.status_code in (429, 500, 502, 503, 504)
                    and attempt <= self.max_retries
                ):
                    retry_after = response.headers.get("Retry-After")
                    sleep_time = (
                        float(retry_after)
                        if retry_after and retry_after.replace(".", "", 1).isdigit()
                        else backoff
                    )
                    logger.warning(
                        "LLM call received status %d on attempt %d. Backing off for %.2fs.",
                        response.status_code,
                        attempt,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                    backoff *= 2.0
                    continue
                return response
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                if attempt <= self.max_retries:
                    logger.warning(
                        "LLM connection error on attempt %d: %s. Backing off.", attempt, exc
                    )
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise

    def chat_json(
        self,
        *,
        kind: str,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        cache_parts: dict[str, str],
        conn: sqlite3.Connection | None = None,
        situation_id: str | None = None,
        redaction_counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Execute structured JSON inference with schema validation and fallback."""
        content_hash = cache_parts.get(
            "content_hash", hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]
        )
        prompt_id = cache_parts.get("prompt_id", "prompt")
        prompt_version = cache_parts.get("prompt_version", "v1")
        cache_key = compute_cache_key(content_hash, prompt_id, prompt_version, model)

        # Check deterministic cache
        if conn is not None:
            cached = get_cached_response(conn, cache_key)
            if cached is not None:
                logger.debug("LLM cache hit for key %s", cache_key)
                return cached

        # Pre-call budget estimation (assuming approx 1,000 prompt tokens and 300 output tokens)
        estimated_cost = calculate_cost(model, 1000, 300, self.budget_guard.price_table)
        self.budget_guard.check_and_reserve(estimated_cost)

        with self._get_http_client() as client:
            # 1. Attempt JSON-schema structured output
            structured_payload: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "strict": True,
                        "schema": schema,
                    },
                },
            }

            resp = self._post_with_retries(client, "/chat/completions", structured_payload)
            data: dict[str, Any] | None = None

            if resp.status_code == 200:
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                try:
                    data = json.loads(content)
                except Exception:
                    data = None

            # 2. Fallback to JSON mode if structured output rejected or failed
            if data is None:
                logger.info("JSON-schema rejected or unparseable. Falling back to JSON-only mode.")
                fallback_system = (
                    f"{system}\nYou MUST return a JSON object adhering strictly to this schema: "
                    f"{canonical_json(schema)}"
                )
                fallback_payload: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": fallback_system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                }

                resp_fb = self._post_with_retries(client, "/chat/completions", fallback_payload)
                if resp_fb.status_code == 200:
                    body = resp_fb.json()
                    content = body["choices"][0]["message"]["content"]
                    try:
                        data = json.loads(content)
                    except Exception:
                        data = None

                # 3. Exactly one repair retry
                if data is None:
                    repair_messages = [
                        {"role": "system", "content": fallback_system},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": content if "content" in locals() else ""},
                        {
                            "role": "user",
                            "content": "The previous output was not valid JSON conforming to the schema. Output valid JSON only.",
                        },
                    ]
                    repair_payload = {
                        "model": model,
                        "messages": repair_messages,
                        "temperature": 0.0,
                        "response_format": {"type": "json_object"},
                    }
                    resp_rep = self._post_with_retries(client, "/chat/completions", repair_payload)
                    if resp_rep.status_code == 200:
                        rep_content = resp_rep.json()["choices"][0]["message"]["content"]
                        try:
                            data = json.loads(rep_content)
                        except Exception as err:
                            raise LLMValidationError(
                                f"Repair retry failed to parse JSON: {err}"
                            ) from err
                    else:
                        raise LLMValidationError(
                            f"Repair retry failed with status {resp_rep.status_code}"
                        )

            if data is None:
                raise LLMValidationError(
                    "Failed to obtain valid JSON schema response from LLM endpoint."
                )

            # Record usage and cost
            usage = body.get("usage", {})
            tokens_in = int(usage.get("prompt_tokens", 800))
            tokens_out = int(usage.get("completion_tokens", 150))
            actual_cost = calculate_cost(
                model, tokens_in, tokens_out, self.budget_guard.price_table
            )
            self.budget_guard.record_spend(actual_cost)

            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Write cache and exposure log if DB connection provided
            if conn is not None:
                store_cached_response(
                    conn,
                    cache_key=cache_key,
                    kind=kind,
                    model_id=model,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    response_data=data,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=actual_cost,
                    created_at=now_iso,
                )

                # Exposure log write
                call_id = str(uuid.uuid4())[:32]
                counts_json = canonical_json(redaction_counts or {})
                conn.execute(
                    """
                    INSERT INTO exposure_log (
                        id, situation_id, call_kind, model_id, tokens_in, tokens_out,
                        redaction_counts_json, cost_usd, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        call_id,
                        situation_id,
                        kind,
                        model,
                        tokens_in,
                        tokens_out,
                        counts_json,
                        actual_cost,
                        now_iso,
                    ),
                )
                conn.commit()

            return data

    def chat_text(
        self,
        *,
        kind: str,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 400,
        cache_parts: dict[str, str],
        conn: sqlite3.Connection | None = None,
        situation_id: str | None = None,
        redaction_counts: dict[str, int] | None = None,
    ) -> str:
        """Execute text generation (for drafts or wording) with budget and caching."""
        content_hash = cache_parts.get(
            "content_hash", hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]
        )
        prompt_id = cache_parts.get("prompt_id", "prompt")
        prompt_version = cache_parts.get("prompt_version", "v1")
        cache_key = compute_cache_key(content_hash, prompt_id, prompt_version, model)

        if conn is not None:
            cached = get_cached_response(conn, cache_key)
            if cached is not None and "text" in cached:
                return str(cached["text"])

        estimated_cost = calculate_cost(model, 1000, max_tokens, self.budget_guard.price_table)
        self.budget_guard.check_and_reserve(estimated_cost)

        with self._get_http_client() as client:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
                "max_tokens": max_tokens,
            }
            resp = self._post_with_retries(client, "/chat/completions", payload)
            if resp.status_code != 200:
                raise LLMValidationError(
                    f"LLM text completion failed with status {resp.status_code}"
                )

            body = resp.json()
            text_result = str(body["choices"][0]["message"]["content"])
            usage = body.get("usage", {})
            tokens_in = int(usage.get("prompt_tokens", 800))
            tokens_out = int(usage.get("completion_tokens", max_tokens))
            actual_cost = calculate_cost(
                model, tokens_in, tokens_out, self.budget_guard.price_table
            )
            self.budget_guard.record_spend(actual_cost)

            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

            if conn is not None:
                store_cached_response(
                    conn,
                    cache_key=cache_key,
                    kind=kind,
                    model_id=model,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    response_data={"text": text_result},
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=actual_cost,
                    created_at=now_iso,
                )
                call_id = str(uuid.uuid4())[:32]
                counts_json = canonical_json(redaction_counts or {})
                conn.execute(
                    """
                    INSERT INTO exposure_log (
                        id, situation_id, call_kind, model_id, tokens_in, tokens_out,
                        redaction_counts_json, cost_usd, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        call_id,
                        situation_id,
                        kind,
                        model,
                        tokens_in,
                        tokens_out,
                        counts_json,
                        actual_cost,
                        now_iso,
                    ),
                )
                conn.commit()

            return text_result
