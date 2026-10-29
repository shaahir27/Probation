"""Decide whether a registered job may run, then run it exactly as often as it must.

Authority: docs/CONTRACT.md section 6, invariants I-1, I-3, I-14, I-15, I-16;
docs/wp3/WORK_PACKAGES.md P05.1-P05.4, P05.9.

The client answers a schema it is handed and cannot know whether a job is permitted. This module
decides that first, in one order that is itself the safety property: registration, asset, model
role, bounded request, semantic identity, cache *with its spend provenance*, transport authority,
then the network. Reading the cache before asking for authority is deliberate - a row whose
exposure record has gone is a data-integrity finding, and re-buying its answer would turn that
finding into a silent bill.
"""

import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from probation.config import settings
from probation.core.hashing import det_id
from probation.llm.budget import BudgetExceeded
from probation.llm.cache import (
    CacheProvenance,
    SemanticEnvelope,
    get_cache_row,
    usable_cached_answer,
)
from probation.llm.catalog import JobNotRegistered, JobSpec, model_for_job, resolve_job
from probation.llm.client import LLMClient
from probation.llm.context import check_headers, request_limit_for
from probation.llm.errors import LLMValidationError
from probation.llm.generation import context_version
from probation.llm.jobs import validate_job_output
from probation.llm.prompt_loader import (
    CONTEXT_VERSION,
    PromptAsset,
    PromptAssetError,
    compile_request,
    load_prompt,
    provider_schema,
)
from probation.llm.results import FailureCode, JobOutcome, Provenance

logger = logging.getLogger(__name__)

# The two versions a cached answer is only reusable under: which code validated it, and which
# egress encoder produced the text it was asked about.
VALIDATOR_VERSION = "wp3-p05-v1"
ENCODER_VERSION = "wp3-p03-v1"
REQUEST_ID_PREFIX = "llm-request-v1"

ContextualCheck = Callable[[Mapping[str, Any]], "tuple[FailureCode, str] | None"]


class JobFailure(LLMValidationError):
    """A registered job did not happen. `code` is the typed reason and the text is always safe."""


@dataclass(frozen=True, slots=True)
class TransportAuthority:
    """Whether *this run* may put bytes on the wire, and to which approved destination.

    Possession of a key is not a grant: the caller has to say so, and the grant is then bound to
    the endpoint it was read for, so a client aimed elsewhere cannot borrow it.
    """

    granted: bool
    endpoint: str
    reason: str = ""

    def deny(self) -> "JobFailure":
        return JobFailure(
            f"live dispatch refused: {self.reason}" if self.reason else "live dispatch refused",
            code=FailureCode.NO_TRANSPORT_AUTHORITY,
        )


def provider_of(endpoint: str) -> str:
    """The host a request would reach, which is the fact the cache identity needs."""
    return urlparse(endpoint).hostname or ""


def transport_authority(
    client: LLMClient,
    *,
    allow_live_dispatch: bool = True,
    approved_base_url: str | None = None,
) -> TransportAuthority:
    """Read the grant for one client without ever touching a credential value."""
    approved = (settings.llm_base_url if approved_base_url is None else approved_base_url).rstrip(
        "/"
    )
    endpoint = client.base_url.rstrip("/")
    if not allow_live_dispatch:
        return TransportAuthority(False, endpoint, "this run did not opt into live dispatch")
    if not str(client.api_key or "").strip():
        return TransportAuthority(False, endpoint, "no transport credential is configured")
    if endpoint != approved:
        return TransportAuthority(False, endpoint, "endpoint is not the approved destination")
    return TransportAuthority(True, endpoint, "")


def build_envelope(
    *,
    asset: PromptAsset,
    model_id: str,
    system: str,
    user: str,
    purpose: str,
    provider: str | None = None,
    temperature: float = 0.0,
) -> SemanticEnvelope:
    """Digest the whole semantic request, not just its content, into `content_hash`.

    The contract's outer key stays the four-part tuple (I-16); only its `content_hash` component
    grows, so an old row answers an old question and never a new one.
    """
    spec = asset.spec
    return SemanticEnvelope(
        prompt_id=spec.prompt_id,
        prompt_version=spec.prompt_version,
        model_id=model_id,
        provider=provider_of(settings.llm_base_url) if provider is None else provider,
        purpose=purpose,
        system=system,
        user=user,
        max_tokens=spec.max_tokens,
        temperature=temperature,
        template_hash=asset.template_hash,
        schema_fingerprint=asset.schema_fingerprint,
        context_version=context_version(model_id, CONTEXT_VERSION),
        validator_version=VALIDATOR_VERSION,
    )


def _asset_failure(exc: PromptAssetError) -> JobFailure:
    """Asset text names job ids and bounds only, so it is safe to carry through."""
    return JobFailure(str(exc), code=getattr(exc, "code", FailureCode.ASSET_MISMATCH))


