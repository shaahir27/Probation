"""Beta distribution evidence accumulation and empirical Bayes pooling.

Authority: docs/CONTRACT.md invariants I-10, I-11, I-12 and docs/ENGINE_SPEC.md section 6.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import scipy.stats

from probation.config import settings
from probation.core.actions import InvalidAction, parse_action
from probation.core.clock import format_timestamp
from probation.core.history import HistoryView
from probation.db.access import AccessError, Role, RoleAccess
from probation.db.guards import ReadConnection

EVIDENCE_WINDOW_DAYS_DEFAULT: Final[int] = 180
RECENT_WINDOW_DAYS_DEFAULT: Final[int] = 30
POOLING_KAPPA_DEFAULT: Final[float] = 10.0
LB_QUANTILE_DEFAULT: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class ClassStats:
    """Computed evidence statistics for a (class_key, action) pair."""

    class_key: str
    action: str
    as_of: str
    n_strong: int
    k_strong: int
    n_all: int
    k_all: int
    n_recent: int
    lb_strong: float
    lb_all: float


def lower_bound(
    k: int,
    n: int,
    parent_mean: float | None = None,
    kappa: float = POOLING_KAPPA_DEFAULT,
    q: float = LB_QUANTILE_DEFAULT,
) -> float:
    """Compute lower-bound success rate using Beta quantile with optional empirical Bayes pooling.

    Authority: docs/ENGINE_SPEC.md section 6.2 and section 16.
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"Invalid success counts: k={k}, n={n}")

    if n == 0:
        return 0.0

    a, b = posterior_parameters(k, n, parent_mean, kappa)
    return float(scipy.stats.beta.ppf(q, a, b))


