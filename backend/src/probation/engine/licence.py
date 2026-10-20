"""Licence derivation and maintenance.

Authority: docs/CONTRACT.md invariants I-10, I-13, I-20 and docs/ENGINE_SPEC.md sections 6.2, 6.3.
"""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from probation.config import settings
from probation.core.enums import LedgerKind, LicenceLevel
from probation.core.types import LicenceView
from probation.db.ledger import append_ledger
from probation.engine.caps import BASE_ACTION_CAPS, is_recallable
from probation.engine.evidence import ClassStats

L1_MIN_N_DEFAULT: Final[int] = 20
L1_MIN_LB_DEFAULT: Final[float] = 0.70
L2_MIN_LB_DEFAULT: Final[float] = 0.95
L3_MIN_LB_DEFAULT: Final[float] = 0.98
STRONG_MIN_RAW_N_DEFAULT: Final[int] = 40
LICENCE_MIN_RECENT_N_DEFAULT: Final[int] = 20
LICENCE_TTL_DAYS_DEFAULT: Final[int] = 30
EXAM_VALID_DAYS_DEFAULT: Final[int] = 90


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp to UTC datetime."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def derive_licence_level(
    action: str,
    n_all: int,
    lb_all: float,
    n_strong: int,
    lb_strong: float,
    n_recent: int,
    exam_ok_fn: Callable[[int], bool] | None = None,
    cap: int | None = None,
    recallable: bool | None = None,
    current_level: int = 0,
    l1_min_n: int = L1_MIN_N_DEFAULT,
    l1_min_lb: float = L1_MIN_LB_DEFAULT,
    l2_min_lb: float = L2_MIN_LB_DEFAULT,
    l3_min_lb: float = L3_MIN_LB_DEFAULT,
    strong_min_raw_n: int = STRONG_MIN_RAW_N_DEFAULT,
    licence_min_recent_n: int = LICENCE_MIN_RECENT_N_DEFAULT,
) -> LicenceLevel:
    """Derive permissible autonomy level given evidence volume, lower bounds, and exam pass status.

    Authority: docs/ENGINE_SPEC.md section 6.3:
    - Level 1: n_all >= 20 and lb_all >= 0.70
    - Level 2: n_strong >= 40, n_recent >= 20, lb_strong >= 0.95, and exam_ok(level=2)
    - Level 3: n_strong >= 40, n_recent >= 20, lb_strong >= 0.98, exam_ok(level=3), and action.recallable
    - Effective level: min(L, cap)
    """
    rec = recallable if recallable is not None else is_recallable(action)
    act_cap = cap if cap is not None else BASE_ACTION_CAPS.get(action.upper(), 3)

    lvl = 0

    # Level 1 check
    if n_all >= l1_min_n and lb_all >= l1_min_lb:
        lvl = 1

    # Strong evidence prerequisites
    strong_ok = (n_strong >= strong_min_raw_n) and (n_recent >= licence_min_recent_n)

    if strong_ok:
        # Level 2 check
        exam_l2_ok = exam_ok_fn(2) if exam_ok_fn is not None else False
        if lb_strong >= l2_min_lb and exam_l2_ok:
            lvl = 2

        # Level 3 check: strictly requires recallability (CONTRACT I-20)
        exam_l3_ok = exam_ok_fn(3) if exam_ok_fn is not None else False
        if lb_strong >= l3_min_lb and exam_l3_ok and rec:
            lvl = 3

    effective = min(lvl, act_cap)
    return LicenceLevel(effective)


