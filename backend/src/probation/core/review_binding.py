"""Canonical owner-reviewed operations; no account access or model inference."""

import hashlib
import json
import re
import sqlite3
from email.utils import getaddresses
from typing import Any

from probation.core.clock import parse_timestamp
from probation.core.hashing import canonical_json
from probation.core.history import HistoryView
from probation.core.identity import normalize_address
from probation.core.lifecycle import ApprovalBinding, binding_hash
from probation.core.lifecycle import SourceGrant as SourceGrant
from probation.db.guards import ReadConnection
from probation.llm.draft_validation import DraftInvalid, body_hash, validate_draft

FORWARD_SEPARATOR = "\n\n--- Forwarded message ---\n"
MAIL_ACTIONS = frozenset({"ARCHIVE", "TRASH", "LEAVE", "REPLY", "FORWARD"})
MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s@]+>")


def _address(value: str) -> str:
    if any(c in value for c in "\r\n"):
        raise DraftInvalid("invalid_mail_address")
    address = normalize_address(value)
    if not address or "@" not in address or len(getaddresses([value])) != 1:
        raise DraftInvalid("invalid_mail_address")
    return address


def build_review_binding(
    conn: sqlite3.Connection | ReadConnection,
    proposal_id: str,
    *,
    grant: SourceGrant,
    owner_id: str,
    restriction_revision: str,
    as_of: str,
    response: str,
    edited_action: str | None = None,
    edited_body: str | None = None,
    forward_recipient: str | None = None,
    allowed_forward_recipients: tuple[str, ...] = (),
) -> ApprovalBinding:
    row = conn.execute(
        """SELECT p.*,s.raw_item_id,s.pack,s.hands_off_reason FROM proposals p
        JOIN situations s ON s.id=p.situation_id WHERE p.id=?""",
        (proposal_id,),
    ).fetchone()
    if row is None or parse_timestamp(row["proposed_at"]) > parse_timestamp(as_of):
        raise DraftInvalid("proposal_not_known")
    if not owner_id or not restriction_revision or row["pack"] != "mail":
        raise DraftInvalid("supported_owner_operation_required")
    raw = HistoryView(conn, as_of).get_raw_item(row["raw_item_id"])
    if raw is None or raw["source_id"] != grant.source_id:
        raise DraftInvalid("source_grant_mismatch")
    if not all((grant.connection_id, grant.account_id, grant.from_addr)):
        raise DraftInvalid("source_grant_missing")
    payload = json.loads(raw["payload_json"])
    if not isinstance(payload, dict) or not raw["source_ref"]:
        raise DraftInvalid("source_identity_missing")
    if response not in {"accept", "reject", "edit", "leave"}:
        raise DraftInvalid("unsupported_response")
    action = "LEAVE" if response in {"reject", "leave"} else edited_action or row["action"]
    if action not in MAIL_ACTIONS:
        raise DraftInvalid("unsupported_mail_action")
    if response != "edit" and any(
        v is not None for v in (edited_action, edited_body, forward_recipient)
    ):
        raise DraftInvalid("edit_response_required")
    if row["hands_off_reason"] and action != "LEAVE":
        raise DraftInvalid("hands_off")
    # Reapply hard-coded hands-off rules if source fields have changed.
    from probation.packs.mail import MailPack

    incoming = str(payload.get("body", ""))
    subject = str(payload.get("subject", ""))
    if MailPack().hands_off_text(f"Subject: {subject}\n\n{incoming}") and action != "LEAVE":
        raise DraftInvalid("hands_off")
    source_hash = hashlib.sha256(
        canonical_json(
            {
                "payload": payload,
                "source_ref": raw["source_ref"],
                "content_hash": raw["content_hash"],
            }
        ).encode()
    ).hexdigest()
    params: dict[str, Any] = {
        "proposal_id": proposal_id,
        "review_response": response,
        "review_edited_action": edited_action,
        "review_body_edited": edited_body is not None,
        "message_id": raw["source_ref"],
        "from_addr": _address(grant.from_addr),
    }
    body = recipient = native_message = native_thread = None
    if action in {"REPLY", "FORWARD"}:
        if (
            payload.get("attachments")
            or payload.get("has_attachments")
            or payload.get("has_attachment")
        ):
            if action == "FORWARD":
                raise DraftInvalid("forward_attachment_policy")
        native_message = str(payload.get("message_id", ""))
        if not MESSAGE_ID.fullmatch(native_message):
            raise DraftInvalid("original_message_id_required")
        native_thread = str(payload.get("thread_id") or "") or None
        if native_thread and any(c in native_thread for c in "\r\n"):
            raise DraftInvalid("invalid_thread_identity")
        if any(c in subject for c in "\r\n"):
            raise DraftInvalid("invalid_subject")
    if action == "REPLY":
        if forward_recipient is not None:
            raise DraftInvalid("reply_recipient_is_original_sender")
        recipient = _address(str(payload.get("from") or payload.get("from_addr") or ""))
        draft = conn.execute("SELECT * FROM drafts WHERE proposal_id=?", (proposal_id,)).fetchone()
        original_params = json.loads(row["params_json"])
        if draft is None or not draft["validator_ok"]:
            raise DraftInvalid("stored_draft_required")
        if (
            original_params.get("draft_proposal_id") != proposal_id
            or original_params.get("to_addr") != recipient
            or original_params.get("draft_body_hash") != body_hash(draft["body_text"])
        ):
            raise DraftInvalid("draft_binding_mismatch")
        if edited_body is None and draft["needs_user_input"]:
            raise DraftInvalid("draft_needs_user_input")
        body = edited_body if edited_body is not None else str(draft["body_text"])
        validate_draft(body, incoming, needs_user_input=edited_body is not None)
        params.update(
            {
                "to_addr": recipient,
                "subject": "Re: " + subject,
                "in_reply_to": native_message,
                "thread_id": native_thread,
                "draft_proposal_id": proposal_id,
                "draft_body_hash": body_hash(body),
            }
        )
    elif action == "FORWARD":
        recipient = _address(forward_recipient or "")
        if recipient not in {_address(value) for value in allowed_forward_recipients}:
            raise DraftInvalid("forward_recipient_not_allowed")
        introduction = edited_body or ""
        if introduction:
            validate_draft(introduction, incoming, needs_user_input=True)
        body = introduction + FORWARD_SEPARATOR + incoming
        if len(body) > 4800 or any(ord(c) < 32 and c not in "\r\n\t" for c in body):
            raise DraftInvalid("forward_body_policy")
        params.update(
            {
                "to_addr": recipient,
                "subject": "Fwd: " + subject,
                "forward_source_id": native_message,
                "forward_introduction": introduction,
                "draft_body_hash": body_hash(body),
            }
        )
    elif edited_body is not None or forward_recipient is not None:
        raise DraftInvalid("body_not_applicable")
    return ApprovalBinding(
        owner_id=owner_id,
        connection_id=grant.connection_id,
        account_id=grant.account_id,
        resource_id=str(raw["source_ref"]),
        source_hash=source_hash,
        action=action,
        restriction_revision=restriction_revision,
        params=params,
        body_text=body,
        recipient=recipient,
        native_thread_id=native_thread,
        native_message_id=native_message,
        pack="mail",
    )


def validate_review_binding(
    conn: sqlite3.Connection | ReadConnection,
    proposal_id: str,
    binding: ApprovalBinding,
    *,
    grant: SourceGrant,
    as_of: str,
    allowed_forward_recipients: tuple[str, ...] = (),
) -> None:
    response = str(binding.params.get("review_response", ""))
    body = binding.body_text if binding.params.get("review_body_edited") else None
    if binding.action == "FORWARD" and binding.params.get("review_body_edited"):
        body = str(binding.params.get("forward_introduction", ""))
    expected = build_review_binding(
        conn,
        proposal_id,
        grant=grant,
        owner_id=binding.owner_id,
        restriction_revision=binding.restriction_revision,
        as_of=as_of,
        response=response,
        edited_action=binding.params.get("review_edited_action"),
        edited_body=body,
        forward_recipient=binding.recipient if binding.action == "FORWARD" else None,
        allowed_forward_recipients=allowed_forward_recipients,
    )
    if binding_hash(expected) != binding_hash(binding):
        raise DraftInvalid("review_binding_mismatch")
