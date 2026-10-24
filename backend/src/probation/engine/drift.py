"""Statistical drift monitoring via CUSUM and Population Stability Index (PSI).

Authority: docs/CONTRACT.md section 7, section 8 and docs/ENGINE_SPEC.md section 11.
"""

import math
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from probation.engine.policy import Policy

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
    *,
    policy: "Policy | None" = None,
) -> bool:
    """Persist an auditable bounded check; unavailable monitoring is not a quiet result."""
    from probation.core.clock import format_timestamp, parse_timestamp
    from probation.core.hashing import canonical_json
    from probation.core.history import HistoryView
    from probation.engine.shift import assess_shift

    as_of = format_timestamp(as_of)
    view = HistoryView(conn, as_of)
    versions = policy.provenance.get("semantic_versions", []) if policy else []
    semantic_version = versions[0] if len(versions) == 1 else None
    reference, current = view.shift_populations(family, semantic_version)
    invalid_snapshot = policy is not None and (
        policy.family != family
        or not policy.as_of
        or parse_timestamp(policy.as_of) > parse_timestamp(as_of)
    )
    result = assess_shift(
        None if invalid_snapshot else policy, reference, current, threshold=psi_alarm_threshold
    )
    cut = parse_timestamp(as_of)
    result["reference_start"] = format_timestamp(cut - timedelta(days=120))
    result["current_start"] = format_timestamp(cut - timedelta(days=30))
    result["as_of"] = as_of
    result["semantic_version"] = semantic_version
    if invalid_snapshot:
        result["status"] = "invalid_policy_snapshot"
    alarm = result["alarm"] is True
    packed = canonical_json(result)
    access = RoleAccess(conn, Role.EXAMINER)
    with access.transaction():
        previous = access.conn.execute(
            "SELECT alarm,psi_json FROM family_shift WHERE family=? AND week_start=?",
            (family, as_of),
        ).fetchone()
        unchanged = (
            previous is not None and int(previous[0]) == int(alarm) and str(previous[1]) == packed
        )
        access.execute_write(
            "family_shift",
            """INSERT OR REPLACE INTO family_shift
            (family,week_start,psi_json,alarm) VALUES (?,?,?,?)""",
            (family, as_of, packed, int(alarm)),
        )
        if alarm and not unchanged:
            access.append_ledger(
                LedgerKind.DRIFT_ALARM,
                f"shift-{family}-{as_of}",
                {
                    "family": family,
                    "kind": "family_shift",
                    "max_psi": result["max_psi"],
                    "psi_scores": {key: value["psi"] for key, value in result["features"].items()},
                    "week_start": as_of,
                    "policy_version": result.get("policy_version"),
                },
                as_of,
            )
    return alarm
