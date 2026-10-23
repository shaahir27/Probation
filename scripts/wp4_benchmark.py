"""Synthetic, in-memory bounded-query benchmark; no published result mutation."""

import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Bind this script to its own worktree, not a different editable installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/src"))

from probation.core.clock import elapsed_seconds
from probation.core.history import HistoryView
from probation.db.connection import apply_schema, get_connection
from probation.db.ledger import append_ledger


def benchmark(
    size: int, timer: Callable[[], float] = elapsed_seconds
) -> dict[str, Any]:
    conn = get_connection(":memory:")
    apply_schema(conn)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    cutoff = (base + timedelta(hours=size + 1)).isoformat()
    conn.execute(
        "INSERT INTO sources VALUES ('bench','files','synthetic','benchmark',?)",
        (cutoff,),
    )
    reference: list[tuple[str, str]] = []
    for i in range(size):
        sid, raw = f"s-{i}", f"r-{i}"
        when = (base + timedelta(hours=i)).isoformat()
        origin = f"origin-{i % 17}"
        action = "LEAVE" if i % 3 == 0 else f"MOVE_TO_FOLDER:Folder/{i % 7}"
        reference.append((origin, action))
        conn.execute(
            """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,
                     occurred_at,known_at,payload_json,content_hash)
                     VALUES (?,'bench','files','file',?,?,?,'{}','hash')""",
            (raw, raw, when, when),
        )
        conn.execute(
            """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,
                     sender_key,content_hash,created_at)
                     VALUES (?,?,'files','file_destination',?,?,'hash',?)""",
            (sid, raw, when, origin, when),
        )
        append_ledger(
            conn,
            "outcome",
            sid,
            {
                "situation_id": sid,
                "observed_action": action,
                "strength": "STRONG",
                "source": "footprint",
                "known_at": when,
            },
            when,
        )
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    started = timer()
    result = HistoryView(conn, cutoff).file_statistics("origin-0")
    elapsed = timer() - started
    conn.set_trace_callback(None)
    actions = [a for origin, a in reference if origin == "origin-0"]
    folders = Counter(
        a.partition(":")[2] for a in actions if a.startswith("MOVE_TO_FOLDER:")
    )
    folder = min(folders, key=lambda f: (-folders[f], f))
    expected = {
        "n_prior_from_origin": len(actions),
        "top_folder_for_origin": folder,
        "top_folder_share": (folders[folder] + 1) / (len(actions) + 2),
    }
    if result != expected:
        raise AssertionError("aggregate differs from independent scan")
    plan = conn.execute("EXPLAIN QUERY PLAN " + statements[0]).fetchall()
    returned_rows = len(conn.execute(statements[0]).fetchall())
    conn.close()
    return {
        "size": size,
        "queries": len(statements),
        "seconds": elapsed,
        "matching_situations": len(actions),
        "returned_rows": returned_rows,
        "output_fields": len(result),
        "scan_parity": True,
        "query_plan": [str(r[3]) for r in plan],
    }


