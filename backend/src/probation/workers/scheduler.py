"""Scheduler worker: Nightly review, retrain ticks, and TTL expiry.

Authority: docs/CONTRACT.md section 3 and docs/ENGINE_SPEC.md section 1.
"""

import sqlite3
from datetime import UTC, datetime

from probation.engine.drift import check_family_shift
from probation.engine.evidence import aggregate_evidence
from probation.engine.licence import derive_and_cache_licences


def run_nightly_review(
    conn: sqlite3.Connection,
    as_of: str | None = None,
) -> None:
    """Execute nightly review tick (02:00 IST / daily replay tick).

    Authority: docs/ENGINE_SPEC.md section 1:
    - Recompute evidence counts and lower bounds (class_stats).
    - Recompute derived licence levels and cache (licence_cache).
    """
    now_iso = as_of or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Aggregate evidence
    stats = aggregate_evidence(conn, as_of=now_iso)

    # 2. Derive and cache licences
    derive_and_cache_licences(conn, as_of=now_iso, stats=stats)


def run_weekly_shift_checks(
    conn: sqlite3.Connection,
    as_of: str | None = None,
) -> None:
    """Execute weekly feature drift checks (PSI) per family.

    Authority: docs/ENGINE_SPEC.md section 11.2.
    """
    now_iso = as_of or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT family FROM situations;")
    families = [str(r[0]) for r in cur.fetchall()]

    for fam in families:
        check_family_shift(conn, family=fam, as_of=now_iso)