class JobGateway:
    """The only route a registered production job may take to the model."""

    def __init__(self, client: LLMClient | None, *, conn: sqlite3.Connection | None = None) -> None:
        self.client = client
        self.conn = conn
        self._sequence = 0

    def dispatch(
        self,
        prompt_id: str,
        prompt_version: str,
        *,
        values: Mapping[str, str],
        purpose: str,
        authority: TransportAuthority,
        contextual: ContextualCheck | None = None,
        request_limit: int | None = None,
        redaction_counts: Mapping[str, int] | None = None,
        situation_id: str | None = None,
    ) -> JobOutcome:
        """Run one registered job, or fail typed before anything is sent.

        `values` must already be the bounded, redacted placeholders the asset declares; the
        gateway does not redact, because a caller that redacts twice cannot prove which text left.
        """
        if self.conn is None:
            raise JobFailure(
                "a production job needs a connection that can record its spend",
                code=FailureCode.ACCOUNTING_UNAVAILABLE,
            )
        spec = self._resolve(prompt_id, prompt_version)
        try:
            asset = load_prompt(spec)
        except PromptAssetError as exc:
            raise _asset_failure(exc) from exc
        try:
            model = model_for_job(spec)
        except JobNotRegistered as exc:
            raise JobFailure(
                f"job {spec.qualified_id} has no configured model",
                code=FailureCode.NOT_REGISTERED,
            ) from exc
        system, user = self._compile(spec, asset, values, request_limit)
        envelope = build_envelope(
            asset=asset,
            model_id=model,
            system=system,
            user=user,
            purpose=purpose,
            provider=provider_of(authority.endpoint),
        )
        counts = dict(redaction_counts or {})

        cached = self._cached(envelope)
        if cached is not None:
            # Same identity, same validator, same schema fingerprint: the row is this question's
            # answer. Re-checking it costs nothing and cannot buy a call, so a stale row is
            # refused here rather than re-bought.
            if not validate_job_output(dict(cached), spec.prompt_id, spec.prompt_version):
                raise JobFailure(
                    "a cached answer no longer satisfies this job's contract",
                    code=FailureCode.INVALID_OUTPUT,
                )
            self._contextual(cached, contextual)
            cached_row = get_cache_row(self.conn, envelope.cache_key())
            return JobOutcome(
                dict(cached),
                self._provenance(spec, asset, model, counts, transport="cache", request_id=None),
                True,
                0,
                0,
                int(cached_row["tokens_in"]) if cached_row is not None else 0,
                int(cached_row["tokens_out"]) if cached_row is not None else 0,
            )

        if not authority.granted:
            raise authority.deny()
        if self.client is None:
            raise JobFailure(
                "offline gateway has no dispatch client", code=FailureCode.NO_TRANSPORT_AUTHORITY
            )

        self._sequence += 1
        request_id = det_id(REQUEST_ID_PREFIX, f"{envelope.cache_key()}:{self._sequence}")
        try:
            answer = self.client.dispatch_json(
                kind=spec.model_role.value,
                model=model,
                system=system,
                user=user,
                schema=provider_schema(spec),
                cache_parts={
                    "content_hash": envelope.content_hash(),
                    "prompt_id": spec.prompt_id,
                    "prompt_version": spec.prompt_version,
                },
                conn=self.conn,
                situation_id=situation_id,
                redaction_counts=counts,
                max_tokens=spec.max_tokens,
                check_cache=False,
            )
        except BudgetExceeded as exc:
            raise JobFailure(
                f"budget authority refused this dispatch: {exc.code}",
                code=FailureCode.BUDGET_DENIED,
            ) from exc
        except LLMValidationError as exc:
            raise JobFailure(exc.safe_reason, code=exc.code) from exc

        self._contextual(answer.data, contextual)
        return JobOutcome(
            dict(answer.data),
            self._provenance(spec, asset, model, counts, transport="live", request_id=request_id),
            answer.cache_hit,
            answer.physical_attempts,
            answer.cost_units,
            answer.tokens_in,
            answer.tokens_out,
        )

    def _resolve(self, prompt_id: str, prompt_version: str) -> JobSpec:
        try:
            return resolve_job(prompt_id, prompt_version)
        except JobNotRegistered as exc:
            raise JobFailure(
                f"job {prompt_id}.{prompt_version} is not registered",
                code=FailureCode.NOT_REGISTERED,
            ) from exc

    def _compile(
        self,
        spec: JobSpec,
        asset: PromptAsset,
        values: Mapping[str, str],
        request_limit: int | None,
    ) -> tuple[str, str]:
        limit = request_limit_for(spec) if request_limit is None else int(request_limit)
        try:
            system, user = compile_request(asset, dict(values), user_limit=limit)
            check_headers(spec, asset.user, user)
        except PromptAssetError as exc:
            raise _asset_failure(exc) from exc
        return system, user

    def _cached(self, envelope: SemanticEnvelope) -> dict[str, Any] | None:
        assert self.conn is not None
        try:
            return usable_cached_answer(self.conn, envelope)
        except CacheProvenance as exc:
            raise JobFailure(
                "a cached answer has no exposure record to vouch for it",
                code=FailureCode.CACHE_PROVENANCE,
            ) from exc

    @staticmethod
    def _contextual(data: Mapping[str, Any], contextual: ContextualCheck | None) -> None:
        """The caller's rules on schema-valid data: a form can be well-formed and still wrong."""
        if contextual is None:
            return
        found = contextual(data)
        if found is not None:
            code, reason = found
            raise JobFailure(reason, code=code)

    def _provenance(
        self,
        spec: JobSpec,
        asset: PromptAsset,
        model: str,
        counts: Mapping[str, int],
        *,
        transport: str,
        request_id: str | None,
    ) -> Provenance:
        return Provenance(
            prompt_id=spec.prompt_id,
            prompt_version=spec.prompt_version,
            model_id=model,
            template_hash=asset.template_hash,
            schema_fingerprint=asset.schema_fingerprint,
            context_version=context_version(model, CONTEXT_VERSION),
            encoder_version=ENCODER_VERSION,
            redaction_profile=spec.redaction_profile,
            redaction_counts=dict(counts),
            transport=transport,
            request_id=request_id,
            # The durable attempt store is gated on the W3-D03 schema review (docs/wp3/
            # W3_D03_SPEND_ACCOUNTING_REVIEW.md), so this run names no attempt it cannot prove.
            attempt_id=None,
        )


__all__ = [
    "ENCODER_VERSION",
    "VALIDATOR_VERSION",
    "JobFailure",
    "JobGateway",
    "TransportAuthority",
    "build_envelope",
    "provider_of",
    "transport_authority",
]
