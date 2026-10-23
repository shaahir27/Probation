"""Feature encoding, standardization, and featurization hash computation.

Authority: docs/ENGINE_SPEC.md section 3.
"""

import hashlib
import math
from typing import Any

from probation.core.hashing import canonical_json


def compute_features_hash(
    deterministic_data: dict[str, Any],
    reader_data: dict[str, Any] | None = None,
    featurizer_version: str = "v1",
) -> str:
    """Compute sha256 hash across normalized feature dictionaries per ENGINE_SPEC.md section 3."""
    combined = canonical_json(
        {
            "det": deterministic_data,
            "reader": reader_data or {},
            "ver": featurizer_version,
        }
    )
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


class FeatureValidationError(ValueError):
    """Invalid numeric/categorical input; callers must fail closed."""


class FeatureEncoder:
    """One ordered fitted column specification for names and values."""

    def __init__(self, featurizer_version: str = "v1") -> None:
        self.featurizer_version = featurizer_version
        self._reset()

    def _reset(self) -> None:
        self.fitted = False
        self.numeric_means: dict[str, float] = {}
        self.numeric_scales: dict[str, float] = {}
        self.categorical_levels: dict[str, list[str]] = {}
        self.encoded_feature_names: list[str] = []

    def fit(self, rows: list[dict[str, Any]]) -> "FeatureEncoder":
        self._reset()
        try:
            for key in sorted({key for row in rows for key in row}):
                values = [r[key] for r in rows if r.get(key) is not None]
                if not values:
                    continue
                if all(isinstance(v, str) for v in values):
                    self.categorical_levels[key] = sorted(set(values))
                elif all(isinstance(v, (int, float, bool)) for v in values):
                    numbers = [float(v) for v in values]
                    if not all(math.isfinite(v) for v in numbers):
                        raise FeatureValidationError("nonfinite_feature")
                    mean = sum(numbers) / len(numbers)
                    scale = math.sqrt(sum((v - mean) ** 2 for v in numbers) / len(numbers))
                    if not math.isfinite(mean) or not math.isfinite(scale):
                        raise FeatureValidationError("nonfinite_scaler")
                    self.numeric_means[key] = mean
                    self.numeric_scales[key] = scale if scale > 1e-6 else 1.0
                else:
                    raise FeatureValidationError("incompatible_feature_types")
            self.encoded_feature_names = list(self.numeric_means) + [
                f"{key}={level}"
                for key, levels in self.categorical_levels.items()
                for level in levels
            ]
            self.fitted = True
            return self
        except (ValueError, TypeError, OverflowError):
            self._reset()
            raise

    def transform_row(self, row: dict[str, Any]) -> list[float]:
        if not self.fitted:
            raise FeatureValidationError("encoder_unfitted")
        vector: list[float] = []
        for key, mean in self.numeric_means.items():
            value = row.get(key)
            if value is None:
                vector.append(0.0)
            elif not isinstance(value, (int, float, bool)) or not math.isfinite(float(value)):
                raise FeatureValidationError("invalid_numeric_feature")
            else:
                vector.append((float(value) - mean) / self.numeric_scales[key])
        for key, levels in self.categorical_levels.items():
            value = row.get(key)
            if value is not None and not isinstance(value, str):
                raise FeatureValidationError("invalid_categorical_feature")
            vector.extend(1.0 if value == level else 0.0 for level in levels)
        if not all(math.isfinite(v) for v in vector):
            raise FeatureValidationError("nonfinite_encoded_feature")
        return vector

    def transform(self, rows: list[dict[str, Any]]) -> list[list[float]]:
        return [self.transform_row(row) for row in rows]

    def state(self) -> dict[str, Any]:
        return {
            "version": self.featurizer_version,
            "columns": self.encoded_feature_names,
            "means": self.numeric_means,
            "scales": self.numeric_scales,
            "categories": self.categorical_levels,
        }
