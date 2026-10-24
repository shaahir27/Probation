"""Pure fitted-feature population comparison; callers provide bounded observations."""

import bisect
import math
from typing import Any

from probation.engine.drift import compute_psi
from probation.engine.policy import Policy


def selected_features(policy: Policy) -> list[str]:
    if not policy.is_fitted or policy.model is None or not policy.encoder.fitted:
        return []
    weights = policy.model.coef_
    columns = list(policy.encoder.numeric_means) + [
        key for key, levels in policy.encoder.categorical_levels.items() for _ in levels
    ]
    if weights.ndim != 2 or weights.shape[1] != len(columns):
        raise ValueError("unaligned_policy_features")
    scores: dict[str, float] = {}
    for index, key in enumerate(columns):
        score = max(float(abs(row[index])) for row in weights)
        if not math.isfinite(score):
            raise ValueError("invalid_policy_coefficients")
        scores[key] = max(scores.get(key, 0.0), score)
    return sorted(scores, key=lambda key: (-scores[key], key))[:5]


def _numeric(
    reference: list[Any], current: list[Any]
) -> tuple[list[float], list[float], dict[str, Any]]:
    values = reference + current
    if any(
        value is not None
        and (not isinstance(value, (int, float, bool)) or not math.isfinite(float(value)))
        for value in values
    ):
        raise ValueError("invalid_numeric_population")
    known = sorted(float(value) for value in reference if value is not None)
    if not known:
        # Missing reference is a real bin; newly known values remain detectable.
        buckets = [0 if value is None else 1 for value in values]
        metadata: dict[str, Any] = {"kind": "numeric_missing_reference", "bins": []}
        size = 2
    elif known[0] == known[-1]:
        buckets = [2 if value is None else 0 if float(value) == known[0] else 1 for value in values]
        metadata = {"kind": "numeric_constant", "value": known[0], "bins": []}
        size = 3
    else:
        cutoffs = sorted({known[int(len(known) * index / 10)] for index in range(1, 10)})
        buckets = [
            len(cutoffs) + 1 if value is None else bisect.bisect_right(cutoffs, float(value))
            for value in values
        ]
        metadata = {"kind": "numeric", "bins": cutoffs}
        size = len(cutoffs) + 2
    ref = [float(buckets[: len(reference)].count(index)) for index in range(size)]
    cur = [float(buckets[len(reference) :].count(index)) for index in range(size)]
    return ref, cur, metadata


def _categorical(
    reference: list[Any], current: list[Any]
) -> tuple[list[float], list[float], dict[str, Any]]:
    if any(value is not None and not isinstance(value, str) for value in reference + current):
        raise ValueError("invalid_categorical_population")
    categories = sorted({value for value in reference + current if value is not None})
    bins = [*categories, None]
    return (
        [float(reference.count(value)) for value in bins],
        [float(current.count(value)) for value in bins],
        {"kind": "categorical", "bins": bins},
    )


def assess_shift(
    policy: Policy | None,
    reference: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    threshold: float = 0.25,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "policy_unavailable",
        "alarm": None,
        "reference_n": len(reference),
        "current_n": len(current),
        "features": {},
        "max_psi": None,
    }
    if policy is None or not policy.is_fitted:
        return result
    result["policy_version"] = policy.policy_version
    if len(reference) < 20 or len(current) < 10:
        return {**result, "status": "insufficient_data"}
    try:
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("invalid_shift_threshold")
        selected = selected_features(policy)
        if not selected:
            return result
        if policy.family == "file_destination":
            reference = [policy.vocabulary.row(row) for row in reference]
            current = [policy.vocabulary.row(row) for row in current]
        features = {}
        for key in selected:
            reference_values = [row.get(key) for row in reference]
            current_values = [row.get(key) for row in current]
            ref, cur, metadata = (
                _numeric(reference_values, current_values)
                if key in policy.encoder.numeric_means
                else _categorical(reference_values, current_values)
            )
            features[key] = {
                **metadata,
                "psi": compute_psi(ref, cur),
                "reference_counts": ref,
                "current_counts": cur,
            }
        maximum = max(item["psi"] for item in features.values())
        return {
            **result,
            "status": "available",
            "alarm": maximum > threshold,
            "features": features,
            "max_psi": maximum,
            "threshold": threshold,
        }
    except (ValueError, TypeError, OverflowError):
        return {**result, "status": "invalid_features"}
