"""LLM transport for Nebius Token Factory: per-attempt spend authority and classified failures.

Authority: docs/CONTRACT.md section 6, invariants I-1, I-3, I-14, I-15, I-16;
docs/wp3/WORK_PACKAGES.md P05.5-P05.9.

Every physical request reserves its own worst-case cost before its bytes leave, is booked after
it returns whatever the answer looks like, and is classified before anything decides whether to
send again. That ordering is the whole design: a request that reached the socket may have been
billed even when this process got nothing usable from it, and a request that never reached the
socket gives its authorization back.
"""

from __future__ import annotations

import hashlib
import logging
import random
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import TypeAdapter

from probation.config import settings
from probation.core.clock import Clock, get_clock
from probation.core.enums import ClockMode
from probation.core.hashing import canonical_json
from probation.db.inference import record_inference

if TYPE_CHECKING:
    from probation.db.spend import AttemptReservation, SpendStore
from probation.llm.budget import (
    BudgetGuard,
    cost_units,
    input_token_bound,
    rates_for,
    units_to_usd,
)
from probation.llm.cache import compute_cache_key, get_cached_response
from probation.llm.content import (
    TERMINAL_OUTPUT_CODES,
    parse_json,
    parse_text,
    safe_content,
)
from probation.llm.errors import (
    BACKOFF_FACTOR,
    INITIAL_BACKOFF_S,
    MAX_TREE_STAGES,
    LLMValidationError,
    OutputFailure,
    TransportFailure,
    bounded_wait,
    classify_response,
    is_transient,
)
from probation.llm.generation import direct_content_hash, generation_options
from probation.llm.results import FailureCode
from probation.llm.schema import UnsupportedSchema, compile_schema
from probation.llm.schema import validate_json_schema as validate_json_schema

logger = logging.getLogger(__name__)

ENDPOINT = "/chat/completions"
JSON_MODE_SUFFIX = "\nYou MUST return a JSON object adhering strictly to this schema: "
REPAIR_INSTRUCTION = (
    "The previous output was not valid JSON conforming to the schema. "
    "Output valid JSON only with all required fields."
)
_NO_ANSWER = "request ended without a usable answer"
# The accounting store names a rung by what it bought, not by what this client calls it: the
# first send of a stage is that stage, and every send after it inside the same stage is a retry.
STAGE_LABELS = {
    "structured": "structured",
    "json_only": "format_fallback",
    "repair": "repair",
    "text": "structured",
}


@dataclass(frozen=True, slots=True)
class AttemptAccounting:
    """What one physical request cost, and how much of that is the provider's own count."""

    tokens_in: int
    tokens_out: int
    charge_units: int
    usage_provenance: str


@dataclass(slots=True)
class RequestLedger:
    """Everything this logical request did: sends, egress and cost, summed per attempt."""

    sends: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    units: int = 0
    last_content: str = ""

    def absorb(self, charge: AttemptAccounting) -> None:
        self.sends += 1
        self.tokens_in += charge.tokens_in
        self.tokens_out += charge.tokens_out
        self.units += charge.charge_units

    def snapshot(self) -> tuple[int, int, int, int]:
        return self.sends, self.tokens_in, self.tokens_out, self.units


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One rung of the bounded ladder, recorded whether or not it produced an answer."""

    stage: str
    sends: int
    outcome: str


@dataclass(frozen=True, slots=True)
class JsonDispatch:
    """A JSON request's answer with the accounting that bought it."""

    data: dict[str, Any]
    cache_key: str
    cache_hit: bool
    physical_attempts: int
    tokens_in: int
    tokens_out: int
    cost_units: int
    stages: tuple[StageRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class TextDispatch:
    """A text request's answer with the accounting that bought it."""

    text: str
    cache_key: str
    cache_hit: bool
    physical_attempts: int
    tokens_in: int
    tokens_out: int
    cost_units: int
    stages: tuple[StageRecord, ...] = ()


def json_mode_system(system: str, schema: Mapping[str, Any]) -> str:
    """The JSON-only stage's system text: the same schema, now as visible instructions."""
    return f"{system}{JSON_MODE_SUFFIX}{canonical_json(schema)}"


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


def _identity(cache_parts: Mapping[str, str], user: str) -> tuple[str, str, str]:
    """(content_hash, prompt_id, prompt_version) for the contract's four-part outer key."""
    content_hash = cache_parts.get(
        "content_hash", hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]
    )
    return (
        content_hash,
        cache_parts.get("prompt_id", "prompt"),
        cache_parts.get("prompt_version", "v1"),
    )


