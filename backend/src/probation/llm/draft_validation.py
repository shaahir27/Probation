"""Local reply checks and exact immutable edit bindings; no I/O or send authority.

These checks reject detectable unsupported content. They cannot prove semantic truth.
Uncertain commitments require user input and must not be sent autonomously.
"""

import hashlib
import json
import re
from dataclasses import dataclass

URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
TOKEN = re.compile(r"<[^>]+>|\[[A-Z_]+(?:\d+)?\]|\{[^}]+\}")
PERSON = re.compile(r"<PERSON_\d+>")
AMOUNT = re.compile(r"(?:[$₹€£]\s*\d[\d,.]*|\b\d[\d,.]*\s*(?:USD|INR|EUR|GBP)\b)", re.I)
NUMBER = re.compile(r"\b\d+(?:[.,:/-]\d+)*\b")
COMMITMENT = re.compile(
    r"\b(?:(?:I|we)['\u2019](?:ll|m|ve|re)|(?:I|we)\s+(?:will|shall|promise|guarantee|agree|commit|can|could|would|have|am|are|was|were|submitted|completed|attended|accept))\b",
    re.I,
)
DATE_WORD = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|January|February|March|April|May(?=\s+\d)|June|July|August|September|October|November|December|tomorrow|tonight|next week)\b",
    re.I,
)
PAYMENT = re.compile(r"\b(?:pay|transfer|wire|deposit)\b", re.I)


class DraftInvalid(ValueError):
    """A safe reason code, never body text."""


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_draft(
    body: str,
    incoming: str,
    *,
    allow_person_tokens: bool = False,
    needs_user_input: bool = False,
) -> tuple[str, ...]:
    if not 5 <= len(body) <= 1200 or not body.strip():
        raise DraftInvalid("draft_length")
    if any(ord(c) < 32 and c not in "\n\t\r" for c in body):
        raise DraftInvalid("draft_control_character")
    for pattern, reason in (
        (URL, "new_url"),
        (EMAIL, "new_address"),
        (AMOUNT, "new_amount"),
        (NUMBER, "new_number_or_date"),
    ):
        if not set(pattern.findall(body)).issubset(set(pattern.findall(incoming))):
            raise DraftInvalid(reason)
    if re.search(r"\b(?:attached|attachment|enclosed)\b", body, re.I):
        raise DraftInvalid("attachment_not_added")
    if not {word.casefold() for word in DATE_WORD.findall(body)} <= {
        word.casefold() for word in DATE_WORD.findall(incoming)
    }:
        raise DraftInvalid("unsupported_date")
    for token in TOKEN.findall(body):
        if not allow_person_tokens or not PERSON.fullmatch(token):
            raise DraftInvalid("unresolved_placeholder")
    if PAYMENT.search(body) and body.casefold().strip() not in incoming.casefold():
        raise DraftInvalid("payment_commitment")
    uncertain = COMMITMENT.search(body) is not None
    if uncertain and not needs_user_input:
        raise DraftInvalid("commitment_requires_review")
    return ("commitment_requires_review",) if uncertain else ()


@dataclass(frozen=True, slots=True)
class EditedReply:
    proposal_id: str
    draft_hash: str
    connection_id: str
    resource_id: str
    recipient: str
    body: str
    reviewed_hash: str
    action: str = "REPLY"


def approval_payload(
    *,
    proposal_id: str,
    draft_hash: str,
    connection_id: str,
    resource_id: str,
    recipient: str,
    body: str,
    incoming: str,
) -> EditedReply:
    """Server must supply bindings; a hash is not authentication or permission.

    Persist in immutable response storage under WP6/WP9, never overwrite a draft.
    Executor must reconstruct this binding from trusted state before accepting a hash.
    """
    values = {
        "proposal_id": proposal_id,
        "draft_hash": draft_hash,
        "connection_id": connection_id,
        "resource_id": resource_id,
        "recipient": recipient,
        "body": body,
        "action": "REPLY",
    }
    if any(not v.strip() for v in values.values()) or not EMAIL.fullmatch(recipient):
        raise DraftInvalid("approval_binding_missing")
    validate_draft(body, incoming, needs_user_input=True)
    encoded = json.dumps(
        {"version": "edited-reply-v1", **values},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return EditedReply(**values, reviewed_hash=body_hash(encoded))
