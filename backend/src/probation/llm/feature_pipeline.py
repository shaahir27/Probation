"""Shared bounded feature adapter for replay, live ticks and exam edits."""

import hashlib
import math

from probation.core.hashing import canonical_json
from probation.core.history import HistoryView
from probation.core.types import Features, Situation
from probation.llm.consumers import RegisteredConsumer
from probation.llm.reader import ReaderCallable, read_situation
from probation.llm.results import FailureCode
from probation.packs.registry import registry

FEATURIZER_VERSION = "wp3-reader-v1"


def semantic_feature_version(*, stub: bool = False) -> str:
    """Shared extraction/training identity, excluding operational transport facts."""
    from probation.config import settings
    from probation.llm.catalog import JobNotRegistered, ModelRole, model_for_job, registered_jobs
    from probation.llm.gateway import ENCODER_VERSION
    from probation.llm.prompt_loader import CONTEXT_VERSION, PromptAssetError, load_prompt

    jobs = []
    for spec in registered_jobs().values():
        if spec.model_role is ModelRole.READER:
            try:
                asset = load_prompt(spec)
                model = "offline-stub" if stub else model_for_job(spec)
            except (PromptAssetError, JobNotRegistered):
                return FEATURIZER_VERSION + ":unavailable"
            jobs.append(
                [
                    spec.qualified_id,
                    model,
                    asset.template_hash,
                    asset.schema_fingerprint,
                ]
            )
    encoded = canonical_json(
        {
            "encoder": FEATURIZER_VERSION,
            "context": CONTEXT_VERSION,
            "redaction": ENCODER_VERSION,
            "history": "wp4-history-v1",
            "endpoint": settings.llm_base_url,
            "jobs": jobs,
        }
    )
    return FEATURIZER_VERSION + ":" + hashlib.sha256(encoded.encode()).hexdigest()[:16]


def compute_features(
    situation: Situation,
    history: HistoryView,
    *,
    consumer: RegisteredConsumer | None = None,
    reader_callable: ReaderCallable | None = None,
) -> Features:
    pack = registry.get_descriptor(situation.pack)
    valid = True
    try:
        det = pack.deterministic_clues(situation, history)
        valid = all(
            isinstance(v, (bool, str, int, float))
            and (not isinstance(v, (int, float)) or math.isfinite(v))
            for v in det.values()
        )
    except (ValueError, TypeError, KeyError, ArithmeticError):
        det, valid = {}, False
    if not valid:
        det = {}
    result = read_situation(
        situation, history, det, consumer=consumer, reader_callable=reader_callable
    )
    fields = dict(result.fields) if result.fields is not None else None
    semantic_version = semantic_feature_version(stub=reader_callable is not None)
    if semantic_version.endswith(":unavailable"):
        valid = False
    # P06 #4: a contradiction between authoritative header facts and the reader form is a
    # reader-side failure. It must fail the gate through reader_ok, never by relabelling
    # sound deterministic clues as invalid.
    reader_ok = result.ok
    if situation.pack == "mail" and fields is not None:
        if bool(fields.get("looks_automated")) != (det.get("sender_tier") == "automated"):
            reader_ok = False
            det["__reader_failure_reason"] = "reader_header_conflict"
    if result.failure is FailureCode.HEADER_CONFLICT or result.reason == "reader_header_conflict":
        reader_ok = False
        det["__reader_failure_reason"] = "reader_header_conflict"
    elif not result.ok and result.reason:
        det["__reader_failure_reason"] = result.reason
    if not reader_ok and det.get("__reader_failure_reason") == "reader_header_conflict":
        # A contradicted form is not a validated read; it must not reach the policy as one.
        fields = None

    det["__deterministic_ok"] = valid
    det["__reader_required"] = result.required
    det["__budget_ok"] = result.failure not in {
        FailureCode.BUDGET_DENIED,
        FailureCode.ACCOUNTING_UNAVAILABLE,
        FailureCode.ATTEMPT_BUDGET_EXHAUSTED,
    }

    full_prov = result.provenance.as_dict()
    full_prov["cutoff"] = situation.occurred_at
    full_prov_json = canonical_json(full_prov)

    provenance_hash_dict = result.provenance.as_dict()
    for key in ("transport", "request_id", "attempt_id", "redaction_counts"):
        provenance_hash_dict.pop(key, None)
    digest = hashlib.sha256(
        canonical_json(
            {
                "deterministic": det,
                "reader": fields,
                "provenance": provenance_hash_dict,
                "encoder": FEATURIZER_VERSION,
            }
        ).encode()
    ).hexdigest()
    return Features(
        situation_id=situation.id,
        deterministic=det,
        reader=fields,
        reader_ok=reader_ok,
        featurizer_version=semantic_version,
        model_id=result.provenance.model_id,
        prompt_version=result.provenance.prompt_version,
        features_hash=digest,
        provenance_json=full_prov_json,
    )
