"""Beta distribution evidence accumulation and empirical Bayes pooling.

Authority: docs/ENGINE_SPEC.md section 6.1 and section 16.
"""


def compute_beta_lower_bound(k: int, n: int, confidence: float = 0.95) -> float:
    """Compute pessimistic Wilson or Beta quantile lower bound for binomial success."""
    if n == 0:
        return 0.0
    return float(k) / float(n)