def benchmark_mail_calendar(
    size: int, family: str, timer: Callable[[], float] = elapsed_seconds
) -> dict[str, Any]:
    """Independent scan arithmetic versus the actual bounded aggregate consumers."""
    conn = get_connection(":memory:")
    apply_schema(conn)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    cutoff = (base + timedelta(hours=size + 2)).isoformat()
    pack = "mail" if family == "email_action" else "calendar"
    conn.execute(
        "INSERT INTO sources VALUES ('bench',?,'synthetic','benchmark',?)",
        (pack, cutoff),
    )
    records = []
    for i in range(size):
        sid, raw = f"s-{i}", f"r-{i}"
        when = base + timedelta(hours=i)
        sender = f"person{i % 17}@example.test"
        selected = i % 3 == 0
        payload = {
            "from": sender,
            "to": "owner@example.test",
            "organizer": sender,
            "start_time": when.isoformat(),
            "end_time": (when + timedelta(hours=1)).isoformat(),
        }
        conn.execute(
            "INSERT INTO raw_items VALUES (?,'bench',?,?,?,?,?,?,'h')",
            (
                raw,
                pack,
                "mail_in" if pack == "mail" else "invite",
                raw,
                when.isoformat(),
                when.isoformat(),
                json.dumps(payload),
            ),
        )
        conn.execute(
            "INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,sender_key,content_hash,created_at) VALUES (?,?,?,?,?,?,'h',?)",
            (sid, raw, pack, family, when.isoformat(), sender, when.isoformat()),
        )
        action = (
            ("REPLY" if selected else "ARCHIVE")
            if pack == "mail"
            else ("ACCEPT" if selected else "DECLINE")
        )
        known = (when + timedelta(minutes=30)).isoformat()
        append_ledger(
            conn,
            "outcome",
            sid,
            {
                "situation_id": sid,
                "observed_action": action,
                "strength": "STRONG",
                "source": "footprint",
                "known_at": known,
            },
            known,
        )
        records.append((when, sender, selected))
    current_start = base + timedelta(hours=size // 2)
    current_end = current_start + timedelta(hours=1)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    started = timer()
    history = HistoryView(conn, cutoff)
    if pack == "mail":
        result = history.sender_statistics("person0@example.test")
    else:
        result = history.calendar_statistics(
            "person0@example.test",
            "current",
            current_start.isoformat(),
            current_end.isoformat(),
            "UTC",
        )
    elapsed = timer() - started
    conn.set_trace_callback(None)
    matching = [
        (t, chosen) for t, sender, chosen in records if sender == "person0@example.test"
    ]
    if pack == "mail":
        expected = {
            "messages": len(matching),
            "replies": sum(chosen for _, chosen in matching),
            "reply_hours": [0.5 for _, chosen in matching if chosen],
        }
    else:

        def bucket(hour: int) -> int:
            return 0 if hour < 9 else 1 if hour < 12 else 2 if hour < 17 else 3

        same_bucket = [
            (t, chosen)
            for t, _, chosen in records
            if bucket(t.hour) == bucket(current_start.hour)
        ]
        accepted = [t for t, _, chosen in records if chosen]
        expected = {
            "organizer_tier": "frequent"
            if len(matching) >= 10
            else "known"
            if matching
            else "unknown",
            "accept_rate_organizer": round(
                (sum(chosen for _, chosen in matching) + 1) / (len(matching) + 2), 4
            ),
            "accept_rate_hour_bucket": round(
                (sum(chosen for _, chosen in same_bucket) + 1) / (len(same_bucket) + 2),
                4,
            ),
            "conflicts_count": sum(
                max(t, current_start) < min(t + timedelta(hours=1), current_end)
                for t in accepted
            ),
            "adjacent_conflict": any(
                0 <= (current_start - t - timedelta(hours=1)).total_seconds() / 60 <= 30
                or 0 <= (t - current_end).total_seconds() / 60 <= 30
                for t in accepted
            ),
        }
    if result != expected:
        raise AssertionError(f"{family} aggregate differs from independent scan")
    plans, returned = [], []
    for statement in statements:
        plans.append(
            [str(row[3]) for row in conn.execute("EXPLAIN QUERY PLAN " + statement)]
        )
        returned.append(len(conn.execute(statement).fetchall()))
    conn.close()
    return {
        "family": family,
        "size": size,
        "queries": len(statements),
        "returned_rows": returned,
        "seconds": elapsed,
        "scan_parity": True,
        "query_plans": plans,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            [
                *[
                    {"family": "file_destination", **benchmark(n)}
                    for n in (250, 1000, 4000)
                ],
                *[
                    benchmark_mail_calendar(n, family)
                    for family in ("email_action", "invite_rsvp")
                    for n in (250, 1000, 4000)
                ],
            ],
            indent=2,
        )
    )
