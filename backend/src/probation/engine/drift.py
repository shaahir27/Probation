"""Statistical drift monitoring via CUSUM and Population Stability Index (PSI).

Authority: docs/CONTRACT.md section 7, section 8 and docs/ENGINE_SPEC.md section 11.
"""

import bisect
import json
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Final

from probation.core.enums import LedgerKind
from probation.db.access import Role, RoleAccess

CUSUM_ALLOWANCE_DEFAULT: Final[float] = 0.02
CUSUM_ALARM_DEFAULT: Final[float] = 5.0
CUSUM_BASE_ERR_DEFAULT: Final[float] = 0.03
PSI_ALARM_DEFAULT: Final[float] = 0.25


def _parse_ts(ts: str) -> datetime:
    """Parse ISO timestamp into UTC datetime."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _quantile_bins(ref_nums: list[float], n_bins: int = 10) -> list[float]:
    """Compute quantile cutoffs from reference distribution (ENGINE_SPEC 11.2)."""
    sorted_vals = sorted(ref_nums)
    if not sorted_vals:
        return []
    cutoffs: list[float] = []
    for i in range(1, n_bins):
        idx = int(len(sorted_vals) * i / n_bins)
        cutoffs.append(sorted_vals[idx])
    return sorted(set(cutoffs))


class CUSUMTracker:
    """CUSUM error tracker for detecting performance degradation per (class_key, action).

    Authority: docs/ENGINE_SPEC.md section 11.1:
    - x_t = 1 if disagreement else 0 (evidence items AND undo/override events)
    - S_t = max(0, S_{t-1} + x_t - (baseline_err + CUSUM_ALLOWANCE))
    - if S_t >= CUSUM_ALARM: alarm (record last_alarm_at = now, S = 0)
    - Hard rule: two or more undo or override events for the same (c, a) within 30 days -> alarm immediately.
    """

    def __init__(
        self,
        baseline_err: float = CUSUM_BASE_ERR_DEFAULT,
        allowance: float = CUSUM_ALLOWANCE_DEFAULT,
        threshold: float = CUSUM_ALARM_DEFAULT,
        last_alarm_at: str | None = None,
        initial_s: float = 0.0,
        correction_times: tuple[str, ...] = (),
    ) -> None:
        self.baseline_err = baseline_err
        self.allowance = allowance
        self.threshold = threshold
        self.last_alarm_at = last_alarm_at
        self.s = initial_s
        self._undo_history: list[datetime] = [
            _parse_ts(timestamp) for timestamp in correction_times
        ]

    def update(
        self,
        is_error: bool,
        is_undo: bool = False,
        timestamp: str = "",
    ) -> bool:
        """Update tracker with new observation and return True if alarm triggers."""
        ts_dt = _parse_ts(timestamp) if timestamp else datetime(1970, 1, 1, tzinfo=UTC)

        # 1. Hard rule: two or more undos/overrides within 30 days
        if is_undo:
            cutoff = ts_dt - timedelta(days=30)
            self._undo_history = [t for t in self._undo_history if t >= cutoff]
            self._undo_history.append(ts_dt)

            if len(self._undo_history) >= 2:
                self.last_alarm_at = timestamp or ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                self.s = 0.0
                return True

        # 2. CUSUM formula update
        x_t = 1.0 if is_error else 0.0
        increment = x_t - (self.baseline_err + self.allowance)
        self.s = max(0.0, self.s + increment)

        if self.s >= self.threshold:
            self.last_alarm_at = timestamp or ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            self.s = 0.0
            return True

        return False


def compute_psi(expected_dist: list[float], actual_dist: list[float]) -> float:
    """Compute Population Stability Index between reference and current feature distributions.

    Authority: docs/ENGINE_SPEC.md section 11.2:
    PSI = sum_i (a_i - e_i) * ln(a_i / e_i) with each share floored at 1e-4.
    """
    if len(expected_dist) != len(actual_dist) or not expected_dist:
        raise ValueError("Distributions must have identical non-zero length")

    # Normalize to probabilities if sum > 0
    sum_e = sum(expected_dist)
    sum_a = sum(actual_dist)

    e_shares = [x / sum_e if sum_e > 0 else 1.0 / len(expected_dist) for x in expected_dist]
    a_shares = [x / sum_a if sum_a > 0 else 1.0 / len(actual_dist) for x in actual_dist]

    # Floor at 1e-4 to prevent division by zero or ln(0)
    floor = 1e-4
    e_shares = [max(x, floor) for x in e_shares]
    a_shares = [max(x, floor) for x in a_shares]

    psi = 0.0
    for e_i, a_i in zip(e_shares, a_shares, strict=True):
        psi += (a_i - e_i) * math.log(a_i / e_i)

    return float(psi)


def check_family_shift(
    conn: sqlite3.Connection,
    family: str,
    as_of: str,
    psi_alarm_threshold: float = PSI_ALARM_DEFAULT,
) -> bool:
    """Weekly family shift check via Population Stability Index across top features.

    Authority: docs/ENGINE_SPEC.md section 11.2:
    - Reference window: 90 days before the last 30 days [as_of - 120d, as_of - 30d].
    - Current window: last 30 days [as_of - 30d, as_of].
    - If max PSI > 0.25: records family_shift alarm and appends ledger event.
    """
    as_of_dt = _parse_ts(as_of)
    ref_start = (as_of_dt - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ref_end = (as_of_dt - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur_end = as_of

    access = RoleAccess(conn, Role.EXAMINER)
    with access.transaction():
        cur = access.conn.cursor()

        # Query reference features
        cur.execute(
            """
            SELECT f.deterministic_json, f.reader_json
            FROM situations s
            JOIN features f ON s.id = f.situation_id
            WHERE s.family = ? AND s.occurred_at COLLATE UTC_TIMESTAMP >= ? AND s.occurred_at COLLATE UTC_TIMESTAMP < ?;
            """,
            (family, ref_start, ref_end),
        )
        ref_rows = cur.fetchall()

        # Query current features
        cur.execute(
            """
            SELECT f.deterministic_json, f.reader_json
            FROM situations s
            JOIN features f ON s.id = f.situation_id
            WHERE s.family = ? AND s.occurred_at COLLATE UTC_TIMESTAMP >= ? AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?;
            """,
            (family, ref_end, cur_end),
        )
        cur_rows = cur.fetchall()

        if len(ref_rows) < 20 or len(cur_rows) < 10:
            return False

        # Extract common categorical/numeric keys
        psi_results: dict[str, float] = {}

        # Sample top feature distributions
        sample_ref = json.loads(ref_rows[0]["deterministic_json"])
        feature_keys = list(sample_ref.keys())[:5]

        for key in feature_keys:
            sample_val = sample_ref.get(key)
            is_numeric = isinstance(sample_val, (int, float)) and not isinstance(sample_val, bool)

            if is_numeric:
                ref_nums: list[float] = []
                for r in ref_rows:
                    d = json.loads(r["deterministic_json"])
                    val = d.get(key)
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        ref_nums.append(float(val))

                cur_nums: list[float] = []
                for r in cur_rows:
                    d = json.loads(r["deterministic_json"])
                    val = d.get(key)
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        cur_nums.append(float(val))

                if not ref_nums or not cur_nums:
                    continue

                cutoffs = _quantile_bins(ref_nums, n_bins=10)
                if not cutoffs:
                    ref_val0 = ref_nums[0]
                    ref_dist = [float(len(ref_nums)), 0.0]
                    act_dist = [
                        float(sum(1 for x in cur_nums if x == ref_val0)),
                        float(sum(1 for x in cur_nums if x != ref_val0)),
                    ]
                else:
                    n_buckets = len(cutoffs) + 1
                    ref_dist = [0.0] * n_buckets
                    act_dist = [0.0] * n_buckets
                    for x in ref_nums:
                        ref_dist[bisect.bisect_right(cutoffs, x)] += 1.0
                    for x in cur_nums:
                        act_dist[bisect.bisect_right(cutoffs, x)] += 1.0

                feat_psi = compute_psi(ref_dist, act_dist)
                psi_results[key] = feat_psi
            else:
                # Build histogram of categorical values
                ref_vals: dict[str, int] = {}
                for r in ref_rows:
                    d = json.loads(r["deterministic_json"])
                    v = str(d.get(key, ""))
                    ref_vals[v] = ref_vals.get(v, 0) + 1

                cur_vals: dict[str, int] = {}
                for r in cur_rows:
                    d = json.loads(r["deterministic_json"])
                    v = str(d.get(key, ""))
                    cur_vals[v] = cur_vals.get(v, 0) + 1

                all_bins = sorted(set(ref_vals.keys()) | set(cur_vals.keys()))
                if len(all_bins) < 2:
                    continue

                ref_dist = [float(ref_vals.get(b, 0)) for b in all_bins]
                act_dist = [float(cur_vals.get(b, 0)) for b in all_bins]

                feat_psi = compute_psi(ref_dist, act_dist)
                psi_results[key] = feat_psi

        max_psi = max(psi_results.values()) if psi_results else 0.0
        alarm = int(max_psi > psi_alarm_threshold)
        psi_json = json.dumps(psi_results)

        # A resumed replay regenerates every weekly tick from the start of the timeline, so
        # this week may already be recorded. family_shift is read positionally because
        # callers hand in plain sqlite3 connections as well as Row-factory ones.
        prior = cur.execute(
            "SELECT alarm, psi_json FROM family_shift WHERE family=? AND week_start=?",
            (family, as_of),
        ).fetchone()
        # Only an identical recheck is skipped. A recomputation that disagrees with the
        # recorded week is new information and must still reach the audit trail.
        already_recorded = (
            prior is not None and int(prior[0]) == alarm and str(prior[1]) == psi_json
        )

        access.execute_write(
            "family_shift",
            """
            INSERT OR REPLACE INTO family_shift (family, week_start, psi_json, alarm)
            VALUES (?, ?, ?, ?);
            """,
            (family, as_of, psi_json, alarm),
        )

        if alarm == 1 and not already_recorded:
            access.append_ledger(
                kind=LedgerKind.DRIFT_ALARM,
                ref_id=f"shift-{family}-{as_of}",
                payload={
                    "family": family,
                    "kind": "family_shift",
                    "max_psi": max_psi,
                    "psi_scores": psi_results,
                    "week_start": as_of,
                },
                created_at=as_of,
            )

        return bool(alarm)