def check_exam_ok(
    conn: sqlite3.Connection,
    class_key: str,
    action: str,
    as_of: str,
    level: int,
    exam_valid_days: int = EXAM_VALID_DAYS_DEFAULT,
) -> bool:
    """Verify if a valid, uninvalidated exam pass exists for (class_key, action) as of as_of.

    Authority: docs/ENGINE_SPEC.md section 6.3:
    A passed exam run exists with:
    - level_tested >= level
    - finished_at >= as_of - EXAM_VALID_DAYS
    - finished_at later than the latest drift alarm for (c, a)
    - finished_at later than the latest family-shift alarm for the family
    """
    cur = conn.cursor()

    # Check if exam_runs table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exam_runs';")
    if cur.fetchone() is None:
        return False

    as_of_dt = _parse_ts(as_of)
    min_finished = (as_of_dt - timedelta(days=exam_valid_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Find latest drift alarm for (class_key, action)
    cur.execute(
        "SELECT last_alarm_at FROM drift_state WHERE class_key = ? AND action = ?;",
        (class_key, action),
    )
    drift_row = cur.fetchone()
    last_drift_alarm = (
        str(drift_row["last_alarm_at"]) if drift_row and drift_row["last_alarm_at"] else ""
    )

    # Find latest family-shift alarm
    family = class_key.split("|")[0]
    cur.execute(
        "SELECT MAX(week_start) FROM family_shift WHERE family = ? AND alarm = 1;",
        (family,),
    )
    shift_row = cur.fetchone()
    last_shift_alarm = str(shift_row[0]) if shift_row and shift_row[0] else ""

    query = """
    SELECT id, finished_at FROM exam_runs
    WHERE class_key = ?
      AND action = ?
      AND level_tested >= ?
      AND passed = 1
      AND finished_at >= ?
      AND finished_at <= ?
    ORDER BY finished_at DESC
    LIMIT 1;
    """
    cur.execute(query, (class_key, action, level, min_finished, as_of))
    row = cur.fetchone()

    if row is None:
        return False

    finished_at = str(row["finished_at"])
    if last_drift_alarm and finished_at <= last_drift_alarm:
        return False
    if last_shift_alarm and finished_at <= last_shift_alarm:
        return False

    return True


def get_latest_passing_exam_id(
    conn: sqlite3.Connection,
    class_key: str,
    action: str,
    as_of: str,
    level: int,
) -> str | None:
    """Retrieve ID of latest valid passing exam run for (class_key, action)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exam_runs';")
    if cur.fetchone() is None:
        return None

    query = """
    SELECT id FROM exam_runs
    WHERE class_key = ?
      AND action = ?
      AND level_tested >= ?
      AND passed = 1
      AND finished_at <= ?
    ORDER BY finished_at DESC
    LIMIT 1;
    """
    cur.execute(query, (class_key, action, level, as_of))
    row = cur.fetchone()
    return str(row["id"]) if row else None


def derive_and_cache_licences(
    conn: sqlite3.Connection,
    as_of: str,
    stats: dict[tuple[str, str], ClassStats] | None = None,
    exam_ok_fn: Callable[[str, str, int], bool] | None = None,
) -> dict[tuple[str, str], LicenceView]:
    """Derive licences for all active (class_key, action) pairs and update licence_cache.

    Appends LedgerKind.LICENCE_CHANGE to the ledger when a level transition occurs.
    """
    cur = conn.cursor()
    as_of_dt = _parse_ts(as_of)
    valid_until = (as_of_dt + timedelta(days=LICENCE_TTL_DAYS_DEFAULT)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    # If stats not provided, query class_stats as of as_of
    stats_dict: dict[tuple[str, str], ClassStats] = {}
    if stats is not None:
        stats_dict = stats
    else:
        cur.execute("SELECT * FROM class_stats WHERE as_of = ?;", (as_of,))
        for r in cur.fetchall():
            s = ClassStats(
                class_key=str(r["class_key"]),
                action=str(r["action"]),
                as_of=str(r["as_of"]),
                n_strong=int(r["n_strong"]),
                k_strong=int(r["k_strong"]),
                n_all=int(r["n_all"]),
                k_all=int(r["k_all"]),
                n_recent=int(r["n_recent"]),
                lb_strong=float(r["lb_strong"]),
                lb_all=float(r["lb_all"]),
            )
            stats_dict[(s.class_key, s.action)] = s

    licences: dict[tuple[str, str], LicenceView] = {}

    for (c_key, act), s in stats_dict.items():
        # Get previous level from cache
        cur.execute(
            "SELECT level FROM licence_cache WHERE class_key = ? AND action = ?;",
            (c_key, act),
        )
        prev_row = cur.fetchone()
        prev_level = int(prev_row["level"]) if prev_row else 0

        # Build exam_ok checker for this specific pair
        def _check_exam(
            lvl: int,
            current_ck: str = c_key,
            current_act: str = act,
        ) -> bool:
            if exam_ok_fn is not None:
                return exam_ok_fn(current_ck, current_act, lvl)
            return check_exam_ok(conn, current_ck, current_act, as_of, lvl)

        new_level = derive_licence_level(
            action=act,
            n_all=s.n_all,
            lb_all=s.lb_all,
            n_strong=s.n_strong,
            lb_strong=s.lb_strong,
            n_recent=s.n_recent,
            exam_ok_fn=_check_exam,
            current_level=prev_level,
        )

        reasons: list[str] = []
        if new_level > prev_level:
            reasons.append("promoted")
        elif new_level < prev_level:
            reasons.append("demoted")

        # Determine exam_run_id for level >= 2
        exam_run_id = None
        if int(new_level.value) >= 2:
            exam_run_id = get_latest_passing_exam_id(conn, c_key, act, as_of, int(new_level.value))

        # Update cache
        cur.execute(
            """
            INSERT OR REPLACE INTO licence_cache
            (class_key, action, level, lower_bound, reasons_json, exam_run_id, computed_at, valid_until)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                c_key,
                act,
                int(new_level.value),
                s.lb_strong,
                json.dumps(reasons),
                exam_run_id,
                as_of,
                valid_until,
            ),
        )

        # Append to hash-chained ledger on transition
        if int(new_level.value) != prev_level:
            append_ledger(
                conn,
                kind=LedgerKind.LICENCE_CHANGE,
                ref_id=f"{c_key}::{act}",
                payload={
                    "class_key": c_key,
                    "action": act,
                    "prev_level": prev_level,
                    "new_level": int(new_level.value),
                    "lower_bound": s.lb_strong,
                    "n_strong": s.n_strong,
                    "k_strong": s.k_strong,
                    "as_of": as_of,
                },
                created_at=as_of,
            )

        licences[(c_key, act)] = LicenceView(
            class_key=c_key,
            action=act,
            level=new_level,
            lower_bound=s.lb_strong,
            n_strong=s.n_strong,
            k_strong=s.k_strong,
            n_all=s.n_all,
            k_all=s.k_all,
            n_recent=s.n_recent,
            exam_run_id=exam_run_id,
            valid_until=valid_until,
            reasons=reasons,
        )

    conn.commit()
    return licences


