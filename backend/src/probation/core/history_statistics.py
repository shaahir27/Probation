"""Targeted bounded aggregate queries, isolated from policy/network code."""

import json
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from probation.core.clock import parse_timestamp, timestamp_key
from probation.core.identity import normalize_address, normalize_user_addresses
from probation.db.guards import ReadConnection

# Match the conservative legacy projection: one known normal decision, allowing
# exact duplicate events but never treating a correction as another training vote.
DECISIONS = """WITH events AS MATERIALIZED (
 SELECT seq,json_extract(payload_json,'$.situation_id') AS sid,
        json_extract(payload_json,'$.observed_action') AS action,
        json_extract(payload_json,'$.strength') AS strength,
        json_extract(payload_json,'$.source') AS source,
        COALESCE(json_extract(payload_json,'$.actor'),json_extract(payload_json,'$.details.actor'),'user') AS actor,
        json_extract(payload_json,'$.known_at') AS known
 FROM ledger WHERE kind='outcome' AND created_at COLLATE UTC_TIMESTAMP <= ?
 AND json_extract(payload_json,'$.known_at') COLLATE UTC_TIMESTAMP <= ?
), eligible AS MATERIALIZED (
 SELECT sid,MIN(seq) AS first_seq FROM events GROUP BY sid
 HAVING COUNT(DISTINCT action)=1 AND SUM(CASE
 WHEN source IN ('footprint','user_response','window_close')
 AND actor NOT IN ('executor','system','probation','automation')
 AND action NOT IN ('UNDO','OVERRIDE','REJECT','CANCEL','ABSTAIN') THEN 0 ELSE 1 END)=0
), decisions AS (
 SELECT events.* FROM events JOIN eligible ON events.seq=eligible.first_seq
)
"""


SUBJECT_DECISIONS = DECISIONS.replace(
    "FROM ledger WHERE kind=",
    "FROM ledger WHERE json_extract(payload_json,'$.situation_id') IN ("
    "SELECT id FROM situations WHERE family=? AND sender_key=? "
    "AND occurred_at COLLATE UTC_TIMESTAMP <= ? AND id!=?) AND kind=",
)


def sender_statistics(
    conn: sqlite3.Connection | ReadConnection, as_of: str, sender: str, exclude: str | None
) -> dict[str, Any]:
    rows = conn.execute(
        SUBJECT_DECISIONS
        + """
        SELECT s.occurred_at,d.action,d.known FROM situations s
        LEFT JOIN decisions d ON d.sid=s.id
        JOIN raw_items r ON r.id=s.raw_item_id AND r.known_at COLLATE UTC_TIMESTAMP <= ?
        WHERE s.sender_key=? AND s.family='email_action'
          AND s.occurred_at COLLATE UTC_TIMESTAMP <= ? AND s.id!=?
        ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP,s.id
        """,
        (
            "email_action",
            sender,
            as_of,
            exclude or "",
            as_of,
            as_of,
            as_of,
            sender,
            as_of,
            exclude or "",
        ),
    ).fetchall()
    deltas = [
        (timestamp_key(r["known"]) - timestamp_key(r["occurred_at"])) / 3_600_000_000
        for r in rows
        if r["action"] == "REPLY" and r["known"]
    ]
    return {
        "messages": len(rows),
        "replies": len(deltas),
        "reply_hours": [d for d in deltas if d >= 0],
    }


def file_statistics(
    conn: sqlite3.Connection | ReadConnection, as_of: str, origin: str, exclude: str | None
) -> dict[str, Any]:
    rows = conn.execute(
        SUBJECT_DECISIONS
        + """
        SELECT d.action,COUNT(*) AS n FROM situations s
        LEFT JOIN decisions d ON d.sid=s.id
        JOIN raw_items r ON r.id=s.raw_item_id AND r.known_at COLLATE UTC_TIMESTAMP <= ?
        WHERE s.family='file_destination' AND s.sender_key=?
          AND s.occurred_at COLLATE UTC_TIMESTAMP <= ? AND s.id!=?
        GROUP BY d.action
        """,
        (
            "file_destination",
            origin,
            as_of,
            exclude or "",
            as_of,
            as_of,
            as_of,
            origin,
            as_of,
            exclude or "",
        ),
    ).fetchall()
    count = sum(int(r["n"]) for r in rows)
    folders = {
        str(r["action"]).partition(":")[2]: int(r["n"])
        for r in rows
        if str(r["action"]).startswith("MOVE_TO_FOLDER:")
    }
    folder = min(folders, key=lambda f: (-folders[f], f)) if folders else "none"
    return {
        "n_prior_from_origin": count,
        "top_folder_for_origin": folder,
        "top_folder_share": (folders.get(folder, 0) + 1.0) / (count + 2.0),
    }


