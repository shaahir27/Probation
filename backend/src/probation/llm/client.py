"""LLM client interface for Nebius Token Factory with schema validation and budget guard.

Authority: docs/CONTRACT.md section 6, invariants I-1, I-3, I-14, I-15, I-16.
"""

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.hashing import canonical_json
from probation.llm.budget import BudgetGuard, calculate_cost
from probation.llm.cache import compute_cache_key, get_cached_response, store_cached_response

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(Exception):
    """Raised when LLM output fails schema validation or repair."""

    pass


def validate_json_schema(data: Any, schema: dict[str, Any]) -> tuple[bool, str | None]:
    """Pure deterministic JSON schema validator for LLM output."""
    if not isinstance(schema, dict) or not schema:
        return True, None

    schema_type = schema.get("type")

    # Handle list of allowed types, e.g. ["string", "null"]
    if isinstance(schema_type, list):
        for t in schema_type:
            ok, _ = validate_json_schema(data, {"type": t})
            if ok:
                return True, None
        return False, f"Expected one of types {schema_type}, got {type(data).__name__}"

    if schema_type == "null":
        if data is None:
            return True, None
        return False, f"Expected null, got {type(data).__name__}"

    if schema_type == "boolean":
        if isinstance(data, bool):
            return True, None
        return False, f"Expected boolean, got {type(data).__name__}"

    if schema_type == "integer":
        if isinstance(data, int) and not isinstance(data, bool):
            if "minimum" in schema and data < int(schema["minimum"]):
                return False, f"Value {data} is less than minimum {schema['minimum']}"
            if "maximum" in schema and data > int(schema["maximum"]):
                return False, f"Value {data} is greater than maximum {schema['maximum']}"
            return True, None
        return False, f"Expected integer, got {type(data).__name__}"

    if schema_type == "number":
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return True, None
        return False, f"Expected number, got {type(data).__name__}"

    if schema_type == "string":
        if isinstance(data, str):
            if "enum" in schema and data not in schema["enum"]:
                return False, f"Value '{data}' not in enum {schema['enum']}"
            if "maxLength" in schema and len(data) > int(schema["maxLength"]):
                return False, f"Length {len(data)} exceeds maxLength {schema['maxLength']}"
            return True, None
        return False, f"Expected string, got {type(data).__name__}"

    if schema_type == "array":
        if isinstance(data, list):
            items_schema = schema.get("items")
            if isinstance(items_schema, dict):
                for idx, item in enumerate(data):
                    ok, err = validate_json_schema(item, items_schema)
                    if not ok:
                        return False, f"Item at index {idx} failed: {err}"
            return True, None
        return False, f"Expected array, got {type(data).__name__}"

    if schema_type == "object" or "properties" in schema:
        if not isinstance(data, dict):
            return False, f"Expected object, got {type(data).__name__}"

        required = schema.get("required", [])
        for req_field in required:
            if req_field not in data:
                return False, f"Missing required field: '{req_field}'"

        properties = schema.get("properties", {})
        additional_allowed = schema.get("additionalProperties", True)
        if additional_allowed is False:
            for k in data.keys():
                if k not in properties:
                    return False, f"Unexpected additional property: '{k}'"

        for k, prop_val in data.items():
            if k in properties:
                prop_schema = properties[k]
                ok, err = validate_json_schema(prop_val, prop_schema)
                if not ok:
                    return False, f"Property '{k}' invalid: {err}"

        return True, None

    return True, None


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.budget_guard = budget_guard or BudgetGuard()
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.transport = transport
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
                            if is_valid:
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
                            if is_valid:
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
                                if is_valid:
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

            clock_mode = ClockMode.REPLAY if settings.clock_mode == "replay" else ClockMode.LIVE
            now_iso = Clock(mode=clock_mode).now_iso()

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

            clock_mode = ClockMode.REPLAY if settings.clock_mode == "replay" else ClockMode.LIVE
            now_iso = Clock(mode=clock_mode).now_iso()

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
