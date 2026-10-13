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


class FeatureEncoder:
    """Standardizes numeric features and one-hot encodes categoricals for policy training."""

    def __init__(self, featurizer_version: str = "v1") -> None:
        self.featurizer_version = featurizer_version
        self.fitted = False
        self.numeric_means: dict[str, float] = {}
        self.numeric_scales: dict[str, float] = {}
        self.categorical_levels: dict[str, list[str]] = {}
        self.encoded_feature_names: list[str] = []

    def fit(self, rows: list[dict[str, Any]]) -> "FeatureEncoder":
        """Fit scaler on training numeric rows and discover categorical levels."""
        if not rows:
            self.fitted = True
            return self

        # Discover all unique feature keys
        all_keys = sorted({k for r in rows for k in r.keys()})

        self.numeric_means = {}
        self.numeric_scales = {}
        self.categorical_levels = {}
        self.encoded_feature_names = []

        for key in all_keys:
            sample_vals = [r[key] for r in rows if key in r and r[key] is not None]
            if not sample_vals:
                continue

            first_val = sample_vals[0]
            if isinstance(first_val, str):
                # Categorical column
                levels = sorted({str(v) for v in sample_vals})
                self.categorical_levels[key] = levels
                for level in levels:
                    self.encoded_feature_names.append(f"{key}={level}")
            else:
                # Numeric column (int, float, bool)
                num_vals: list[float] = [float(v) for v in sample_vals]
                mean_val = sum(num_vals) / len(num_vals)
                variance = sum((v - mean_val) ** 2 for v in num_vals) / len(num_vals)
                std_val = math.sqrt(variance)
                scale_val = std_val if std_val > 1e-6 else 1.0

                self.numeric_means[key] = mean_val
                self.numeric_scales[key] = scale_val
                self.encoded_feature_names.append(key)

        self.fitted = True
        return self

    def transform_row(self, row: dict[str, Any]) -> list[float]:
        """Transform a feature dict into a standardized float vector."""
        if not self.fitted:
            raise RuntimeError("FeatureEncoder must be fitted before transforming rows.")

        vector: list[float] = []

        for key in sorted(self.numeric_means.keys()):
            val = row.get(key)
            if val is None:
                # Impute missing numeric with 0.0 (the mean after standardization)
                vector.append(0.0)
            else:
                num = float(val)
                mean = self.numeric_means[key]
                scale = self.numeric_scales[key]
                vector.append((num - mean) / scale)

        for key in sorted(self.categorical_levels.keys()):
            val = str(row.get(key, ""))
            for level in self.categorical_levels[key]:
                vector.append(1.0 if val == level else 0.0)

        return vector

    def transform(self, rows: list[dict[str, Any]]) -> list[list[float]]:
        """Transform multiple feature dicts into float vectors."""
        return [self.transform_row(r) for r in rows]
