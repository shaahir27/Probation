"""Scheduler worker: Nightly review, retrain ticks, and TTL expiry.

Authority: docs/CONTRACT.md section 3 and docs/ENGINE_SPEC.md section 1.
"""

import sqlite3
from datetime import UTC, datetime

from probation.config import settings
from probation.engine.drift import check_family_shift
from probation.engine.evidence import aggregate_evidence
from probation.engine.exam import run_exam
from probation.engine.habits import mine_habits
from probation.engine.licence import derive_and_cache_licences, find_exam_candidates
from probation.packs.chains.mining import mine_chains


def run_nightly_review(
    conn: sqlite3.Connection,
    as_of: str | None = None,
) -> None:
    """Execute nightly review tick (02:00 IST / daily replay tick).

    Authority: docs/ENGINE_SPEC.md section 1 & section 15.0:
    - Recompute evidence counts and lower bounds (class_stats).
    - Queue and evaluate diagnostic exams for candidate classes (capped by EXAM_MAX_PER_DAY).
    - Recompute derived licence levels and cache (licence_cache).
    - Mine habits with BH FDR correction and chains with sequence mining.
    """
    now_iso = as_of or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Aggregate evidence
    stats = aggregate_evidence(conn, as_of=now_iso)

    # 2. Run diagnostic exams for candidates
    candidates = find_exam_candidates(conn, as_of=now_iso, max_candidates=settings.exam_max_per_day)
    for c_key, act, lvl in candidates:
        run_exam(conn, class_key=c_key, action=act, level_tested=lvl, as_of=now_iso)

    # 3. Derive and cache licences
    derive_and_cache_licences(conn, as_of=now_iso, stats=stats)

    # 4. Mine habits and chains
    mine_habits(conn, as_of=now_iso)
    mine_chains(conn, as_of=now_iso)


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
