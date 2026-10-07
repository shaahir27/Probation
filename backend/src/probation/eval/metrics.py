"""Core evaluation metrics functions.

Authority: docs/EVALUATION_PLAN.md section 3.
"""


def compute_agreement(predictions: list[str], ground_truth: list[str]) -> float:
    """Compute empirical agreement rate between predictions and human ground truth."""
    if not predictions or len(predictions) != len(ground_truth):
        return 0.0
    matches = sum(1 for p, g in zip(predictions, ground_truth, strict=True) if p == g)
    return float(matches) / float(len(predictions))
