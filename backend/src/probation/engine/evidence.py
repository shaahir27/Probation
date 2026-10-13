"""Beta distribution evidence accumulation and empirical Bayes pooling.

Authority: docs/ENGINE_SPEC.md section 6.2 and section 16.
"""

import scipy.stats


def lower_bound(
    k: int,
    n: int,
    parent_mean: float | None = None,
    kappa: float = 10.0,
    q: float = 0.05,
) -> float:
    """Compute lower-bound success rate using Beta quantile with optional empirical Bayes pooling.

    Authority: docs/ENGINE_SPEC.md section 6.2 and section 16.
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"Invalid success counts: k={k}, n={n}")

    if n == 0:
        return 0.0

    if parent_mean is None:
        a0 = 1.0
        b0 = 1.0
    else:
        p = min(max(parent_mean, 0.01), 0.99)
        a0 = max(1.0, kappa * p)
        b0 = max(1.0, kappa * (1.0 - p))  # never below 1: pooling cannot assert near-perfection

    a = a0 + k
    b = b0 + (n - k)
    return float(scipy.stats.beta.ppf(q, a, b))


# Alias for compatibility
compute_beta_lower_bound = lower_bound
