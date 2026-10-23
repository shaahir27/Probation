"""Time-bounded family policy with purged chronological calibration (WP4)."""

import hashlib
import json
import math
import warnings
from importlib.metadata import version
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from probation.core.clock import format_timestamp, parse_timestamp, timestamp_key
from probation.core.hashing import canonical_json
from probation.core.training_labels import valid_label
from probation.engine.calibration import calibrated, fit_temperature
from probation.engine.features import FeatureEncoder
from probation.engine.vocabulary import FileVocabulary


class Policy:
    """Compatibility fit/predict API; optional metadata supports bounded cohorts."""

    def __init__(
        self,
        family: str,
        cold_start_min: int | None = None,
        train_half_life_days: float | None = None,
        files_topk: int = 15,
    ) -> None:
        self.family = family
        self.cold_start_min = 200 if cold_start_min is None else cold_start_min
        self.train_half_life_days = 90.0 if train_half_life_days is None else train_half_life_days
        self.files_topk = files_topk
        if (
            type(self.cold_start_min) is not int
            or self.cold_start_min < 1
            or not math.isfinite(self.train_half_life_days)
            or self.train_half_life_days <= 0
            or type(files_topk) is not int
            or files_topk < 1
        ):
            raise ValueError("invalid_policy_configuration")
        self._reset()

    def _reset(self) -> None:
        self.encoder = FeatureEncoder()
        self.model: LogisticRegression | None = None
        self.temperature = 1.0
        self.policy_version = "cold_start"
        self.policy_digest = ""
        self.is_fitted = False
        self.classes: list[str] = []
        self.vocabulary = FileVocabulary()
        self.calibration: dict[str, Any] = {"status": "cold_start", "folds": [], "usable_rows": 0}
        self.provenance: dict[str, Any] = {}
        self.cohort_digest = ""
        self.as_of = ""

    def _row(self, row: dict[str, Any], vocabulary: FileVocabulary) -> dict[str, Any]:
        return vocabulary.row(row) if self.family == "file_destination" else dict(row)

    def _fit_model(
        self, rows: list[dict[str, Any]], labels: list[str], times: list[str], as_of: str
    ) -> tuple[FeatureEncoder, LogisticRegression, FileVocabulary]:
        vocabulary = (
            FileVocabulary.fit(rows, labels, self.files_topk)
            if self.family == "file_destination"
            else FileVocabulary()
        )
        targets = (
            [vocabulary.label(a) for a in labels] if self.family == "file_destination" else labels
        )
        if len(set(targets)) < 2:
            raise ValueError("insufficient_classes")
        encoder = FeatureEncoder().fit([self._row(r, vocabulary) for r in rows])
        x = np.asarray(
            encoder.transform([self._row(r, vocabulary) for r in rows]), dtype=np.float64
        )
        cutoff = parse_timestamp(as_of)
        ages = [(cutoff - parse_timestamp(t)).total_seconds() / 86400 for t in times]
        weights = np.asarray([0.5 ** (age / self.train_half_life_days) for age in ages])
        if not np.isfinite(weights).all() or not weights.any():
            raise ValueError("invalid_training_weights")
        clf = LogisticRegression(solver="lbfgs", C=1.0, max_iter=1000)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", ConvergenceWarning)
                clf.fit(x, np.asarray(targets), sample_weight=weights)
        except ConvergenceWarning as exc:
            raise ValueError("model_did_not_converge") from exc
        if not np.isfinite(clf.coef_).all() or not np.isfinite(clf.intercept_).all():
            raise ValueError("invalid_fitted_model")
        return encoder, clf, vocabulary

    def fit(
        self,
        features_list: list[dict[str, Any]],
        observed_actions: list[str],
        timestamps: list[str],
        as_of: str,
        *,
        known_at: list[str] | None = None,
        situation_ids: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> "Policy":
        self._reset()
        n = len(features_list)
        known = timestamps if known_at is None else known_at
        ids = [str(i) for i in range(n)] if situation_ids is None else situation_ids
        if len(observed_actions) != n or len(timestamps) != n or len(known) != n or len(ids) != n:
            raise ValueError("unaligned_training_rows")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_training_identity")
        cutoff = timestamp_key(as_of)
        occurred = [format_timestamp(t) for t in timestamps]
        answers = [format_timestamp(t) for t in known]
        if any(timestamp_key(t) > cutoff for t in occurred + answers):
            raise ValueError("future_training_row")
        if any(timestamp_key(k) < timestamp_key(t) for t, k in zip(occurred, answers, strict=True)):
            raise ValueError("outcome_precedes_situation")
        if any(
            not a or a in {"ABSTAIN", "UNDO", "OVERRIDE", "REJECT", "OTHER"}
            for a in observed_actions
        ):
            raise ValueError("invalid_training_label")
        if any(not valid_label(self.family, action) for action in observed_actions):
            raise ValueError("unsupported_family_training_label")
        order = sorted(range(n), key=lambda i: (timestamp_key(occurred[i]), ids[i]))
        rows = [dict(features_list[i]) for i in order]
        labels = [observed_actions[i] for i in order]
        times = [occurred[i] for i in order]
        known_times = [answers[i] for i in order]
        sorted_ids = [ids[i] for i in order]
        if n < self.cold_start_min or len(set(labels)) < 2:
            return self
        if self.family == "file_destination":
            vocabulary = FileVocabulary.fit(rows, labels, self.files_topk)
            if len({vocabulary.label(a) for a in labels}) < 2:
                return self

        def fold_predict(
            train: list[int], valid: list[int], start: str
        ) -> tuple[NDArray[np.float64], list[int | None]]:
            encoder, clf, vocabulary = self._fit_model(
                [rows[i] for i in train],
                [labels[i] for i in train],
                [times[i] for i in train],
                start,
            )
            x = np.asarray(
                encoder.transform([self._row(rows[i], vocabulary) for i in valid]), dtype=np.float64
            )
            classes = [str(a) for a in clf.classes_]
            targets = [
                vocabulary.label(labels[i]) if self.family == "file_destination" else labels[i]
                for i in valid
            ]
            return np.asarray(clf.predict_proba(x), dtype=np.float64), [
                classes.index(a) if a in classes else None for a in targets
            ]

        try:
            self.temperature, self.calibration = fit_temperature(times, known_times, fold_predict)
            self.encoder, self.model, self.vocabulary = self._fit_model(rows, labels, times, as_of)
            self.classes = [str(a) for a in self.model.classes_]
            self.provenance = dict(provenance or {})
            self.as_of = format_timestamp(as_of)
            self.cohort_digest = hashlib.sha256(
                canonical_json(
                    {
                        "ids": sorted_ids,
                        "rows": rows,
                        "labels": labels,
                        "occurred": times,
                        "known": known_times,
                    }
                ).encode()
            ).hexdigest()
            self.policy_digest = self.state_digest()
            self.policy_version = self.policy_digest[:12]
            self.is_fitted = True
        except (ValueError, TypeError, ArithmeticError, ConvergenceWarning):
            self._reset()
            raise
        return self

    def state_digest(self) -> str:
        if self.model is None:
            raise ValueError("policy_unfitted")
        payload = {
            "algorithm": "wp4-logistic-v1",
            "family": self.family,
            "classes": self.classes,
            "coef": self.model.coef_.tolist(),
            "intercept": self.model.intercept_.tolist(),
            "encoder": self.encoder.state(),
            "temperature": self.temperature,
            "calibration": self.calibration,
            "folders": list(self.vocabulary.folders),
            "tokens": list(self.vocabulary.tokens),
            "provenance": self.provenance,
            "cutoff": self.as_of,
            "cohort": self.cohort_digest,
            "half_life": self.train_half_life_days,
            "cold_start": self.cold_start_min,
            "topk": self.files_topk,
            "solver": {"name": "lbfgs", "C": 1.0, "max_iter": 1000},
            "versions": {p: version(p) for p in ("numpy", "scipy", "scikit-learn")},
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

    def predict(
        self, feature_dict: dict[str, Any]
    ) -> tuple[str, float, dict[str, float], list[str]]:
        if not self.is_fitted or self.model is None:
            return "ABSTAIN", 1.0, {"ABSTAIN": 1.0}, ["cold_start"]
        x = np.asarray(
            [self.encoder.transform_row(self._row(feature_dict, self.vocabulary))], dtype=np.float64
        )
        p = calibrated(np.asarray(self.model.predict_proba(x), dtype=np.float64), self.temperature)[
            0
        ]
        index = int(np.argmax(p))
        action = self.classes[index]
        probs = {a: float(p[i]) for i, a in enumerate(self.classes)}
        return (
            "ABSTAIN" if action == "OTHER" else action,
            float(p[index]),
            probs,
            ["other_folder"] if action == "OTHER" else [],
        )

    def explain(self, row: dict[str, Any]) -> dict[str, Any]:
        if not self.is_fitted or self.model is None:
            return {"available": False, "reason": "cold_start"}
        action, _, probs, _ = self.predict(row)
        selected = max(self.classes, key=lambda a: probs[a])
        x = self.encoder.transform_row(self._row(row, self.vocabulary))
        index = self.classes.index(selected)
        binary = len(self.classes) == 2
        coefficients = self.model.coef_[0 if binary else index]
        sign = -1.0 if binary and index == 0 else 1.0
        intercept = sign * float(self.model.intercept_[0 if binary else index])
        contributions: list[dict[str, Any]] = [
            {"feature": name, "value": value, "contribution": sign * float(coef) * value}
            for name, value, coef in zip(
                self.encoder.encoded_feature_names, x, coefficients, strict=True
            )
        ]
        return {
            "available": True,
            "action": action,
            "model_class": selected,
            "semantics": "signed_binary_margin" if binary else "class_logit",
            "intercept": intercept,
            "contributions": contributions,
            "logit": intercept + sum(c["contribution"] for c in contributions),
            "policy_version": self.policy_version,
        }
