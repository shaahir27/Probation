"""Bounded immutable permission cohorts; no final-state outcomes or cache truth."""

import json
import sqlite3
from typing import Any

from probation.core.clock import timestamp_key
from probation.db.guards import ReadConnection


def _stored_payload(raw: object) -> dict[str, Any] | None:
    """Parse a stored provider payload. Malformed provenance fails closed, never raises."""
    if raw is None or raw == "":
        return {}
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def permission_records(
    conn: sqlite3.Connection | ReadConnection,
    as_of: str,
    family: str | None,
    source_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    if source_ids == ():
        return []
    source_clause = (
        f" AND r.source_id IN ({','.join('?' for _ in source_ids)})"
        if source_ids is not None
        else ""
    )
    rows = conn.execute(
        f"""SELECT p.*,s.pack,s.raw_item_id,s.occurred_at,s.sender_key,s.content_hash,
                  s.redacted_text,s.hands_off_reason,s.variant,r.payload_json AS raw_payload_json,
                  r.source_id,src.kind AS source_kind,
                  l.payload_json AS commitment,l.created_at AS committed_at
           FROM proposals p JOIN situations s ON s.id=p.situation_id
           JOIN raw_items r ON r.id=s.raw_item_id
           LEFT JOIN sources src ON src.id=r.source_id
           JOIN ledger l ON l.seq=p.ledger_seq AND l.kind='proposal' AND l.ref_id=p.id
           WHERE p.proposed_at COLLATE UTC_TIMESTAMP <= ?
             AND p.gate IN ('SHADOW','SUGGEST','ASK')
             AND p.action NOT IN ('ABSTAIN','LEAVE','NO_RESPONSE','NONE','REJECT')
             AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
             AND r.known_at COLLATE UTC_TIMESTAMP <= ?
             AND l.created_at COLLATE UTC_TIMESTAMP <= ?
             AND (? IS NULL OR p.family=?)
             {source_clause}
           ORDER BY p.proposed_at COLLATE UTC_TIMESTAMP,p.id""",
        (as_of, as_of, as_of, as_of, family, family, *(source_ids or ())),
    ).fetchall()
    proposals: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        commitment = json.loads(item.pop("commitment"))
        raw_payload = _stored_payload(item.get("raw_payload_json"))
        if raw_payload is None:
            continue
        gmail_source = item["source_kind"] == "gmail_live"
        if gmail_source and (
            raw_payload.get("retrospective") is not False
            or raw_payload.get("evidence_context")
            not in {"prospective", "prospective_synthetic", "live"}
            or commitment.get("retrospective") is not False
            or commitment.get("evidence_context")
            not in {"prospective", "prospective_synthetic", "live"}
            or commitment.get("evidence_context") != raw_payload.get("evidence_context")
        ):
            continue
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
        proposals[item["id"]] = item
    if not proposals:
        return []
    by_situation: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals.values():
        by_situation.setdefault(str(proposal["situation_id"]), []).append(proposal)
    decisions: dict[str, dict[str, Any]] = {}
    events = conn.execute(
        """SELECT seq,payload_json,created_at FROM ledger WHERE kind='outcome'
           AND created_at COLLATE UTC_TIMESTAMP <= ? ORDER BY seq""",
        (as_of,),
    ).fetchall()
    for event in events:
        value = json.loads(event["payload_json"])
        sid = value.get("situation_id")
        candidates = [
            proposal
            for proposal in by_situation.get(str(sid), [])
            if (value.get("proposal_id") is None and proposal.get("followup_of_action_id") is None)
            or value.get("proposal_id") == proposal["id"]
        ]
        if not candidates:
            continue
        proposal = candidates[0]
        proposal_id = str(proposal["id"])
        if proposal_id in decisions:
            continue
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
            or value.get("observed_action") in {"UNDO", "CANCEL", "OVERRIDE", "ABSTAIN"}
            or (value.get("observed_action") is None and value.get("decision") != "reject")
            or value.get("strength") not in {"STRONG", "WEAK"}
            or actor in {"executor", "system", "probation", "automation"}
            or value.get("retrospective")
            or details.get("retrospective")
        ):
            continue
        decisions[proposal_id] = {**value, "ledger_seq": event["seq"]}
    # Follow-ups concern the same source situation; asking it twice cannot
    # manufacture two independent votes. Prefer its eligible initial decision.
    records: dict[str, dict[str, Any]] = {}
    for proposal_id, proposal in sorted(
        proposals.items(),
        key=lambda item: (
            item[1].get("followup_of_action_id") is not None,
            timestamp_key(item[1]["proposed_at"]),
            item[0],
        ),
    ):
        if proposal_id in decisions:
            records.setdefault(
                str(proposal["situation_id"]), {**proposal, "decision": decisions[proposal_id]}
            )
    return list(records.values())


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
