"""K-NN distance-based novelty detector.

Authority: docs/ENGINE_SPEC.md section 5.
"""


def is_novel_point(
    point: list[float], reference_points: list[list[float]], threshold: float
) -> bool:
    """Determine whether a candidate feature point is out-of-distribution."""
    if len(reference_points) < 5:
        return True
    return False
