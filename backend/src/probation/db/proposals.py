"""Brain-owned atomic persistence of the final proposal and any validated draft."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from probation.core.hashing import canonical_json
from probation.core.types import Proposal
from probation.db.access import AccessError, Role, RoleAccess


class DraftRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    body_text: str = Field(min_length=5, max_length=1200)
    needs_user_input: bool
    validator_ok: bool
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    created_at: str

    @field_validator("validator_ok")
    @classmethod
    def validated(cls, value: bool) -> bool:
        if not value:
            raise ValueError("An unvalidated draft cannot be persisted as ready")
        return value


def _values(proposal: Proposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "situation_id": proposal.situation_id,
        "family": proposal.family,
        "class_key": proposal.class_key,
        "action": proposal.action,
        "probs_json": canonical_json(proposal.probs),
        "p_max": proposal.p_max,
        "novelty": proposal.novelty,
        "novel": int(proposal.novel),
        "licence_level": proposal.licence_level,
        "cap": proposal.cap,
        "gate": proposal.gate.value,
        "reasons_json": canonical_json(proposal.reasons),
        "params_json": canonical_json(proposal.params),
        "explanation_json": canonical_json(proposal.explanation),
        "web_json": canonical_json(proposal.web),
        "policy_version": proposal.policy_version,
        "features_hash": proposal.features_hash,
        "audit_holdout": int(proposal.audit_holdout),
        "proposed_at": proposal.proposed_at,
        "followup_of_action_id": proposal.followup_of_action_id,
    }


def _gmail_provenance(access: RoleAccess, situation_id: str) -> dict[str, Any]:
    """Carry committed Gmail cohort flags into the immutable proposal commitment."""
    row = access.conn.execute(
        """SELECT src.kind, raw.payload_json FROM situations s
        JOIN raw_items raw ON raw.id=s.raw_item_id
        JOIN sources src ON src.id=raw.source_id WHERE s.id=?""",
        (situation_id,),
    ).fetchone()
    if row is None or row["kind"] != "gmail_live":
        return {}
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("gmail_provenance_unavailable") from exc
    if not isinstance(payload, dict):
        raise ValueError("gmail_provenance_unqualified")
    context = payload.get("evidence_context")
    retrospective = payload.get("retrospective")
    if context not in {"prospective", "prospective_synthetic", "live", "backfill"}:
        raise ValueError("gmail_provenance_unqualified")
    if (context == "backfill") != (retrospective is True):
        raise ValueError("gmail_provenance_unqualified")
    if not isinstance(retrospective, bool):
        raise ValueError("gmail_provenance_unqualified")
    return {"evidence_context": context, "retrospective": retrospective}


def persist_proposal(
    access: RoleAccess, proposal: Proposal, *, draft: DraftRecord | None = None
) -> Proposal:
    """Commit one unit or join the caller's transaction; a retry cannot alter history.

    The caller generates/validates drafts before entering this function. If joining an
    outer transaction, its owner must commit before dispatching any external action.
    """
    if access.role != Role.BRAIN:
        raise AccessError("Only the brain may persist proposals")
    proposal = Proposal.model_validate(proposal.model_dump())
    values = _values(proposal)
    with access.transaction():
        provenance = _gmail_provenance(access, proposal.situation_id)
        if proposal.followup_of_action_id is not None:
            eligible = access.conn.execute(
                """SELECT 1 FROM actions a JOIN proposals p ON p.id=a.proposal_id
                JOIN ledger l ON l.ref_id=a.id AND l.kind='action'
                WHERE a.id=? AND a.status='CANCELLED' AND a.authority_kind='autonomous'
                AND p.situation_id=? AND p.family=? AND l.created_at COLLATE UTC_TIMESTAMP <= ?
                AND a.updated_at COLLATE UTC_TIMESTAMP <= ?
                AND json_extract(l.payload_json,'$.status')='CANCELLED'
                AND json_extract(l.payload_json,'$.reason')='licence_lost'
                AND json_extract(l.payload_json,'$.licence_lost_followup_requested')=1""",
                (
                    proposal.followup_of_action_id,
                    proposal.situation_id,
                    proposal.family,
                    proposal.proposed_at,
                    proposal.proposed_at,
                ),
            ).fetchone()
            if (
                eligible is None
                or proposal.licence_level > 1
                or proposal.cap > 1
                or proposal.gate.value not in {"SHADOW", "ASK", "SUGGEST"}
            ):
                raise ValueError("Invalid authority followup")
        existing = access.conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal.id,)
        ).fetchone()
        if existing is not None:
            if any(existing[key] != value for key, value in values.items()):
                raise ValueError("Retry would change an immutable proposal")
            saved = access.conn.execute(
                "SELECT * FROM drafts WHERE proposal_id = ?", (proposal.id,)
            ).fetchone()
            if (draft is None) != (saved is None):
                raise ValueError("Retry would change immutable draft presence")
            if draft is not None:
                if saved is None or any(
                    saved[key] != value for key, value in draft.model_dump().items()
                ):
                    raise ValueError("Retry would change an immutable draft")
            return proposal.model_copy(update={"ledger_seq": int(existing["ledger_seq"])})
        seq = access.append_ledger(
            "proposal",
            proposal.id,
            {
                "situation_id": proposal.situation_id,
                "class_key": proposal.class_key,
                "action": proposal.action,
                "p_max": proposal.p_max,
                "gate": proposal.gate.value,
                "licence_level": proposal.licence_level,
                "policy_version": proposal.policy_version,
                "features_hash": proposal.features_hash,
                "audit_holdout": proposal.audit_holdout,
                "followup_of_action_id": proposal.followup_of_action_id,
                **provenance,
            },
            proposal.proposed_at,
        )
        values["ledger_seq"] = seq
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        access.execute_write(
            "proposals",
            f"INSERT INTO proposals ({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        if draft is not None:
            if draft.needs_user_input and proposal.gate.value.startswith(("EXECUTE", "HOLD_")):
                raise ValueError("A draft needing user input cannot authorize an autonomous effect")
            fields = draft.model_dump()
            columns = ", ".join(fields)
            placeholders = ", ".join("?" for _ in fields)
            access.execute_write(
                "drafts",
                f"INSERT INTO drafts (proposal_id, {columns}) VALUES (?, {placeholders})",
                (proposal.id, *fields.values()),
            )
    return proposal.model_copy(update={"ledger_seq": seq})