def historical_examples(
    candidates: list[dict[str, Any]], scores: dict[str, float], action: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Caller supplies only bounded eligible cohort rows and real similarity scores."""
    if not 0 <= limit <= 3:
        raise ValueError("invalid_example_limit")
    eligible = [r for r in candidates if r.get("action") == action and r["situation_id"] in scores]
    return sorted(eligible, key=lambda r: (-scores[r["situation_id"]], r["situation_id"]))[:limit]


def calendar_statistics(
    conn: sqlite3.Connection | ReadConnection,
    as_of: str,
    organizer: str,
    current_id: str,
    start: str,
    end: str,
    timezone: str,
) -> dict[str, Any]:
    """Single bounded calendar pass; final snapshot status never supplies RSVP truth."""
    zone = ZoneInfo(timezone)
    start_dt = parse_timestamp(start).astimezone(zone)
    end_dt = parse_timestamp(end).astimezone(zone)
    if start_dt.tzinfo is None or end_dt < start_dt:
        raise ValueError("invalid_calendar_interval")

    def bucket(hour: int) -> int:
        return 0 if hour < 9 else 1 if hour < 12 else 2 if hour < 17 else 3

    from probation.core.history_wp4 import decision_projection

    decisions = decision_projection(conn, as_of)
    rows = conn.execute(
        """SELECT s.id,s.sender_key,r.payload_json FROM situations s
        JOIN raw_items r ON r.id=s.raw_item_id
        WHERE s.family='invite_rsvp' AND s.id!=?
        AND s.occurred_at COLLATE UTC_TIMESTAMP <= ? AND r.known_at COLLATE UTC_TIMESTAMP <= ?""",
        (current_id, as_of, as_of),
    ).fetchall()
    organized = accepted_org = matching_bucket = accepted_bucket = conflicts = 0
    adjacent = False
    for row in rows:
        payload = json.loads(row["payload_json"])
        decision = decisions.get(str(row["id"]), {})
        accepted = bool(decision.get("eligible")) and decision.get("observed_action") == "ACCEPT"
        if normalize_address(row["sender_key"] or "") == organizer:
            organized += 1
            accepted_org += int(accepted)
        try:
            prior_start = parse_timestamp(payload["start_time"]).astimezone(zone)
            prior_end = parse_timestamp(payload["end_time"]).astimezone(zone)
        except (KeyError, TypeError, ValueError):
            continue
        if bucket(prior_start.hour) == bucket(start_dt.hour):
            matching_bucket += 1
            accepted_bucket += int(accepted)
        if accepted:
            conflicts += int(max(start_dt, prior_start) < min(end_dt, prior_end))
            before = (start_dt - prior_end).total_seconds() / 60
            after = (prior_start - end_dt).total_seconds() / 60
            adjacent |= 0 <= before <= 30 or 0 <= after <= 30
    mail = (
        conn.execute(
            """SELECT payload_json FROM raw_items WHERE pack='mail'
        AND known_at COLLATE UTC_TIMESTAMP <= ? AND payload_json LIKE ?""",
            (as_of, "%" + organizer + "%"),
        ).fetchall()
        if organizer
        else []
    )
    interactions = 0
    for row in mail:
        payload = json.loads(row["payload_json"])
        recipients = normalize_user_addresses(
            [str(payload.get("to", "")), str(payload.get("cc", ""))]
        )
        interactions += int(
            normalize_address(payload.get("from", "")) == organizer or organizer in recipients
        )
    total = organized + interactions
    return {
        "organizer_tier": "frequent" if total >= 10 else "known" if total else "unknown",
        "accept_rate_organizer": round((accepted_org + 1) / (organized + 2), 4),
        "accept_rate_hour_bucket": round((accepted_bucket + 1) / (matching_bucket + 2), 4),
        "conflicts_count": conflicts,
        "adjacent_conflict": adjacent,
    }
