"""Executor-only hydration of an immutable generated reply; no browser body trusted."""

import json
from email.utils import parseaddr
from typing import Any

from probation.core.history import HistoryView
from probation.db.access import Role, RoleAccess
from probation.llm.draft_validation import DraftInvalid, body_hash, validate_draft


def load_reply_params(access: RoleAccess, proposal_id: str, *, as_of: str) -> dict[str, Any]:
    if access.role is not Role.EXECUTOR:
        raise PermissionError("Only Executor may hydrate a send payload")
    row = access.conn.execute(
        """SELECT p.params_json,p.situation_id,d.body_text,d.validator_ok,d.needs_user_input,
                  s.raw_item_id FROM proposals p JOIN drafts d ON d.proposal_id=p.id
           JOIN situations s ON s.id=p.situation_id WHERE p.id=? AND p.action='REPLY'""",
        (proposal_id,),
    ).fetchone()
    if row is None or not row["validator_ok"] or row["needs_user_input"]:
        raise DraftInvalid("stored_ready_draft_required")
    raw = HistoryView(access.conn, as_of).get_raw_item(row["raw_item_id"])
    if raw is None:
        raise DraftInvalid("source_not_known")
    source = json.loads(raw["payload_json"])
    recipient = parseaddr(str(source.get("from") or source.get("from_addr") or ""))[1]
    params = json.loads(row["params_json"])
    body = str(row["body_text"])
    if (
        params.get("draft_proposal_id") != proposal_id
        or params.get("to_addr") != recipient
        or params.get("draft_body_hash") != body_hash(body)
    ):
        raise DraftInvalid("draft_binding_mismatch")
    validate_draft(body, str(source.get("body", "")))
    from probation.packs.identity import persisted_or_configured_owner

    owners = persisted_or_configured_owner(access.conn.cursor())
    if not owners:
        raise DraftInvalid("reply_owner_identity_unavailable")
    return {
        **params,
        "body": body,
        "from_addr": owners[0],
        "subject": "Re: " + str(source.get("subject", "")),
    }