def posterior_parameters(
    k: int, n: int, parent_mean: float | None = None, kappa: float = POOLING_KAPPA_DEFAULT
) -> tuple[float, float]:
    """One clipped-prior definition for both permission bounds and drift baselines."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"Invalid success counts: k={k}, n={n}")
    if parent_mean is None:
        a0 = 1.0
        b0 = 1.0
    else:
        p = min(max(parent_mean, 0.01), 0.99)
        a0 = max(1.0, kappa * p)
        b0 = max(1.0, kappa * (1.0 - p))  # never below 1: pooling cannot assert near-perfection

    a = a0 + k
    b = b0 + (n - k)
    return a, b


# Alias for compatibility
compute_beta_lower_bound = lower_bound


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string to UTC datetime."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def aggregate_evidence(
    conn: sqlite3.Connection | ReadConnection,
    as_of: str,
    family: str | None = None,
    evidence_window_days: int = EVIDENCE_WINDOW_DAYS_DEFAULT,
    recent_window_days: int = RECENT_WINDOW_DAYS_DEFAULT,
    persist: bool = True,
    pooling_kappa: float | None = None,
    lb_quantile: float | None = None,
) -> dict[tuple[str, str], ClassStats]:
    """Aggregate evidence for (class_key, action) pairs as of specified timestamp.

    Authority: docs/ENGINE_SPEC.md section 6.1 and CONTRACT I-12:
    - Filters strictly non-auto-executed proposals (gate in SHADOW, SUGGEST, ASK).
    - Auto-executed items (HOLD_THEN_EXECUTE, EXECUTE_UNDO, EXECUTE_SILENT) are EXCLUDED.
    - Undo/override outcomes (source in 'undo', 'override') are EXCLUDED from Beta counts.
    - Audit-holdout items (gate SUGGEST with audit_holdout=1) ARE INCLUDED.
    - Weak outcomes are counted only in n_all, k_all.
    - Hierarchical empirical Bayes pooling applied from parent class key if n_parent >= 20.
    """
    as_of_dt = _parse_ts(as_of)
    window_start = format_timestamp(as_of_dt - timedelta(days=evidence_window_days))
    recent_start = format_timestamp(as_of_dt - timedelta(days=recent_window_days))
    rows = HistoryView(conn, as_of).permission_records(family)

    # Raw counts per (class_key, action)
    counts: dict[tuple[str, str], dict[str, int]] = {}

    for record in rows:
        if record["gate"] not in {"SHADOW", "SUGGEST", "ASK"}:
            continue
        if _parse_ts(record["proposed_at"]) < _parse_ts(window_start):
            continue
        row = {**record, **record["decision"]}
        c_key = str(row["class_key"])
        act = str(row["action"])
        try:
            if parse_action(act).is_noop:
                continue
        except InvalidAction:
            continue
        key = (c_key, act)
        if key not in counts:
            counts[key] = {
                "n_strong": 0,
                "k_strong": 0,
                "n_all": 0,
                "k_all": 0,
                "n_recent": 0,
            }

        observed = str(row["observed_action"])
        agree = observed == act
        strength = str(row["strength"])
        proposed_at = str(row["proposed_at"])

        # Count in all
        counts[key]["n_all"] += 1
        if agree:
            counts[key]["k_all"] += 1

        # Count in strong
        if strength == "STRONG":
            counts[key]["n_strong"] += 1
            if agree:
                counts[key]["k_strong"] += 1

            if _parse_ts(proposed_at) >= _parse_ts(recent_start):
                counts[key]["n_recent"] += 1

    # Compute parent strong counts for empirical Bayes pooling
    parent_counts: dict[tuple[str, str], dict[str, int]] = {}
    for (c_key, act), c_data in counts.items():
        p_key = c_key.rsplit("|", 1)[0] if "|" in c_key else c_key
        pkey_tuple = (p_key, act)
        if pkey_tuple not in parent_counts:
            parent_counts[pkey_tuple] = {"n_parent": 0, "k_parent": 0}
        parent_counts[pkey_tuple]["n_parent"] += c_data["n_strong"]
        parent_counts[pkey_tuple]["k_parent"] += c_data["k_strong"]

    # Calculate statistics and lower bounds
    results: dict[tuple[str, str], ClassStats] = {}

    for (c_key, act), c_data in counts.items():
        n_strong = c_data["n_strong"]
        k_strong = c_data["k_strong"]
        n_all = c_data["n_all"]
        k_all = c_data["k_all"]
        n_recent = c_data["n_recent"]

        p_key = c_key.rsplit("|", 1)[0] if "|" in c_key else c_key
        p_info = parent_counts.get((p_key, act), {"n_parent": 0, "k_parent": 0})
        n_p = p_info["n_parent"]
        k_p = p_info["k_parent"]

        # Only pool if n_parent >= 20 and class_key differs from parent
        parent_mean = None
        if n_p >= 20 and p_key != c_key:
            parent_mean = (k_p + 1.0) / (n_p + 2.0)

        kappa = settings.pooling_kappa if pooling_kappa is None else pooling_kappa
        quantile = settings.lb_quantile if lb_quantile is None else lb_quantile
        lb_strong = lower_bound(
            k=k_strong, n=n_strong, parent_mean=parent_mean, kappa=kappa, q=quantile
        )
        lb_all = lower_bound(k=k_all, n=n_all, parent_mean=None, kappa=kappa, q=quantile)

        stat = ClassStats(
            class_key=c_key,
            action=act,
            as_of=as_of,
            n_strong=n_strong,
            k_strong=k_strong,
            n_all=n_all,
            k_all=k_all,
            n_recent=n_recent,
            lb_strong=lb_strong,
            lb_all=lb_all,
        )
        results[(c_key, act)] = stat

        if not persist:
            continue
        if not isinstance(conn, sqlite3.Connection):
            raise AccessError("A read-only evidence query cannot persist class statistics")

        # Insert into class_stats table if table exists
        RoleAccess(conn, Role.EXAMINER).execute_write(
            "class_stats",
            """
            INSERT OR REPLACE INTO class_stats
            (class_key, action, as_of, n_strong, k_strong, n_all, k_all, n_recent, lb_strong, lb_all)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                c_key,
                act,
                as_of,
                n_strong,
                k_strong,
                n_all,
                k_all,
                n_recent,
                lb_strong,
                lb_all,
            ),
        )

    return results
