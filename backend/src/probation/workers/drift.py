"""Examiner-owned consumption of immutable, time-bounded outcome events."""

import json
import sqlite3

from probation.core.actions import InvalidAction, parse_action
from probation.core.clock import parse_timestamp
from probation.core.hashing import det_id
from probation.core.history import HistoryView
from probation.db.access import Role, RoleAccess
from probation.engine.drift import CUSUMTracker


def has_pending_drift(conn: sqlite3.Connection, class_key: str, action: str, as_of: str) -> bool:
    """A missing/broken review store denies execution, rather than assuming review."""
    try:
        return any(
            row["class_key"] == class_key and row["action"] == action
            for row in HistoryView(conn, as_of).get_unreviewed_outcome_events()
        )
    except (sqlite3.Error, ValueError, TypeError):
        return True


def review_outcome_events(conn: sqlite3.Connection, *, as_of: str) -> int:
    access = RoleAccess(conn, Role.EXAMINER)
    reviewed = 0
    with access.transaction():
        for event in HistoryView(access.conn, as_of).get_unreviewed_outcome_events():
            payload = json.loads(event["payload_json"])
            timestamp = str(payload.get("known_at", payload.get("undone_at", event["created_at"])))
            correction = payload.get("source") in {"undo", "override"}
            action = str(event["action"])
            pair = (str(event["class_key"]), action)
            # Silence and no-op predictions never enter the disagreement tracker. An action the
            # pack cannot render was already failed closed to ASK, so there is no habit whose
            # drift could be monitored -- but its receipt is still written below, because leaving
            # a reviewed-looking event unreviewed would deny execution for that class forever.
            try:
                predicted_noop = parse_action(action).is_noop
            except InvalidAction:
                predicted_noop = True
            eligible = not predicted_noop and payload.get("source") != "execution"
            if eligible:
                latest_row = access.conn.execute(
                    "SELECT MAX(known_at COLLATE UTC_TIMESTAMP) FROM drift_receipts WHERE class_key=? AND action=?",
                    pair,
                ).fetchone()
                latest = latest_row[0] if latest_row is not None else None
                if latest and parse_timestamp(str(latest)) > parse_timestamp(timestamp):
                    raise ValueError("Out-of-order drift review requires reconciliation")
                row = access.conn.execute(
                    "SELECT * FROM drift_state WHERE class_key=? AND action=?", pair
                ).fetchone()
                if (
                    row
                    and row["last_alarm_at"]
                    and parse_timestamp(row["last_alarm_at"]) > parse_timestamp(timestamp)
                ):
                    raise ValueError("Historical review cannot overwrite future drift state")
                previous = access.conn.execute(
                    """SELECT known_at FROM drift_receipts
                    WHERE class_key=? AND action=? AND is_correction=1
                    AND known_at COLLATE UTC_TIMESTAMP <= ? ORDER BY event_seq""",
                    (*pair, timestamp),
                ).fetchall()
                tracker = CUSUMTracker(
                    initial_s=float(row["cusum"]) if row else 0,
                    baseline_err=float(row["baseline_err"]) if row else 0.03,
                    last_alarm_at=row["last_alarm_at"] if row else None,
                    correction_times=tuple(str(item[0]) for item in previous),
                )
                alarm = tracker.update(
                    payload["observed_action"] != action or correction, correction, timestamp
                )
                access.execute_write(
                    "drift_state",
                    """INSERT INTO drift_state
                    (class_key,action,cusum,baseline_err,last_alarm_at) VALUES (?,?,?,?,?)
                    ON CONFLICT(class_key,action) DO UPDATE SET cusum=excluded.cusum,
                    baseline_err=excluded.baseline_err,last_alarm_at=excluded.last_alarm_at""",
                    (*pair, tracker.s, tracker.baseline_err, tracker.last_alarm_at),
                )
                if alarm:
                    access.append_ledger(
                        "drift_alarm",
                        det_id("drift-event-v1", str(event["seq"]), *pair),
                        {
                            "class_key": pair[0],
                            "action": action,
                            "cusum": tracker.s,
                            "kind": "cusum",
                            "alarm_at": timestamp,
                        },
                        timestamp,
                    )
            access.execute_write(
                "drift_receipts",
                "INSERT INTO drift_receipts VALUES (?,?,?,?,?)",
                (event["seq"], *pair, timestamp, int(correction)),
            )
            reviewed += 1
    return reviewed
