"""Policy training (logistic regression) and action prediction.

Authority: docs/ENGINE_SPEC.md section 4.
"""


class Policy:
    """Local, calibrated logistic regression policy."""

    def __init__(self, class_key: str) -> None:
        self.class_key = class_key

    def predict(self, feature_vector: list[float]) -> tuple[str, dict[str, float]]:
        """Predict top action and calibrated probability distribution."""
        return ("ABSTAIN", {"ABSTAIN": 1.0})