class LLMClient:
    """Budget-guarded, retry-bounded inference for one approved endpoint."""

    def __init__(
        self,
        base_url: str = settings.llm_base_url,
        api_key: str = settings.llm_api_key,
        budget_guard: BudgetGuard | None = None,
        timeout_s: float = float(settings.llm_timeout_s),
        max_retries: int = settings.llm_max_retries,
        transport: httpx.BaseTransport | None = None,
        clock: Clock | None = None,
        sleeper: Callable[[float], None] | None = None,
        operational_clock: Clock | None = None,
        jitter_s: float = 0.0,
        jitter_seed: int = 0,
        max_physical_attempts: int | None = None,
        spend_store: SpendStore | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.budget_guard = budget_guard or BudgetGuard()
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.transport = transport
        self.clock = clock or get_clock()
        # Retry timing and a provider's Retry-After deadline are operational facts, never event
        # time: they get their own clock so a replay jump cannot age a paid reservation.
        self.operational_clock = operational_clock or Clock(mode=ClockMode.LIVE)
        self.sleeper = sleeper or time.sleep
        self.jitter_s = jitter_s
        self._random = random.Random(jitter_seed)
        self.max_physical_attempts = max_physical_attempts
        # Durable accounting (W3-D03): when bound, every physical attempt is reserved in the
        # database and committed before its bytes leave, so the cap holds across processes and
        # across a crash. A store that cannot record a reservation denies the dispatch.
        self.spend_store = spend_store
        self._unsupported_structured_models: set[str] = set()

    @property
    def default_attempt_ceiling(self) -> int:
        """The whole tree, declared: each stage may send its own bounded set of attempts."""
        return MAX_TREE_STAGES * (self.max_retries + 1)

    @property
    def attempt_ceiling(self) -> int:
        return self.max_physical_attempts or self.default_attempt_ceiling

    def _http_client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_s,
            transport=self.transport,
        )

    def available_models(self) -> list[dict[str, Any]]:
        """Read account model capability through the approved transport boundary."""
        if not self.api_key:
            raise LLMValidationError("Model catalog credentials unavailable")
        try:
            with self._http_client() as client:
                response = client.get("/models")
            if response.status_code != 200:
                raise LLMValidationError("Model catalog request failed")
            data = response.json().get("data")
            if not isinstance(data, list):
                raise ValueError("invalid catalog")
            return [
                {key: item[key] for key in ("id", "pricing") if key in item}
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise LLMValidationError("Model catalog unavailable") from exc

    def _open_spend_request(
        self,
        *,
        model: str,
        content_hash: str,
        prompt_id: str,
        prompt_version: str,
        cache_key: str,
        situation_id: str | None,
    ) -> str | None:
        """Claim this logical request's durable identity, or None when no store is bound.

        A missing scope, an unwritable table or an open caller transaction raises rather than
        returning None: quietly falling back to in-process accounting is the exact failure the
        durable store exists to prevent.
        """
        if self.spend_store is None:
            if self.transport is None:
                from probation.llm.budget import BudgetExceeded

                raise BudgetExceeded(
                    "Live dispatch requires durable accounting", code="accounting_store_unavailable"
                )
            return None
        scope = self.spend_store.scope_for(model)
        totals = self.spend_store.startup_totals(scope)
        self.budget_guard.adopt_durable(
            spent_units=totals.spent_units, held_units=totals.held_units
        )
        return self.spend_store.open_request(
            scope,
            semantic_digest=content_hash,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model_id=model,
            cache_key=cache_key,
            situation_id=situation_id,
        )

    def _settle_spend_request(self, request_id: str | None, *, succeeded: bool) -> None:
        if self.spend_store is None or request_id is None:
            return
        self.spend_store.settle_request(
            request_id, result_state="succeeded" if succeeded else "failed_closed"
        )

    def _dispatched_durable(self, reservation: AttemptReservation | None) -> None:
        """Record that the bytes are leaving: from here the estimate is owed until settled."""
        store = self.spend_store
        if store is not None and reservation is not None:
            store.mark_dispatched(reservation.attempt_id)

    def _never_dispatched_durable(self, reservation: AttemptReservation | None) -> None:
        """The only path that returns a hold to the cap: proof nothing reached the socket."""
        store = self.spend_store
        if store is not None and reservation is not None:
            store.mark_never_dispatched(reservation.attempt_id)

    def _ambiguous_durable(
        self, reservation: AttemptReservation | None, *, denial_code: str | None = None
    ) -> None:
        """A dispatched attempt whose outcome was never learned keeps its hold."""
        store = self.spend_store
        if store is not None and reservation is not None:
            store.mark_ambiguous(reservation.attempt_id, denial_code=denial_code)

    def _reconcile_durable(
        self,
        reservation: AttemptReservation | None,
        *,
        charged_units: int,
        usage_provenance: str,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        denial_code: str | None = None,
    ) -> None:
        store = self.spend_store
        if store is not None and reservation is not None:
            store.reconcile(
                reservation.attempt_id,
                charged_units=charged_units,
                usage_provenance=usage_provenance,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                denial_code=denial_code,
            )

    def _reserve_durable(
        self,
        request_id: str | None,
        *,
        ordinal: int,
        stage: str,
        estimate_units: int,
        tokens_in_bound: int,
        tokens_out_bound: int,
    ) -> AttemptReservation | None:
        if self.spend_store is None or request_id is None:
            return None
        return self.spend_store.reserve(
            request_id,
            ordinal=ordinal,
            stage=stage,
            estimate_units=estimate_units,
            tokens_in_bound=tokens_in_bound,
            tokens_out_bound=tokens_out_bound,
            runtime_cap_units=self.budget_guard.limit_units,
        )

    def _wait_before_retry(self, backoff: float, response: httpx.Response | None) -> float:
        """Sleep the authorized interval, or deny the next send when the hint cannot be obeyed."""
        now = self.operational_clock.now()
        hint = backoff if response is None else bounded_wait(response, now=now, backoff=backoff)
        if hint is None:
            raise TransportFailure(
                "provider asked for a wait this job will not take",
                code=FailureCode.ATTEMPT_BUDGET_EXHAUSTED,
            )
        self.sleeper(hint + self.jitter_s * self._random.random())
        return backoff * BACKOFF_FACTOR

    def _account(
        self,
        *,
        model: str,
        tokens_in: int,
        tokens_out_bound: int,
        response: httpx.Response,
        held: int,
        reservation: AttemptReservation | None,
    ) -> AttemptAccounting:
        """Book the attempt this call just made, usable answer or not.

        The provider's own count is used when it reported one. Otherwise the attempt is
        charged at the bound it was authorized with rather than an invented typical case,
        because a request that left this process may still have been billed.
        """
        denial = None if response.status_code == 200 else "status"
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
                settled = self.budget_guard.settle_units(held=held, charge_units=charge)
                self._reconcile_durable(
                    reservation,
                    charged_units=settled,
                    usage_provenance="reported",
                    tokens_in=reported[0],
                    tokens_out=reported[1],
                )
                return AttemptAccounting(
                    tokens_in=reported[0],
                    tokens_out=reported[1],
                    charge_units=settled,
                    usage_provenance="reported",
                )
            logger.warning("LLM usage absent code=usage_estimated model=%s", model)
        units = self.budget_guard.charge_bound(
            model, tokens_in=tokens_in, tokens_out_bound=tokens_out_bound, held=held
        )
        self._reconcile_durable(
            reservation,
            charged_units=units,
            usage_provenance="estimated",
            tokens_in=tokens_in,
            tokens_out=tokens_out_bound,
            denial_code=denial,
        )
        return AttemptAccounting(
            tokens_in=tokens_in,
            tokens_out=tokens_out_bound,
            charge_units=units,
            usage_provenance="estimated",
        )

    def _send(
        self,
        http: httpx.Client,
        payload: dict[str, Any],
        *,
        model: str,
        texts: Sequence[str],
        max_tokens: int,
        ledger: RequestLedger,
        stage: str = "text",
        spend_request: str | None = None,
    ) -> httpx.Response:
        """Send one stage, retrying only approved transients and never past the ceiling."""
        attempt = 0
        backoff = INITIAL_BACKOFF_S
        bound_in = input_token_bound(sum(len(text) for text in texts))
        while True:
            attempt += 1
            if ledger.sends >= self.attempt_ceiling:
                raise TransportFailure(
                    "attempt ceiling reached before the next send",
                    code=FailureCode.ATTEMPT_BUDGET_EXHAUSTED,
                )
            held = self.budget_guard.reserve_units(
                model, tokens_in=bound_in, tokens_out_bound=max_tokens
            )
            # The durable reservation is committed here, before the socket opens, and it is
            # the object the cross-process cap is enforced against. If it cannot be recorded
            # the in-process hold is given back and the send is denied.
            try:
                reservation = self._reserve_durable(
                    spend_request,
                    ordinal=ledger.sends + 1,
                    stage=STAGE_LABELS.get(stage, "retry") if attempt == 1 else "retry",
                    estimate_units=held,
                    tokens_in_bound=bound_in,
                    tokens_out_bound=max_tokens,
                )
            except Exception:
                self.budget_guard.release_hold(held)
                raise
            try:
                self._dispatched_durable(reservation)
            except Exception:
                # Nothing was sent, but the durable row is already holding this estimate and
                # only a validated never-dispatched transition may lower a hold. Deny.
                self.budget_guard.release_hold(held)
                raise
            try:
                response = http.post(ENDPOINT, json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                # A connect-phase failure never reached the socket, so none of it is owed back.
                self.budget_guard.release_hold(held)
                if reservation is not None:
                    # Dispatch intent is already durable. Without provider proof, preserve
                    # the hold; a connection exception cannot reverse that audit state.
                    self._ambiguous_durable(reservation, denial_code="transport")
                    raise
                self._never_dispatched_durable(reservation)
                ledger.sends += 1
                if attempt > self.max_retries:
                    raise
                logger.warning("LLM connect failed on attempt %d. Backing off.", attempt)
                backoff = self._wait_before_retry(backoff, None)
                continue
            except (httpx.ReadTimeout, httpx.WriteTimeout):
                units = self.budget_guard.charge_bound(
                    model, tokens_in=bound_in, tokens_out_bound=max_tokens, held=held
                )
                self._reconcile_durable(
                    reservation,
                    charged_units=units,
                    usage_provenance="estimated",
                    tokens_in=bound_in,
                    tokens_out=max_tokens,
                    denial_code="transport",
                )
                ledger.absorb(
                    AttemptAccounting(
                        tokens_in=bound_in,
                        tokens_out=max_tokens,
                        charge_units=units,
                        usage_provenance="estimated",
                    )
                )
                if attempt > self.max_retries:
                    raise
                logger.warning("LLM timed out after dispatch on attempt %d. Backing off.", attempt)
                backoff = self._wait_before_retry(backoff, None)
                continue
            except BaseException:
                # The request left this process and its answer was never read: hold the money
                # until something reconciles it, and never claim it was free.
                self._ambiguous_durable(reservation, denial_code="transport")
                raise
            ledger.absorb(
                self._account(
                    model=model,
                    tokens_in=bound_in,
                    tokens_out_bound=max_tokens,
                    response=response,
                    held=held,
                    reservation=reservation,
                )
            )
            if is_transient(response) and attempt <= self.max_retries:
                logger.warning(
                    "LLM received status %d on attempt %d. Retrying.",
                    response.status_code,
                    attempt,
                )
                backoff = self._wait_before_retry(backoff, response)
                continue
            return response

    def _attempt_answer(
        self,
        http: httpx.Client,
        messages: list[dict[str, str]],
        *,
        stage: str,
        model: str,
        schema: dict[str, Any],
        adapter: TypeAdapter[Any],
        prompt_id: str,
        prompt_version: str,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        ledger: RequestLedger,
        stages: list[StageRecord],
        spend_request: str | None = None,
    ) -> dict[str, Any] | None:
        """One rung: send it, classify it, and never re-bill a terminal model state.

        Returns None only when the provider itself rejected the response format, which is the
        single fact that authorizes the next format. An unusable answer raises, so the caller
        cannot mistake "answered badly" for "may be asked differently".
        """
        before = ledger.sends
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            **generation_options(model),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        texts = [message["content"] for message in messages]
        response = self._send(
            http,
            payload,
            model=model,
            texts=texts,
            max_tokens=max_tokens,
            ledger=ledger,
            stage=stage,
            spend_request=spend_request,
        )
        code = classify_response(response)
        if code is FailureCode.UNSUPPORTED_FORMAT:
            if stage == "structured":
                self._unsupported_structured_models.add(model)
            stages.append(StageRecord(stage, ledger.sends - before, code.value))
            return None
        if code is not None:
            stages.append(StageRecord(stage, ledger.sends - before, code.value))
            raise TransportFailure(_NO_ANSWER, code=code)
        try:
            answer = parse_json(
                response,
                schema=schema,
                adapter=adapter,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
            )
        except OutputFailure as failure:
            stages.append(StageRecord(stage, ledger.sends - before, failure.code.value))
            ledger.last_content = safe_content(response)
            raise
        stages.append(StageRecord(stage, ledger.sends - before, "accepted"))
        return answer

    def _messages(self, system: str, user: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def dispatch_json(
        self,
        *,
        kind: str,
        model: str,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        cache_parts: Mapping[str, str],
        conn: sqlite3.Connection | None = None,
        situation_id: str | None = None,
        redaction_counts: dict[str, int] | None = None,
        max_tokens: int = 1000,
        check_cache: bool = True,
    ) -> JsonDispatch:
        """Run the bounded ladder for one JSON request and return the answer it paid for.

        Three stages in order: structured output, JSON-only, then exactly one repair of the
        JSON-only answer. A stage is entered only because the previous one was answered and that
        answer was unusable, or because the provider rejected the format. A transport, authority
        or terminal-model-state failure stops the request where it stands.
        """
        request_schema = dict(schema)
        try:
            adapter = compile_schema(request_schema)
        except UnsupportedSchema as exc:
            raise LLMValidationError("Unsupported output schema") from exc
        content_hash, prompt_id, prompt_version = _identity(cache_parts, user)
        if check_cache:
            content_hash = direct_content_hash(model, content_hash)
        cache_key = compute_cache_key(content_hash, prompt_id, prompt_version, model)
        if conn is not None and check_cache:
            cached = get_cached_response(conn, cache_key)
            if cached is not None:
                valid, _ = validate_json_schema(cached, request_schema)
                if not valid:
                    raise LLMValidationError("Cached output fails current schema validation")
                return JsonDispatch(cached, cache_key, True, 0, 0, 0, 0)

        spend_request = self._open_spend_request(
            model=model,
            content_hash=content_hash,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            cache_key=cache_key,
            situation_id=situation_id,
        )
        ledger = RequestLedger()
        stages: list[StageRecord] = []
        json_object: dict[str, Any] = {"type": "json_object"}
        structured_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {"name": "response", "strict": True, "schema": request_schema},
        }
        fallback_system = json_mode_system(system, request_schema)
        plan = ["json_only", "repair"]
        if model not in self._unsupported_structured_models:
            plan.insert(0, "structured")
        data: dict[str, Any] | None = None

        settled = False
        try:
            with self._http_client() as http:
                for position, stage in enumerate(plan):
                    is_final = position == len(plan) - 1
                    if stage == "structured":
                        messages, wire_format = self._messages(system, user), structured_format
                    elif stage == "json_only":
                        messages, wire_format = self._messages(fallback_system, user), json_object
                    else:
                        messages = self._messages(fallback_system, user)
                        messages.append({"role": "assistant", "content": ledger.last_content})
                        messages.append({"role": "user", "content": REPAIR_INSTRUCTION})
                        wire_format = json_object
                    try:
                        data = self._attempt_answer(
                            http,
                            messages,
                            stage=stage,
                            model=model,
                            schema=request_schema,
                            adapter=adapter,
                            prompt_id=prompt_id,
                            prompt_version=prompt_version,
                            max_tokens=max_tokens,
                            response_format=wire_format,
                            ledger=ledger,
                            stages=stages,
                            spend_request=spend_request,
                        )
                    except OutputFailure as failure:
                        if is_final or failure.code in TERMINAL_OUTPUT_CODES:
                            raise
                        continue
                    if data is not None:
                        break

            if data is None:
                raise LLMValidationError(_NO_ANSWER)
            settled = True
        finally:
            self._settle_spend_request(spend_request, succeeded=settled)

        sends, tokens_in, tokens_out, units = ledger.snapshot()
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
                cost_usd=float(units_to_usd(units)),
                cost_units=units,
                created_at=self.clock.now_iso(),
                situation_id=situation_id,
                redaction_counts=redaction_counts,
            )
            if self.spend_store is not None:
                conn.commit()
        return JsonDispatch(
            data, cache_key, False, sends, tokens_in, tokens_out, units, tuple(stages)
        )

    def dispatch_text(
        self,
        *,
        kind: str,
        model: str,
        system: str,
        user: str,
        cache_parts: Mapping[str, str],
        max_tokens: int = 400,
        conn: sqlite3.Connection | None = None,
        situation_id: str | None = None,
        redaction_counts: dict[str, int] | None = None,
        check_cache: bool = True,
    ) -> TextDispatch:
        """One text request: prose has no format to fall back to and no schema to repair."""
        content_hash, prompt_id, prompt_version = _identity(cache_parts, user)
        if check_cache:
            content_hash = direct_content_hash(model, content_hash)
        cache_key = compute_cache_key(content_hash, prompt_id, prompt_version, model)
        if conn is not None and check_cache:
            cached = get_cached_response(conn, cache_key)
            if cached is not None:
                if not isinstance(cached, dict) or set(cached) != {"text"}:
                    raise LLMValidationError("Invalid cached text shape")
                text = cached["text"]
                if not isinstance(text, str) or not text.strip():
                    raise LLMValidationError("Text output must be a nonempty string")
                return TextDispatch(text, cache_key, True, 0, 0, 0, 0)

        spend_request = self._open_spend_request(
            model=model,
            content_hash=content_hash,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            cache_key=cache_key,
            situation_id=situation_id,
        )
        ledger = RequestLedger()
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._messages(system, user),
            "temperature": 0.0,
            "max_tokens": max_tokens,
            **generation_options(model),
        }
        settled = False
        try:
            with self._http_client() as http:
                response = self._send(
                    http,
                    payload,
                    model=model,
                    texts=(system, user),
                    max_tokens=max_tokens,
                    ledger=ledger,
                )
                code = classify_response(response)
                if code is not None:
                    raise TransportFailure(_NO_ANSWER, code=code)
                text = parse_text(response)
            settled = True
        finally:
            self._settle_spend_request(spend_request, succeeded=settled)

        sends, tokens_in, tokens_out, units = ledger.snapshot()
        if conn is not None:
            record_inference(
                conn,
                cache_key=cache_key,
                kind=kind,
                model_id=model,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                response_data={"text": text},
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=float(units_to_usd(units)),
                cost_units=units,
                created_at=self.clock.now_iso(),
                situation_id=situation_id,
                redaction_counts=redaction_counts,
            )
            if self.spend_store is not None:
                conn.commit()
        return TextDispatch(text, cache_key, False, sends, tokens_in, tokens_out, units)

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
        """Diagnostic JSON call: the ladder's answer, with its accounting kept in the ledger."""
        return self.dispatch_json(
            kind=kind,
            model=model,
            system=system,
            user=user,
            schema=schema,
            cache_parts=cache_parts,
            conn=conn,
            situation_id=situation_id,
            redaction_counts=redaction_counts,
            max_tokens=max_tokens,
        ).data

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
        """Diagnostic text call: one request for prose, or a typed failure."""
        return self.dispatch_text(
            kind=kind,
            model=model,
            system=system,
            user=user,
            max_tokens=max_tokens,
            cache_parts=cache_parts,
            conn=conn,
            situation_id=situation_id,
            redaction_counts=redaction_counts,
        ).text
