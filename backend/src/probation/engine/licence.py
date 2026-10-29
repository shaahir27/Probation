"""Licence derivation and maintenance.

Authority: docs/CONTRACT.md invariants I-10, I-13, I-20 and docs/ENGINE_SPEC.md sections 6.2, 6.3.
"""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from probation.config import Settings, settings
from probation.core.clock import format_timestamp, timestamp_key
from probation.core.enums import LedgerKind, LicenceLevel
from probation.core.history import HistoryView
from probation.core.types import LicenceView
from probation.db.access import Role, RoleAccess
from probation.db.guards import ReadConnection
from probation.engine.caps import get_action_cap, is_recallable
from probation.engine.evidence import ClassStats
from probation.engine.exam_candidates import evidence_fingerprint as evidence_fingerprint
from probation.engine.exam_candidates import find_exam_candidates as find_exam_candidates
from probation.engine.exam_validity import meaningful_exam

L1_MIN_N_DEFAULT: Final[int] = 20
L1_MIN_LB_DEFAULT: Final[float] = 0.70
L2_MIN_LB_DEFAULT: Final[float] = 0.95
L3_MIN_LB_DEFAULT: Final[float] = 0.98
STRONG_MIN_RAW_N_DEFAULT: Final[int] = 60
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
    - Level 2: n_strong >= 60, n_recent >= 20, lb_strong >= 0.95, and exam_ok(level=2)
    - Level 3: n_strong >= 60, n_recent >= 20, lb_strong >= 0.98, exam_ok(level=3), and action.recallable
    - Effective level: min(L, cap)
    """
    rec = recallable if recallable is not None else is_recallable(action)
    # A supplied conditional cap cannot make an unknown/no-op action licensable.
    act_cap = min(cap, get_action_cap(action)) if cap is not None else get_action_cap(action)

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


def family_for_class(class_key: str) -> str:
    return {
        "mail": "email_action",
        "email": "email_action",
        "cal": "invite_rsvp",
        "calendar": "invite_rsvp",
        "file": "file_destination",
        "files": "file_destination",
        "radar": "opportunity_triage",
        "reading": "link_triage",
        "link": "link_triage",
        "chain": "chain_followup",
        "chains": "chain_followup",
    }.get(class_key.split("|")[0], "")


def check_exam_ok(
    conn: sqlite3.Connection | ReadConnection,
    class_key: str,
    action: str,
    as_of: str,
    level: int,
    exam_valid_days: int = EXAM_VALID_DAYS_DEFAULT,
) -> bool:
    return (
        get_latest_passing_exam_id(conn, class_key, action, as_of, level, exam_valid_days)
        is not None
    )


def get_latest_passing_exam_id(
    conn: sqlite3.Connection | ReadConnection,
    class_key: str,
    action: str,
    as_of: str,
    level: int,
    exam_valid_days: int = EXAM_VALID_DAYS_DEFAULT,
    config: Settings | None = None,
) -> str | None:

    if level not in {2, 3} or not family_for_class(class_key):
        return None
    cutoff = format_timestamp(_parse_ts(as_of) - timedelta(days=exam_valid_days))
    alarms = HistoryView(conn, as_of).permission_alarms(
        class_key, action, family_for_class(class_key)
    )
    rows = conn.execute(
        """SELECT * FROM exam_runs WHERE class_key=? AND action=?
           AND level_tested>=? AND passed=1
           AND finished_at COLLATE UTC_TIMESTAMP >= ?
           AND finished_at COLLATE UTC_TIMESTAMP <= ?
           AND started_at COLLATE UTC_TIMESTAMP <= finished_at COLLATE UTC_TIMESTAMP
           ORDER BY finished_at COLLATE UTC_TIMESTAMP DESC,id""",
        (class_key, action, level, cutoff, as_of),
    ).fetchall()
    for row in rows:
        if meaningful_exam(row, config) and all(
            timestamp_key(row["finished_at"]) > timestamp_key(alarm) for alarm in alarms
        ):
            return str(row["id"])
    return None


def derive_licences(
    conn: sqlite3.Connection | ReadConnection,
    as_of: str,
    *,
    config: Settings | None = None,
    pair: tuple[str, str] | None = None,
    stats: dict[tuple[str, str], ClassStats] | None = None,
    exam_ok_fn: Callable[[str, str, int], bool] | None = None,
    source_ids: tuple[str, ...] | None = None,
) -> dict[tuple[str, str], LicenceView]:
    """Read-only authority; callers never substitute cache levels for evidence."""
    from probation.engine.evidence import aggregate_evidence

    cfg = config or settings
    as_of = format_timestamp(as_of)
    no_authority = (
        pair is not None and get_action_cap(pair[1], family=family_for_class(pair[0])) == 0
    )
    evidence = (
        stats
        if stats is not None
        else {}
        if no_authority
        else aggregate_evidence(
            conn,
            as_of,
            family=family_for_class(pair[0]) if pair else None,
            evidence_window_days=cfg.evidence_window_days,
            persist=False,
            pooling_kappa=cfg.pooling_kappa,
            lb_quantile=cfg.lb_quantile,
            source_ids=source_ids,
        )
    )
    pairs = (
        {pair}
        if pair
        else set(HistoryView(conn, as_of).permission_pairs(source_ids)) | set(evidence)
    )
    result: dict[tuple[str, str], LicenceView] = {}
    for ck, act in sorted(pairs):
        s = evidence.get((ck, act), ClassStats(ck, act, as_of, 0, 0, 0, 0, 0, 0.0, 0.0))
        if _parse_ts(s.as_of) != _parse_ts(as_of):
            raise ValueError("Evidence cutoff mismatch")
        family = family_for_class(ck)
        cap = get_action_cap(
            act,
            family=family,
            sender_tier=ck.split("|")[-1] if family == "email_action" else None,
            organizer_tier=ck.split("|")[1] if family == "invite_rsvp" and "|" in ck else None,
        )
        exam_ids = {
            level: get_latest_passing_exam_id(
                conn, ck, act, as_of, level, cfg.exam_valid_days, config=cfg
            )
            for level in (2, 3)
        }

        def exam_ok(
            level: int, pair: tuple[str, str] = (ck, act), ids: dict[int, str | None] = exam_ids
        ) -> bool:
            return exam_ok_fn(*pair, level) if exam_ok_fn else ids[level] is not None

        level = derive_licence_level(
            act,
            s.n_all,
            s.lb_all,
            s.n_strong,
            s.lb_strong,
            s.n_recent,
            exam_ok_fn=exam_ok,
            cap=cap,
            l1_min_n=cfg.l1_min_n,
            l1_min_lb=cfg.l1_min_lb,
            l2_min_lb=cfg.l2_min_lb,
            l3_min_lb=cfg.l3_min_lb,
            strong_min_raw_n=cfg.strong_min_raw_n,
            licence_min_recent_n=cfg.licence_min_recent_n,
        )
        reasons = []
        if not s.n_all:
            reasons.append("no_eligible_evidence")
        if s.n_strong < cfg.strong_min_raw_n:
            reasons.append("insufficient_strong_evidence")
        if s.n_recent < cfg.licence_min_recent_n:
            reasons.append("insufficient_recent_evidence")
        if not exam_ids[2]:
            reasons.append("no_valid_exam")
        if cap < 3:
            reasons.append(f"hard_cap_{cap}")
        result[(ck, act)] = LicenceView(
            class_key=ck,
            action=act,
            level=level,
            lower_bound=s.lb_strong if int(level) >= 2 else s.lb_all,
            lb_strong=s.lb_strong,
            lb_all=s.lb_all,
            exam_ok=exam_ids[2] is not None,
            n_strong=s.n_strong,
            k_strong=s.k_strong,
            n_all=s.n_all,
            k_all=s.k_all,
            n_recent=s.n_recent,
            exam_run_id=exam_ids[int(level)] if int(level) >= 2 else exam_ids[2],
            valid_until=format_timestamp(_parse_ts(as_of) + timedelta(days=cfg.licence_ttl_days)),
            reasons=reasons,
        )
    return result


def derive_and_cache_licences(
    conn: sqlite3.Connection,
    as_of: str,
    stats: dict[tuple[str, str], ClassStats] | None = None,
    exam_ok_fn: Callable[[str, str, int], bool] | None = None,
) -> dict[tuple[str, str], LicenceView]:
    """Examiner-owned persistence of the same read-only derivation."""
    access = RoleAccess(conn, Role.EXAMINER)
    with access.transaction():
        from probation.engine.drift_baseline import posterior_error
        from probation.engine.evidence import aggregate_evidence

        if stats is None:
            stats = aggregate_evidence(
                access.conn,
                as_of,
                persist=False,
                evidence_window_days=settings.evidence_window_days,
            )
        views = derive_licences(access.conn, as_of, stats=stats, exam_ok_fn=exam_ok_fn)
        for (ck, act), view in views.items():
            row = access.conn.execute(
                "SELECT level FROM licence_cache WHERE class_key=? AND action=?", (ck, act)
            ).fetchone()
            old = int(row[0]) if row else 0
            access.execute_write(
                "licence_cache",
                """INSERT OR REPLACE INTO licence_cache
                (class_key,action,level,lower_bound,reasons_json,exam_run_id,computed_at,valid_until)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    ck,
                    act,
                    int(view.level),
                    view.lower_bound,
                    json.dumps(view.reasons),
                    view.exam_run_id,
                    as_of,
                    view.valid_until,
                ),
            )
            if old != int(view.level):
                baseline = posterior_error(
                    stats,
                    (ck, act),
                    int(view.level),
                    kappa=settings.pooling_kappa,
                    default=settings.cusum_base_err_default,
                )
                access.execute_write(
                    "drift_state",
                    """INSERT INTO drift_state(class_key,action,cusum,baseline_err,last_alarm_at)
                    VALUES (?,?,0,?,NULL) ON CONFLICT(class_key,action)
                    DO UPDATE SET baseline_err=excluded.baseline_err""",
                    (ck, act, baseline),
                )
                access.append_ledger(
                    LedgerKind.LICENCE_CHANGE,
                    f"{ck}::{act}",
                    {
                        "class_key": ck,
                        "action": act,
                        "old_level": old,
                        "new_level": int(view.level),
                        "lower_bound": view.lower_bound,
                        "reasons": view.reasons,
                        "baseline_err": baseline,
                        "posterior_mean": 1.0 - baseline,
                    },
                    created_at=as_of,
                )
        return views
