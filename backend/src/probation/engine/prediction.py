"""Pure shared prediction/gate seam; no database, provider, credentials or effects."""

import math
from dataclasses import dataclass
from typing import Any, Protocol

from probation.core.enums import GateDecision
from probation.core.types import Features, Situation
from probation.engine.caps import get_action_loss, is_recallable
from probation.engine.gate import compute_audit_draw, decide_gate
from probation.packs.descriptor import PackDescriptor


class PredictPolicy(Protocol):
    policy_version: str

    def predict(
        self, features: dict[str, Any]
    ) -> tuple[str, float, dict[str, float], list[str]]: ...


class NoveltyScore(Protocol):
    def score(self, text: str) -> tuple[bool, float]: ...


@dataclass(frozen=True, slots=True)
class PredictionSnapshot:
    policy: PredictPolicy
    novelty: NoveltyScore
    audit_seed: str
    audit_fraction: float
    attention_cost: float = 1.0


@dataclass(frozen=True, slots=True)
class Prediction:
    action: str
    p_max: float
    probs: dict[str, float]
    reasons: tuple[str, ...]
    class_key: str
    cap: int
    novel: bool
    novelty: float
    gate: GateDecision
    audit_holdout: bool


def policy_inputs(features: Features) -> dict[str, Any]:
    values = {
        k: v
        for k, v in {**features.deterministic, **(features.reader or {})}.items()
        if not k.startswith("__")
    }
    tokens = features.deterministic.get("__name_tokens")
    if isinstance(tokens, str):
        values["name_tokens"] = tokens.split()
    return values


def evaluate_prediction(
    situation: Situation,
    features: Features,
    pack: PackDescriptor,
    snapshot: PredictionSnapshot,
    *,
    licence_level: int,
    restriction_cap: int = 3,
) -> Prediction:
    """Adapters supply bounded features/frozen fitted state and current derived authority.

    restriction_cap is a primitive restriction, never web text or a probability input.
    The policy prediction is computed identically with and without that restriction.
    """
    det_ok = bool(features.deterministic.get("__deterministic_ok", True))
    required = bool(features.deterministic.get("__reader_required", pack.reader_spec() is not None))
    reader_ok = features.reader_ok
    if required:
        from pydantic import ValidationError

        from probation.llm.catalog import resolve_job
        from probation.llm.reader import READER_JOBS

        key = READER_JOBS.get(situation.pack)
        try:
            if key is None or features.reader is None:
                raise ValueError("missing_required_form")
            resolve_job(*key).output_model().model_validate(features.reader, strict=True)
        except (ValueError, ValidationError):
            reader_ok = False
    budget_ok = bool(features.deterministic.get("__budget_ok", True))
    values = policy_inputs(features)
    action, p, probs, reasons = snapshot.policy.predict(values)
    reasons = list(reasons)
    reader_failure_reason = features.deterministic.get("__reader_failure_reason")
    if reader_failure_reason and (not det_ok or not reader_ok):
        reasons.append(str(reader_failure_reason))
    catalogue = {item.type for item in pack.action_catalog()}
    from probation.core.actions import parse_action

    try:
        parsed = parse_action(action)
        if not parsed.is_noop and parsed.type not in catalogue:
            raise ValueError("pack_action_not_supported")
        if (
            not math.isfinite(p)
            or not 0 <= p <= 1
            or any(not math.isfinite(v) or not 0 <= v <= 1 for v in probs.values())
            or not math.isclose(sum(probs.values()), 1.0, abs_tol=1e-6)
        ):
            raise ValueError("invalid_distribution")
    except ValueError:
        action, p, probs = "ABSTAIN", 0.0, {}
        det_ok = False
        reasons.append("prediction_invalid")
    if required and not reader_ok:
        action, p, probs = "ABSTAIN", 0.0, {}
        reasons.append("featurization_failed")
    try:
        novel, distance = snapshot.novelty.score(situation.redacted_text or "")
        if not math.isfinite(distance):
            raise ValueError("invalid_novelty")
    except (ValueError, RuntimeError):
        novel, distance, det_ok = True, 1.0, False
        reasons.append("novelty_unavailable")
    try:
        class_key = pack.class_key(situation, features)
        cap = min(pack.level_cap(action, situation, features), max(0, min(3, restriction_cap)))
        hands_off = situation.hands_off_reason or pack.hands_off(situation)
    except (ValueError, TypeError, KeyError):
        class_key, cap, hands_off, det_ok = (
            f"{situation.pack}|unknown",
            0,
            situation.hands_off_reason,
            False,
        )
    result = decide_gate(
        action=action,
        p=p,
        novel=novel,
        licence_level=licence_level,
        cap=cap,
        hands_off=hands_off,
        reader_required=required,
        reader_ok=reader_ok,
        deterministic_ok=det_ok,
        budget_ok=budget_ok,
        loss=get_action_loss(action),
        recallable=is_recallable(action),
        attention_cost=snapshot.attention_cost,
        audit_draw=compute_audit_draw(situation.id, seed=snapshot.audit_seed),
        audit_fraction=snapshot.audit_fraction,
    )
    if result.reason:
        reasons.append(result.reason)
    return Prediction(
        action,
        p,
        probs,
        tuple(reasons),
        class_key,
        cap,
        novel,
        distance,
        result.decision,
        result.audit_holdout,
    )
