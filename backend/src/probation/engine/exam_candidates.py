"""Deterministic bounded exam scheduling from Examiner-owned review snapshots."""

import json
import sqlite3

from probation.config import settings
from probation.core.clock import format_timestamp, parse_timestamp, timestamp_key
from probation.core.hashing import canonical_json, det_id
from probation.core.history import HistoryView
from probation.db.guards import ReadConnection
from probation.engine.caps import get_action_cap, is_recallable


def find_exam_candidates(
    conn: sqlite3.Connection,
    as_of: str,
    max_candidates: int | None = None,
    strong_min_raw_n: int | None = None,
    licence_min_recent_n: int | None = None,
    l2_min_lb: float | None = None,
    l3_min_lb: float | None = None,
) -> list[tuple[str, str, int]]:
    """Identify (class_key, action, target_level) candidates qualifying numerically without a valid exam pass.

    Authority: docs/ENGINE_SPEC.md section 15.0:
    At each LICENCE_REVIEW, for every (c, a) whose evidence meets the numeric bar for level 2 (or 3)
    but has no valid passing exam (section 6.3), queue an exam for the highest level it qualifies for.
    Start at most EXAM_MAX_PER_DAY per review tick, oldest candidate first.
    """
    from probation.engine.licence import check_exam_ok, family_for_class

    strong_min_raw_n = settings.strong_min_raw_n if strong_min_raw_n is None else strong_min_raw_n
    licence_min_recent_n = (
        settings.licence_min_recent_n if licence_min_recent_n is None else licence_min_recent_n
    )
    l2_min_lb = settings.l2_min_lb if l2_min_lb is None else l2_min_lb
    l3_min_lb = settings.l3_min_lb if l3_min_lb is None else l3_min_lb
    max_cand = (
        min(max_candidates, settings.exam_max_per_day)
        if max_candidates is not None
        else settings.exam_max_per_day
    )
    day_start = format_timestamp(
        parse_timestamp(as_of).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    used = conn.execute(
        """SELECT count(*) FROM exam_runs
        WHERE started_at COLLATE UTC_TIMESTAMP >= ? AND started_at COLLATE UTC_TIMESTAMP <= ?""",
        (day_start, as_of),
    ).fetchone()[0]
    max_cand = max(0, max_cand - int(used))
    if not max_cand:
        return []
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='class_stats';")
    if cur.fetchone() is None:
        return []

    cur.execute(
        """
        SELECT class_key, action, n_strong, lb_strong, n_recent
        FROM class_stats
        WHERE as_of COLLATE UTC_TIMESTAMP = ?
        ORDER BY class_key,action;
        """,
        (as_of,),
    )
    rows = cur.fetchall()
    candidates: list[tuple[str, str, int]] = []

    records = HistoryView(conn, as_of).permission_records()
    oldest: dict[tuple[str, str], str] = {}
    for record in records:
        key = (record["class_key"], record["action"])
        oldest.setdefault(key, record["proposed_at"])
    rows = sorted(
        rows,
        key=lambda row: (
            timestamp_key(oldest.get((row["class_key"], row["action"]), as_of)),
            row["class_key"],
            row["action"],
        ),
    )
    for r in rows:
        c_key = str(r["class_key"])
        act = str(r["action"])
        n_strong = int(r["n_strong"])
        lb_strong = float(r["lb_strong"])
        n_recent = int(r["n_recent"])

        strong_ok = (n_strong >= strong_min_raw_n) and (n_recent >= licence_min_recent_n)
        if not strong_ok or lb_strong < l2_min_lb:
            continue

        family = family_for_class(c_key)
        cap = get_action_cap(
            act,
            family=family,
            sender_tier=c_key.split("|")[-1] if family == "email_action" else None,
            organizer_tier=c_key.split("|")[1]
            if family == "invite_rsvp" and "|" in c_key
            else None,
        )
        if not family or family in {"chain_followup", "link_triage"} or cap < 2:
            continue
        target_level = 2
        rec = is_recallable(act)
        if lb_strong >= l3_min_lb and rec and cap >= 3:
            target_level = 3

        has_valid_exam = check_exam_ok(
            conn, c_key, act, as_of, target_level, settings.exam_valid_days
        )
        previous = conn.execute(
            """SELECT details_json FROM exam_runs WHERE class_key=? AND action=?
            AND started_at COLLATE UTC_TIMESTAMP <= ? ORDER BY started_at COLLATE UTC_TIMESTAMP DESC,id LIMIT 1""",
            (c_key, act, as_of),
        ).fetchone()
        if previous:
            detail = json.loads(previous[0])
            if detail.get("reason") in {
                "insufficient_cases",
                "unfinished_exam",
                "invalid_snapshot",
            } and detail.get("evidence_fingerprint") == evidence_fingerprint(
                conn, c_key, act, as_of
            ):
                continue
        if not has_valid_exam:
            candidates.append((c_key, act, target_level))
            if len(candidates) >= max_cand:
                break

    return candidates


def evidence_fingerprint(
    conn: sqlite3.Connection | ReadConnection, ck: str, act: str, as_of: str
) -> str:
    from probation.engine.licence import family_for_class

    rows = HistoryView(conn, as_of).permission_records(family_for_class(ck))
    return det_id(
        canonical_json([row for row in rows if row["class_key"] == ck and row["action"] == act])
    )
