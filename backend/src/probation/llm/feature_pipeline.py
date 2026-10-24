"""Shared bounded feature adapter for replay, live ticks and exam edits."""

import hashlib
import math

from probation.core.hashing import canonical_json
from probation.core.history import HistoryView
from probation.core.types import Features, Situation
from probation.llm.consumers import RegisteredConsumer
from probation.llm.feature_identity import semantic_feature_version as semantic_feature_version
from probation.llm.reader import ReaderCallable, read_situation
from probation.llm.results import FailureCode
from probation.packs.registry import registry

FEATURIZER_VERSION = "wp3-reader-v1"


def novelty_context(situation: Situation, deterministic: dict[str, float | str | bool]) -> str:
    """Bound local embedding inputs at the role boundary, outside the pure policy."""
    from probation.llm.redact import redact

    text = situation.redacted_text or ""
    if situation.pack == "files":
        text = (
            f"Tokens: {deterministic.get('__name_tokens', '')}\n"
            f"Origin: {deterministic.get('origin_group', '')}\n"
            f"Extension: {deterministic.get('ext_group', '')}"
        )
    return redact(text, profile="file" if situation.pack == "files" else "mail", limit=4000).text[
        :4000
    ]


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

    det["__novelty_text"] = novelty_context(situation, det)
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
