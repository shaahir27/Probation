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
from probation.core.history_statistics import SUBJECT_DECISIONS
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
    plan = conn.execute(
        "EXPLAIN QUERY PLAN "
        + SUBJECT_DECISIONS
        + """
        SELECT d.action,COUNT(*) FROM situations s JOIN decisions d ON d.sid=s.id
        WHERE s.family='file_destination' AND s.sender_key=?
        AND s.occurred_at COLLATE UTC_TIMESTAMP <= ? AND s.id!=? GROUP BY d.action
        """,
        (
            "file_destination",
            "origin-0",
            cutoff,
            "",
            cutoff,
            cutoff,
            "origin-0",
            cutoff,
            "",
        ),
    ).fetchall()
    conn.close()
    return {
        "size": size,
        "queries": len(statements),
        "seconds": elapsed,
        "matching_situations": len(actions),
        "output_fields": len(result),
        "scan_parity": True,
        "query_plan": [str(r[3]) for r in plan],
    }


if __name__ == "__main__":
    print(json.dumps([benchmark(n) for n in (250, 1000, 4000)], indent=2))
