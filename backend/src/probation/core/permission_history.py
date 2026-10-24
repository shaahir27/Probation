"""Bounded immutable permission cohorts; no final-state outcomes or cache truth."""

import json
import sqlite3
from typing import Any

from probation.core.clock import timestamp_key
from probation.db.guards import ReadConnection


def permission_records(
    conn: sqlite3.Connection | ReadConnection, as_of: str, family: str | None
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT p.*,s.pack,s.raw_item_id,s.occurred_at,s.sender_key,s.content_hash,
                  s.redacted_text,s.hands_off_reason,s.variant,r.payload_json AS raw_payload_json,
                  l.payload_json AS commitment,l.created_at AS committed_at
           FROM proposals p JOIN situations s ON s.id=p.situation_id
           JOIN raw_items r ON r.id=s.raw_item_id
           JOIN ledger l ON l.seq=p.ledger_seq AND l.kind='proposal' AND l.ref_id=p.id
           WHERE p.proposed_at COLLATE UTC_TIMESTAMP <= ?
             AND p.gate IN ('SHADOW','SUGGEST','ASK')
             AND p.action NOT IN ('ABSTAIN','LEAVE','NO_RESPONSE','NONE','REJECT')
             AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
             AND r.known_at COLLATE UTC_TIMESTAMP <= ?
             AND l.created_at COLLATE UTC_TIMESTAMP <= ?
             AND (? IS NULL OR p.family=?)
           ORDER BY p.proposed_at COLLATE UTC_TIMESTAMP,p.id""",
        (as_of, as_of, as_of, as_of, family, family),
    ).fetchall()
    proposals: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        commitment = json.loads(item.pop("commitment"))
        if (
            commitment.get("situation_id") != item["situation_id"]
            or commitment.get("class_key") != item["class_key"]
            or commitment.get("action") != item["action"]
            or commitment.get("gate") != item["gate"]
            or commitment.get("retrospective")
            or commitment.get("evidence_context", "prospective")
            not in {"prospective", "prospective_synthetic", "live"}
            or timestamp_key(item["committed_at"]) != timestamp_key(item["proposed_at"])
        ):
            continue
        proposals[item["situation_id"]] = item
    if not proposals:
        return []
    decisions: dict[str, dict[str, Any]] = {}
    events = conn.execute(
        """SELECT seq,payload_json,created_at FROM ledger WHERE kind='outcome'
           AND created_at COLLATE UTC_TIMESTAMP <= ? ORDER BY seq""",
        (as_of,),
    ).fetchall()
    for event in events:
        value = json.loads(event["payload_json"])
        sid = value.get("situation_id")
        if sid not in proposals or sid in decisions:
            continue
        proposal = proposals[sid]
        known = value.get("known_at")
        details = value.get("details") or {}
        if not isinstance(details, dict):
            continue
        actor = value.get("actor", details.get("actor"))
        if (
            not isinstance(known, str)
            or timestamp_key(known) > timestamp_key(as_of)
            or timestamp_key(known) <= timestamp_key(proposal["proposed_at"])
            or timestamp_key(event["created_at"]) < timestamp_key(known)
            or event["seq"] <= proposal["ledger_seq"]
            or value.get("source") not in {"footprint", "user_response", "window_close"}
            or value.get("observed_action") in {None, "UNDO", "CANCEL", "OVERRIDE", "ABSTAIN"}
            or value.get("strength") not in {"STRONG", "WEAK"}
            or actor in {"executor", "system", "probation", "automation"}
            or value.get("retrospective")
            or details.get("retrospective")
        ):
            continue
        decisions[sid] = value
    return [
        {**proposal, "decision": decisions[sid]}
        for sid, proposal in proposals.items()
        if sid in decisions
    ]


def alarm_times(
    conn: sqlite3.Connection | ReadConnection,
    as_of: str,
    class_key: str,
    action: str,
    family: str,
) -> list[str]:
    """Ledger retains earlier alarms even when the latest mutable state is future."""
    aliases = {
        "email_action": {"email_action", "mail", "email"},
        "invite_rsvp": {"invite_rsvp", "cal", "calendar"},
        "file_destination": {"file_destination", "file", "files"},
        "opportunity_triage": {"opportunity_triage", "radar"},
        "link_triage": {"link_triage", "link", "reading"},
        "chain_followup": {"chain_followup", "chain", "chains"},
    }.get(family, {family})
    result: list[str] = []
    for row in conn.execute(
        """SELECT payload_json,created_at FROM ledger WHERE kind='drift_alarm'
           AND created_at COLLATE UTC_TIMESTAMP <= ?""",
        (as_of,),
    ).fetchall():
        value = json.loads(row["payload_json"])
        pair_alarm = (value.get("class_key"), value.get("action")) == (class_key, action)
        family_alarm = value.get("family") in aliases
        if pair_alarm or family_alarm:
            alarm_at = (
                value.get("alarm_at", row["created_at"])
                if pair_alarm
                else value.get("week_start", row["created_at"])
            )
            if timestamp_key(str(alarm_at)) <= timestamp_key(as_of):
                result.append(str(alarm_at))
    row = conn.execute(
        """SELECT last_alarm_at FROM drift_state WHERE class_key=? AND action=?
           AND last_alarm_at COLLATE UTC_TIMESTAMP <= ?""",
        (class_key, action, as_of),
    ).fetchone()
    if row and row[0]:
        result.append(str(row[0]))
    for row in conn.execute(
        """SELECT family,week_start FROM family_shift WHERE alarm=1
           AND week_start COLLATE UTC_TIMESTAMP <= ?""",
        (as_of,),
    ).fetchall():
        if row["family"] in aliases:
            result.append(str(row["week_start"]))
    return result
