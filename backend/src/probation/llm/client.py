"""LLM client interface for Nebius Token Factory with schema validation and budget guard.

Authority: docs/CONTRACT.md section 6, invariants I-1, I-3, I-14, I-15, I-16.
"""

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from probation.config import settings
from probation.core.clock import Clock, get_clock
from probation.core.hashing import canonical_json
from probation.db.inference import record_inference
from probation.llm.budget import (
    BudgetGuard,
    cost_units,
    input_token_bound,
    rates_for,
    units_to_usd,
)
from probation.llm.cache import compute_cache_key, get_cached_response
from probation.llm.jobs import validate_job_output
from probation.llm.schema import UnsupportedSchema, compile_schema
from probation.llm.schema import validate_json_schema as validate_json_schema

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(Exception):
    """Raised when LLM output fails schema validation or repair."""

    pass


@dataclass(frozen=True, slots=True)
class AttemptAccounting:
    """What one physical request cost, and how much of that is the provider's own count."""

    tokens_in: int
    tokens_out: int
    charge_units: int
    usage_provenance: str


def _reported_usage(response: httpx.Response) -> tuple[int, int] | None:
    """The provider's token counts, or None when it did not report them useably."""
    try:
        usage = response.json().get("usage")
    except Exception:
        return None
    if not isinstance(usage, dict):
        return None
    counts: list[int] = []
    for key in ("prompt_tokens", "completion_tokens"):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counts.append(value)
    return counts[0], counts[1]


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
        self,
        client: httpx.Client,
        endpoint: str,
        payload: dict[str, Any],
        *,
        model: str,
        tokens_in: int,
    ) -> tuple[httpx.Response, int]:
        """Send one authorized physical attempt, retrying it at most `max_retries` times.

        Each send reserves its own worst-case cost before the bytes leave. A retry that was
        rejected by status or that timed out after dispatch stays charged at that bound; only
        a request that never reached the socket gives its reservation back, because a live
        request may have been billed whatever its outcome looked like from here.
        """
        attempt = 0
        backoff = 0.5
        max_tokens = int(payload.get("max_tokens") or 0)

        while True:
            attempt += 1
            held = self.budget_guard.reserve_units(
                model, tokens_in=tokens_in, tokens_out_bound=max_tokens
            )
            try:
                response = client.post(endpoint, json=payload)
            except httpx.ConnectError:
                self.budget_guard.release_hold(held)
                if attempt <= self.max_retries:
                    logger.warning("LLM connect failed on attempt %d. Backing off.", attempt)
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise
            except (httpx.ReadTimeout, httpx.WriteTimeout):
                self.budget_guard.charge_bound(
                    model, tokens_in=tokens_in, tokens_out_bound=max_tokens, held=held
                )
                if attempt <= self.max_retries:
                    logger.warning(
                        "LLM timed out after dispatch on attempt %d. Backing off.", attempt
                    )
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise
            if response.status_code in (429, 500, 502, 503, 504) and attempt <= self.max_retries:
                self._account(
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out_bound=max_tokens,
                    response=response,
                    held=held,
                )
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
            return response, held

    def _account(
        self,
        *,
        model: str,
        tokens_in: int,
        tokens_out_bound: int,
        response: httpx.Response,
        held: int,
    ) -> AttemptAccounting:
        """Book the attempt this call just made, usable answer or not.

        The provider's own count is used when it reported one. Otherwise the attempt is
        charged at the bound it was authorized with rather than an invented typical case,
        because a request that left this process may still have been billed.
        """
        if response.status_code == 200:
            reported = _reported_usage(response)
            if reported is not None:
                rate_in, rate_out = rates_for(model, self.budget_guard.price_table)
                charge = cost_units(reported[0], reported[1], rate_in, rate_out)
                if charge > held:
                    logger.warning(
                        "LLM charge exceeded its authorization code=charge_over_estimate model=%s",
                        model,
                    )
                return AttemptAccounting(
                    tokens_in=reported[0],
                    tokens_out=reported[1],
                    charge_units=self.budget_guard.settle_units(held=held, charge_units=charge),
                    usage_provenance="reported",
                )
            logger.warning("LLM usage absent code=usage_estimated model=%s", model)
        units = self.budget_guard.charge_bound(
            model, tokens_in=tokens_in, tokens_out_bound=tokens_out_bound, held=held
        )
        return AttemptAccounting(
            tokens_in=tokens_in,
            tokens_out=tokens_out_bound,
            charge_units=units,
            usage_provenance="estimated",
        )

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

        # Every physical attempt below reserves this bound before it sends.
        tokens_in_bound = input_token_bound(len(system) + len(user))
        accounting: AttemptAccounting

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

                resp, held = self._post_with_retries(
                    client,
                    "/chat/completions",
                    structured_payload,
                    model=model,
                    tokens_in=tokens_in_bound,
                )
                accounting = self._account(
                    model=model,
                    tokens_in=tokens_in_bound,
                    tokens_out_bound=max_tokens,
                    response=resp,
                    held=held,
                )
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

                resp_fb, held_fb = self._post_with_retries(
                    client,
                    "/chat/completions",
                    fallback_payload,
                    model=model,
                    tokens_in=tokens_in_bound,
                )
                accounting = self._account(
                    model=model,
                    tokens_in=tokens_in_bound,
                    tokens_out_bound=max_tokens,
                    response=resp_fb,
                    held=held_fb,
                )
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
                    resp_rep, held_rep = self._post_with_retries(
                        client,
                        "/chat/completions",
                        repair_payload,
                        model=model,
                        tokens_in=tokens_in_bound,
                    )
                    accounting = self._account(
                        model=model,
                        tokens_in=tokens_in_bound,
                        tokens_out_bound=max_tokens,
                        response=resp_rep,
                        held=held_rep,
                    )
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

            tokens_in = accounting.tokens_in
            tokens_out = accounting.tokens_out

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
                    cost_usd=float(units_to_usd(accounting.charge_units)),
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

        tokens_in_bound = input_token_bound(len(system) + len(user))

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
            resp, held = self._post_with_retries(
                client, "/chat/completions", payload, model=model, tokens_in=tokens_in_bound
            )
            accounting = self._account(
                model=model,
                tokens_in=tokens_in_bound,
                tokens_out_bound=max_tokens,
                response=resp,
                held=held,
            )
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
            tokens_in = accounting.tokens_in
            tokens_out = accounting.tokens_out

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
                    cost_usd=float(units_to_usd(accounting.charge_units)),
                    created_at=now_iso,
                    situation_id=situation_id,
                    redaction_counts=redaction_counts,
                )

            return text_result
