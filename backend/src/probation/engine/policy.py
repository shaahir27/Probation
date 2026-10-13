"""Policy training (logistic regression) and action prediction.

Authority: docs/ENGINE_SPEC.md section 4.
"""

import hashlib
from datetime import datetime
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression

from probation.config import settings
from probation.core.hashing import canonical_json
from probation.engine.features import FeatureEncoder


class Policy:
    """Calibrated, time-weighted multinomial logistic regression policy per family."""

    def __init__(
        self,
        family: str,
        cold_start_min: int | None = None,
        train_half_life_days: float | None = None,
    ) -> None:
        self.family = family
        self.cold_start_min = cold_start_min or settings.l1_min_n  # fallback to configured minimum
        self.train_half_life_days = (
            train_half_life_days or settings.train_half_life_days
            if hasattr(settings, "train_half_life_days")
            else 90.0
        )
        self.encoder = FeatureEncoder()
        self.model: LogisticRegression | None = None
        self.temperature: float = 1.0
        self.policy_version: str = "cold_start"
        self.is_fitted: bool = False
        self.classes: list[str] = []

    def fit(
        self,
        features_list: list[dict[str, Any]],
        observed_actions: list[str],
        timestamps: list[str],
        as_of: str,
    ) -> "Policy":
        """Fit policy with time-decay weighting and temperature calibration."""
        distinct_actions = sorted(set(observed_actions))

        # Cold start check per ENGINE_SPEC.md section 4
        if len(features_list) < self.cold_start_min or len(distinct_actions) < 2:
            self.model = None
            self.is_fitted = False
            self.policy_version = "cold_start"
            self.classes = distinct_actions
            return self

        # 1. Fit feature encoder & transform
        self.encoder.fit(features_list)
        x_train = np.array(self.encoder.transform(features_list), dtype=np.float64)
        y_train = np.array(observed_actions)

        # 2. Compute time-decay sample weights
        as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        weights = np.zeros(len(timestamps), dtype=np.float64)
        for i, ts in enumerate(timestamps):
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_days = max(0.0, (as_of_dt - ts_dt).total_seconds() / 86400.0)
            weights[i] = 0.5 ** (age_days / self.train_half_life_days)

        # Normalize weights so mean is 1.0
        weights = weights / (np.mean(weights) + 1e-12)

        # 3. Fit Logistic Regression
        clf = LogisticRegression(solver="lbfgs", C=1.0, max_iter=1000)
        clf.fit(x_train, y_train, sample_weight=weights)
        self.model = clf
        self.classes = [str(c) for c in clf.classes_]

        # 4. Temperature scaling calibration
        self.temperature = self._fit_temperature(clf, x_train, y_train)

        # 5. Compute version hash
        version_payload = {
            "family": self.family,
            "classes": self.classes,
            "coef": [float(v) for v in clf.coef_.flatten()[:20]],
            "intercept": [float(v) for v in clf.intercept_.flatten()],
            "temperature": self.temperature,
        }
        self.policy_version = hashlib.sha256(
            canonical_json(version_payload).encode("utf-8")
        ).hexdigest()[:12]
        self.is_fitted = True
        return self

    def _fit_temperature(
        self,
        clf: LogisticRegression,
        x_mat: np.ndarray,
        y: np.ndarray,
    ) -> float:
        """Fit single calibration temperature in [0.5, 5.0] if >= 100 rows."""
        if len(y) < 100:
            return 1.0

        p_raw = clf.predict_proba(x_mat)
        p_raw = np.clip(p_raw, 1e-12, 1.0 - 1e-12)
        y_indices = np.array([self.classes.index(str(label)) for label in y])

        def nll(temp: float) -> float:
            # Scaled log-probabilities
            log_p = np.log(p_raw) / temp
            exp_p = np.exp(log_p - np.max(log_p, axis=1, keepdims=True))
            probs = exp_p / np.sum(exp_p, axis=1, keepdims=True)
            chosen_probs = np.clip(probs[np.arange(len(y)), y_indices], 1e-12, 1.0)
            return float(-np.mean(np.log(chosen_probs)))

        res = minimize_scalar(nll, bounds=(0.5, 5.0), method="bounded")
        if res.success:
            return float(np.clip(res.x, 0.5, 5.0))
        return 1.0

    def predict(
        self, feature_dict: dict[str, Any]
    ) -> tuple[str, float, dict[str, float], list[str]]:
        """Predict action, max probability, distribution, and reasons.

        Returns (action, p_max, probs_dict, reasons).
        """
        if not self.is_fitted or self.model is None:
            return ("ABSTAIN", 1.0, {"ABSTAIN": 1.0}, ["cold_start"])

        # Transform feature dictionary
        x_vec = np.array([self.encoder.transform_row(feature_dict)], dtype=np.float64)
        p_raw = self.model.predict_proba(x_vec)[0]

        # Apply temperature scaling
        log_p = np.log(np.maximum(p_raw, 1e-12)) / self.temperature
        exp_p = np.exp(log_p - np.max(log_p))
        p_cal = exp_p / np.sum(exp_p)

        top_idx = int(np.argmax(p_cal))
        top_action = self.classes[top_idx]
        p_max = float(p_cal[top_idx])
        probs_dict = {str(cls): float(p_cal[i]) for i, cls in enumerate(self.classes)}

        return (top_action, p_max, probs_dict, [])
