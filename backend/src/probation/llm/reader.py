"""One strict reader seam for event-time extraction and counterfactual adapters."""

import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.llm.catalog import resolve_job
from probation.llm.consumers import RegisteredConsumer
from probation.llm.context import redaction_names
from probation.llm.gateway import JobFailure
from probation.llm.prompt_loader import PromptAssetError, load_prompt
from probation.llm.results import FailureCode, Provenance, ReaderOutcome, ReaderStatus

ReaderCallable = Callable[[Situation], tuple[dict[str, Any] | None, bool]]
READER_JOBS = {
    "mail": ("reader.mail", "v4"),
    "calendar": ("reader.invite", "v2"),
    "files": ("reader.file", "v1"),
    "radar": ("reader.opportunity", "v1"),
}

# P06 #1: packs the contract requires a read for even though no reader job applies.
# `quarantine` is the external quarantined extractor result, `inherited` the trigger
# situation's validated reader context. Absence of either is not a reader success (W3-T03).
READER_READINESS = {"reading": "quarantine", "chains": "inherited"}
READINESS_REASONS = {"quarantine": "quarantine_unavailable", "inherited": "inherited_unavailable"}


def _readiness_fields(readiness: str, clues: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validated non-reader evidence, or None when the pack's readiness is absent."""
    if readiness == "quarantine":
        fields = clues.get("quarantine_fields")
        if clues.get("quarantine_ready") is True and isinstance(fields, Mapping) and fields:
            return dict(fields)
        return None
    inherited = clues.get("inherited_reader_context")
    if isinstance(inherited, Mapping) and inherited:
        return dict(inherited)
    return None


def reader_required(pack: str) -> bool:
    """The single authority for the gate's `reader_required` input.

    `reader_spec() is None` is not the contract on its own: `files` is optional only while
    its reader is disabled, readiness packs are always required, and an unregistered pack
    fails closed instead of silently skipping the read.
    """
    from probation.packs.registry import registry

    if pack in READER_READINESS:
        return True
    try:
        return registry.get_descriptor(pack).reader_spec() is not None
    except KeyError:
        return True


def read_situation(
    situation: Situation,
    history: HistoryView,
    clues: Mapping[str, Any],
    *,
    consumer: RegisteredConsumer | None = None,
    reader_callable: ReaderCallable | None = None,
    payload_override: Mapping[str, Any] | None = None,
) -> ReaderOutcome:
    required = reader_required(situation.pack)
    key = READER_JOBS.get(situation.pack)
    readiness = READER_READINESS.get(situation.pack)
    provenance = Provenance(
        key[0] if key else f"readiness.{readiness}" if readiness else "unregistered",
        key[1] if key else "none",
        None,
        None,
        None,
        "wp3-context-v1",
        "wp3-reader-v1",
        situation.pack,
    )
    if readiness is not None:
        evidence = _readiness_fields(readiness, clues)
        if evidence is None:
            return ReaderOutcome.failed(
                required=True,
                provenance=provenance,
                failure=FailureCode.CLUES_INVALID,
                reason=READINESS_REASONS[readiness],
            )
        return ReaderOutcome(ReaderStatus.VALIDATED, True, evidence, provenance)
    if not required:
        return ReaderOutcome(ReaderStatus.OPTIONAL_DISABLED, False, None, provenance)
    if key is None:
        return ReaderOutcome.failed(
            required=True,
            provenance=provenance,
            failure=FailureCode.NOT_REGISTERED,
            reason="reader_not_registered",
        )
    try:
        spec = resolve_job(*key)
        asset = load_prompt(spec)

        if situation.pack == "calendar":
            org_dom = clues.get("organizer_domain_class")
            dur_min = clues.get("duration_min")
            start_bucket = clues.get("start_hour_bucket")
            if org_dom is None or dur_min is None or start_bucket is None:
                return ReaderOutcome.failed(
                    required=required,
                    provenance=provenance,
                    failure=FailureCode.CLUES_INVALID,
                    reason="missing_calendar_context",
                )
        elif situation.pack == "mail" and (
            consumer is not None or "sender_domain_class" in clues or "sender_tier" in clues
        ):
            snd_class = clues.get("sender_domain_class")
            if snd_class is None:
                return ReaderOutcome.failed(
                    required=required,
                    provenance=provenance,
                    failure=FailureCode.CLUES_INVALID,
                    reason="missing_mail_context",
                )

        if reader_callable is not None:
            data, ok = reader_callable(situation)
            if not ok or data is None:
                raise ValueError("stub_failed")
            data = spec.output_model().model_validate(data, strict=True).model_dump()
            provenance = Provenance(
                *key,
                "offline-stub",
                asset.template_hash,
                asset.schema_fingerprint,
                "wp3-context-v1",
                "wp3-reader-v1",
                spec.redaction_profile,
                transport="stub",
            )
        else:
            if consumer is None:
                return ReaderOutcome.failed(
                    required=True,
                    provenance=provenance,
                    failure=FailureCode.NO_TRANSPORT_AUTHORITY,
                    reason="reader_unavailable",
                )
            raw = history.get_raw_item(situation.raw_item_id)
            if raw is None:
                raise ValueError("source_not_known")
            payload = (
                dict(payload_override)
                if payload_override is not None
                else json.loads(raw["payload_json"])
            )
            if situation.pack in {"mail", "radar"}:
                fields = {
                    "subject": str(payload.get("subject", "")),
                    "body": str(payload.get("body", "")),
                }
                if situation.pack == "mail":
                    fields["sender_domain_class"] = str(clues["sender_domain_class"])
            elif situation.pack == "calendar":
                fields = {
                    "title": str(payload.get("title", "")),
                    "description": str(payload.get("description", "")),
                    "organizer_domain_class": str(clues["organizer_domain_class"]),
                    "duration_min": str(clues["duration_min"]),
                    "start_hour_bucket": str(clues["start_hour_bucket"]),
                }
            else:
                fields = {
                    "filename": str(payload.get("filename") or payload.get("rel_path", "")),
                    "snippet": str(payload.get("snippet", "")),
                }
            context = (
                consumer.context(
                    key[0],
                    fields,
                    display_names=redaction_names(
                        payload.get("from", ""), payload.get("to", ""), payload.get("organizer", "")
                    ),
                )
                if key[1] == "v1"
                else None
            )
            # Reader mail/invite use immutable newer request versions.
            if context is None:
                from probation.llm.context import build_request_context

                context = build_request_context(
                    spec,
                    fields,
                    display_names=redaction_names(
                        payload.get("from", ""), payload.get("to", ""), payload.get("organizer", "")
                    ),
                )
            result = consumer.run(context, purpose="reader", situation_id=situation.id)
            data = spec.output_model().model_validate(dict(result.data), strict=True).model_dump()
            provenance = result.provenance

        # P06 #4: Authoritative mail header consistency check
        if situation.pack == "mail" and data is not None:
            sender_tier = clues.get("sender_tier")
            if sender_tier is not None:
                if bool(data.get("looks_automated")) != (sender_tier == "automated"):
                    return ReaderOutcome.failed(
                        required=required,
                        provenance=provenance,
                        failure=FailureCode.HEADER_CONFLICT,
                        reason="reader_header_conflict",
                    )

        return ReaderOutcome(ReaderStatus.VALIDATED, True, data, provenance)
    except (ValidationError, ValueError, TypeError):
        return ReaderOutcome.failed(
            required=True,
            provenance=provenance,
            failure=FailureCode.INVALID_OUTPUT,
            reason="reader_invalid",
        )
    except (JobFailure, PromptAssetError) as exc:
        return ReaderOutcome.failed(
            required=True, provenance=provenance, failure=exc.code, reason=exc.code.value
        )