def find_exam_candidates(
    conn: sqlite3.Connection,
    as_of: str,
    max_candidates: int | None = None,
    strong_min_raw_n: int = STRONG_MIN_RAW_N_DEFAULT,
    licence_min_recent_n: int = LICENCE_MIN_RECENT_N_DEFAULT,
    l2_min_lb: float = L2_MIN_LB_DEFAULT,
    l3_min_lb: float = L3_MIN_LB_DEFAULT,
) -> list[tuple[str, str, int]]:
    """Identify (class_key, action, target_level) candidates qualifying numerically without a valid exam pass.

    Authority: docs/ENGINE_SPEC.md section 15.0:
    At each LICENCE_REVIEW, for every (c, a) whose evidence meets the numeric bar for level 2 (or 3)
    but has no valid passing exam (section 6.3), queue an exam for the highest level it qualifies for.
    Start at most EXAM_MAX_PER_DAY per review tick, oldest candidate first.
    """
    max_cand = max_candidates if max_candidates is not None else settings.exam_max_per_day
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='class_stats';")
    if cur.fetchone() is None:
        return []

    cur.execute(
        """
        SELECT class_key, action, n_strong, lb_strong, n_recent
        FROM class_stats
        WHERE as_of = ?
        ORDER BY n_strong DESC;
        """,
        (as_of,),
    )
    rows = cur.fetchall()
    candidates: list[tuple[str, str, int]] = []

    for r in rows:
        c_key = str(r["class_key"])
        act = str(r["action"])
        n_strong = int(r["n_strong"])
        lb_strong = float(r["lb_strong"])
        n_recent = int(r["n_recent"])

        strong_ok = (n_strong >= strong_min_raw_n) and (n_recent >= licence_min_recent_n)
        if not strong_ok or lb_strong < l2_min_lb:
            continue

        target_level = 2
        rec = is_recallable(act)
        if lb_strong >= l3_min_lb and rec:
            target_level = 3

        has_valid_exam = check_exam_ok(conn, c_key, act, as_of, target_level)
        if not has_valid_exam:
            candidates.append((c_key, act, target_level))
            if len(candidates) >= max_cand:
                break

    return candidates
