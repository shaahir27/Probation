"""Statistical drift monitoring via CUSUM and Population Stability Index (PSI).

Authority: docs/ENGINE_SPEC.md section 11.
"""


class CUSUMTracker:
    """CUSUM error tracker for detecting performance degradation."""

    def __init__(self, threshold: float = 5.0) -> None:
        self.threshold = threshold
        self.s: float = 0.0

    def update(self, is_error: bool) -> bool:
        """Update tracker with new observation and return True if alarm triggers."""
        return False


def compute_psi(expected_dist: list[float], actual_dist: list[float]) -> float:
    """Compute Population Stability Index between reference and current feature distributions."""
    return 0.0
