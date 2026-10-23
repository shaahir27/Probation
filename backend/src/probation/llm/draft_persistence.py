"""Prepare writer output for the existing Brain-owned atomic unit of work."""

import json
from email.utils import parseaddr

from probation.core.enums import GateDecision
from probation.core.history import HistoryView
from probation.core.types import Proposal, Situation
from probation.db.proposals import DraftRecord
from probation.llm.draft_validation import body_hash, validate_draft
from probation.llm.results import WriterOutcome


def prepare_reply_persistence(
    proposal: Proposal,
    situation: Situation,
    history: HistoryView,
    writer: WriterOutcome,
) -> tuple[Proposal, DraftRecord | None]:
    if proposal.action != "REPLY":
        raise ValueError("Reply persistence requires REPLY")
    if not writer.persistable or not writer.body or not writer.provenance.model_id:
        return proposal.model_copy(
            update={"gate": GateDecision.ASK, "reasons": [*proposal.reasons, "draft_unavailable"]}
        ), None
    raw = history.get_raw_item(situation.raw_item_id)
    if raw is None:
        raise ValueError("Reply source is not known")
    payload = json.loads(raw["payload_json"])
    recipient = parseaddr(str(payload.get("from") or payload.get("from_addr") or ""))[1]
    if not recipient or recipient != writer.recipient:
        raise ValueError("Reply recipient does not match source")
    validate_draft(
        writer.body, str(payload.get("body", "")), needs_user_input=writer.needs_user_input
    )
    params = {
        **proposal.params,
        "to_addr": recipient,
        "draft_proposal_id": proposal.id,
        "draft_body_hash": body_hash(writer.body),
        "thread_id": str(
            payload.get("thread_id") or payload.get("message_id") or raw["source_ref"]
        ),
    }
    reasons = [r for r in proposal.reasons if r != "draft_unavailable"]
    gate = GateDecision.SUGGEST if writer.needs_user_input else proposal.gate
    prepared = proposal.model_copy(
        update={
            "params": params,
            "gate": gate,
            "reasons": reasons,
            "explanation": {
                **proposal.explanation,
                "writer": writer.provenance.as_dict(),
                "draft_body_hash": body_hash(writer.body),
                "draft_validation_notes": list(writer.validation_notes),
            },
        }
    )
    draft = DraftRecord(
        body_text=writer.body,
        needs_user_input=writer.needs_user_input,
        validator_ok=True,
        model_id=writer.provenance.model_id,
        prompt_version=writer.provenance.prompt_version,
        created_at=proposal.proposed_at,
    )
    return prepared, draft
