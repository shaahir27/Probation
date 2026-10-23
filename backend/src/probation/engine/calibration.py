"""Five expanding chronological validation blocks, with delayed-label purging."""

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize_scalar

from probation.core.clock import timestamp_key

Matrix = NDArray[np.float64]
FoldPredictor = Callable[[list[int], list[int], str], tuple[Matrix, list[int | None]]]


def calibrated(raw: Matrix, temperature: float) -> Matrix:
    if not np.isfinite(temperature) or temperature <= 0 or not np.isfinite(raw).all():
        raise ValueError("invalid_probabilities")
    if (raw < 0).any() or not np.allclose(raw.sum(axis=-1), 1.0):
        raise ValueError("invalid_probability_distribution")
    logits = np.log(np.clip(raw, 1e-12, 1.0)) / temperature
    exponent = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
    return np.asarray(exponent / exponent.sum(axis=-1, keepdims=True), dtype=np.float64)


def fit_temperature(
    occurred: list[str], known: list[str], predictor: FoldPredictor
) -> tuple[float, dict[str, Any]]:
    report: dict[str, Any] = {"algorithm": "purged-expanding-5-v1", "folds": [], "usable_rows": 0}
    if len(occurred) < 100:
        return 1.0, {**report, "status": "insufficient_rows"}
    groups = sorted(set(occurred), key=timestamp_key)
    if len(groups) < 6:
        return 1.0, {**report, "status": "insufficient_time_groups"}
    # Split timestamp groups, never individual rows at the same instant.
    blocks = np.array_split(np.arange(len(groups)), 6)
    predictions: list[tuple[Matrix, list[int]]] = []
    for block in blocks[1:]:
        start, end = groups[int(block[0])], groups[int(block[-1])]
        train = [
            i
            for i, t in enumerate(occurred)
            if timestamp_key(t) < timestamp_key(start)
            and timestamp_key(known[i]) <= timestamp_key(start)
        ]
        valid = [
            i
            for i, t in enumerate(occurred)
            if timestamp_key(start) <= timestamp_key(t) <= timestamp_key(end)
        ]
        fold: dict[str, Any] = {
            "validation_start": start,
            "validation_end": end,
            "training_indices": train,
            "validation_indices": valid,
            "max_train_known_at": max((known[i] for i in train), key=timestamp_key, default=None),
            "max_train_occurred_at": max(
                (occurred[i] for i in train), key=timestamp_key, default=None
            ),
        }
        try:
            raw, indices = predictor(train, valid, start)
            keep = [i for i, label in enumerate(indices) if label is not None]
            targets = [value for i in keep if (value := indices[i]) is not None]
            fold.update(status="ok", usable_rows=len(keep), unseen_labels=len(valid) - len(keep))
            if keep:
                probabilities = raw[keep]
                calibrated(probabilities, 1.0)  # validate before optimization
                predictions.append((probabilities, targets))
                report["usable_rows"] += len(keep)
        except (ValueError, FloatingPointError):
            fold.update(status="insufficient_or_invalid_fold", usable_rows=0)
        report["folds"].append(fold)
    if not predictions:
        return 1.0, {**report, "status": "no_usable_predictions"}

    def nll(temperature: float) -> float:
        loss = 0.0
        for raw, targets in predictions:
            p = calibrated(raw, temperature)
            loss -= float(np.log(np.clip(p[np.arange(len(targets)), targets], 1e-12, 1.0)).sum())
        return loss / int(report["usable_rows"])

    try:
        result = minimize_scalar(nll, bounds=(0.5, 5.0), method="bounded")
    except (ValueError, FloatingPointError, RuntimeError):
        return 1.0, {**report, "status": "optimizer_failed"}
    if not result.success or not np.isfinite(result.x) or not np.isfinite(result.fun):
        return 1.0, {**report, "status": "optimizer_failed"}
    return float(result.x), {**report, "status": "calibrated", "held_out_nll": float(result.fun)}
