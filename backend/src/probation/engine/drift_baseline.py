"""Pure posterior error at a real permission change, sharing the golden prior."""

from probation.engine.evidence import ClassStats, posterior_parameters


def posterior_error(
    stats: dict[tuple[str, str], ClassStats],
    pair: tuple[str, str],
    level: int,
    *,
    kappa: float,
    default: float,
) -> float:
    stat = stats.get(pair)
    if stat is None:
        return default
    k, n, parent_mean = stat.k_all, stat.n_all, None
    if level >= 2:
        k, n = stat.k_strong, stat.n_strong
        parent = pair[0].rsplit("|", 1)[0] if "|" in pair[0] else pair[0]
        siblings = [
            value
            for (key, action), value in stats.items()
            if action == pair[1] and (key.rsplit("|", 1)[0] if "|" in key else key) == parent
        ]
        parent_n = sum(value.n_strong for value in siblings)
        parent_k = sum(value.k_strong for value in siblings)
        if parent_n >= 20 and parent != pair[0]:
            parent_mean = (parent_k + 1.0) / (parent_n + 2.0)
    if not n:
        return default
    alpha, beta = posterior_parameters(k, n, parent_mean, kappa)
    return 1.0 - alpha / (alpha + beta)
