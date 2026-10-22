"""LLM client interface for Nebius Token Factory with schema validation and budget guard.

Authority: docs/CONTRACT.md section 6, invariants I-1, I-3, I-14, I-15, I-16.
"""

import hashlib
import json
import logging
import sqlite3
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from probation.config import settings
from probation.core.clock import Clock, get_clock
from probation.core.hashing import canonical_json
from probation.db.inference import record_inference
from probation.llm.budget import BudgetGuard, calculate_cost
from probation.llm.cache import compute_cache_key, get_cached_response
from probation.llm.jobs import validate_job_output
from probation.llm.schema import UnsupportedSchema, compile_schema
from probation.llm.schema import validate_json_schema as validate_json_schema

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(Exception):
    """Raised when LLM output fails schema validation or repair."""

    pass


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Clean text and parse JSON, handling thought tags and markdown code blocks."""
    cleaned = text.strip()
    if "<thought>" in cleaned and "</thought>" in cleaned:
        cleaned = cleaned.split("</thought>", 1)[-1].strip()
    elif "<think>" in cleaned and "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[-1].strip()

    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        cleaned = cleaned[first_brace : last_brace + 1]

    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError(f"Parsed JSON must be an object/dict, got {type(parsed).__name__}")
    return parsed


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
        clock: Clock | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.budget_guard = budget_guard or BudgetGuard()
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.transport = transport
        self.clock = clock or get_clock()
        self._unsupported_structured_models: set[str] = set()

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
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        """Execute structured JSON inference with schema validation and fallback."""
        try:
            compile_schema(schema)
        except UnsupportedSchema as exc:
            raise LLMValidationError("Unsupported output schema") from exc
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
                valid, _ = validate_json_schema(cached, schema)
                if not valid or not validate_job_output(cached, prompt_id, prompt_version):
                    raise LLMValidationError("Cached output fails current schema validation")
                logger.debug("LLM cache hit for key %s", cache_key)
                return cached

        # Pre-call budget estimation
        estimated_cost = calculate_cost(model, 1000, max_tokens, self.budget_guard.price_table)
        self.budget_guard.check_and_reserve(estimated_cost)

        with self._get_http_client() as client:
            data: dict[str, Any] | None = None
            body: dict[str, Any] = {}
            last_content: str = ""

            # 1. Attempt JSON-schema structured output if model supports it
            if model not in self._unsupported_structured_models:
                structured_payload: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.0,
                    "max_tokens": max_tokens,
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
                if resp.status_code == 200:
                    body = resp.json()
                    choices = body.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        last_content = msg.get("content") or msg.get("reasoning_content") or ""
                        try:
                            candidate = extract_json_from_text(last_content)
                            is_valid, _ = validate_json_schema(candidate, schema)
                            if is_valid and validate_job_output(
                                candidate, prompt_id, prompt_version
                            ):
                                data = candidate
                        except Exception:
                            data = None
                else:
                    self._unsupported_structured_models.add(model)

            # 2. Fallback to JSON mode if structured output rejected or failed validation
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
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                }

                resp_fb = self._post_with_retries(client, "/chat/completions", fallback_payload)
                if resp_fb.status_code == 200:
                    body = resp_fb.json()
                    choices = body.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        last_content = msg.get("content") or msg.get("reasoning_content") or ""
                        try:
                            candidate = extract_json_from_text(last_content)
                            is_valid, _ = validate_json_schema(candidate, schema)
                            if is_valid and validate_job_output(
                                candidate, prompt_id, prompt_version
                            ):
                                data = candidate
                        except Exception:
                            data = None

                # 3. Exactly one repair retry
                if data is None:
                    repair_messages = [
                        {"role": "system", "content": fallback_system},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": last_content},
                        {
                            "role": "user",
                            "content": (
                                "The previous output was not valid JSON conforming to the schema. "
                                "Output valid JSON only with all required fields."
                            ),
                        },
                    ]
                    repair_payload = {
                        "model": model,
                        "messages": repair_messages,
                        "temperature": 0.0,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                    }
                    resp_rep = self._post_with_retries(client, "/chat/completions", repair_payload)
                    if resp_rep.status_code == 200:
                        body = resp_rep.json()
                        choices = body.get("choices", [])
                        if choices:
                            msg = choices[0].get("message", {})
                            rep_content = msg.get("content") or msg.get("reasoning_content") or ""
                            try:
                                candidate = extract_json_from_text(rep_content)
                                is_valid, err = validate_json_schema(candidate, schema)
                                if is_valid and validate_job_output(
                                    candidate, prompt_id, prompt_version
                                ):
                                    data = candidate
                                else:
                                    raise LLMValidationError(
                                        f"Repair retry failed schema validation: {err}"
                                    )
                            except Exception as err:
                                if isinstance(err, LLMValidationError):
                                    raise
                                raise LLMValidationError(
                                    f"Repair retry failed to parse JSON: {err}"
                                ) from err
                        else:
                            raise LLMValidationError("Repair retry returned empty choices")
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

            now_iso = self.clock.now_iso()

            if conn is not None:
                record_inference(
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
                    situation_id=situation_id,
                    redaction_counts=redaction_counts,
                )

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
            if cached is not None:
                if not isinstance(cached, dict) or set(cached) != {"text"}:
                    raise LLMValidationError("Invalid cached text shape")
                text = cached["text"]
                if not isinstance(text, str) or not text.strip():
                    raise LLMValidationError("Text output must be a nonempty string")
                return text

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
            try:
                text_result = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMValidationError("Invalid text response shape") from exc
            if not isinstance(text_result, str) or not text_result.strip():
                raise LLMValidationError("Text output must be a nonempty string")
            usage = body.get("usage", {})
            tokens_in = int(usage.get("prompt_tokens", 800))
            tokens_out = int(usage.get("completion_tokens", max_tokens))
            actual_cost = calculate_cost(
                model, tokens_in, tokens_out, self.budget_guard.price_table
            )
            self.budget_guard.record_spend(actual_cost)

            now_iso = self.clock.now_iso()

            if conn is not None:
                record_inference(
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
                    situation_id=situation_id,
                    redaction_counts=redaction_counts,
                )

            return text_result
