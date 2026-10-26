"""Reader -> isolated Webfacts -> bounded features -> unchanged pure prediction."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from probation.core.clock import Clock, timestamp_key
from probation.core.history import HistoryView
from probation.core.types import Features, Proposal, Situation
from probation.engine.prediction import Prediction, PredictionSnapshot, evaluate_prediction
from probation.llm.consumers import RegisteredConsumer
from probation.llm.feature_pipeline import compute_features
from probation.llm.reader import ReaderCallable
from probation.packs.registry import registry
from probation.web.types import VerificationCard


@dataclass(frozen=True, slots=True)
class WebObservation:
    cap: int = 3
    entities: list[dict[str, Any]] = field(default_factory=list)
    card: VerificationCard | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifiedPrediction:
    features: Features
    prediction: Prediction
    web: WebObservation
    cutoff: str


Verifier = Callable[[Situation, Features, HistoryView], WebObservation]


def email_verifier(
    conn: sqlite3.Connection,
    *,
    client: Any,
    consumer: RegisteredConsumer | None,
    clock: Clock,
) -> Verifier:
    """Compose the Webfacts-owned entity and optional opportunity jobs."""
    import json

    from probation.llm.gateway import JobFailure
    from probation.llm.jobs import OpportunityReader
    from probation.llm.prompt_loader import PromptAssetError
    from probation.web.derive import mail_link_domains
    from probation.web.verification import verify_email_opportunity
    from probation.workers.webfacts import verify_email_entities

    def verify(situation: Situation, features: Features, history: HistoryView) -> WebObservation:
        facts = verify_email_entities(
            conn, situation, features, history, client=client, clock=clock
        )
        card = None
        if features.reader and features.reader.get("intent") == "opportunity" and consumer:
            raw = history.get_raw_item(situation.raw_item_id)
            if raw is not None:
                payload = json.loads(raw["payload_json"])
                body = str(payload.get("body_text") or payload.get("body") or "")
                subject = str(payload.get("subject") or "")
                try:
                    output = consumer.call(
                        "reader.opportunity",
                        {"subject": subject, "body": body},
                        purpose="email_opportunity_verification",
                        prompt_version="v2",
                    )
                    fields = OpportunityReader.model_validate(dict(output.data))
                    # Public fields must be copied from the source, never invented.
                    source = (subject + "\n" + body).casefold()
                    names = (fields.organiser_name, fields.opportunity_name)
                    if all(name and name.casefold() in source for name in names):
                        card = verify_email_opportunity(
                            conn,
                            client,
                            consumer,
                            organiser_name=fields.organiser_name,
                            opportunity_name=fields.opportunity_name,
                            clock=clock,
                            mail_deadline=(
                                fields.deadline_text
                                if fields.deadline_text
                                and fields.deadline_text.casefold() in source
                                else None
                            ),
                            situation_id=situation.id,
                            mail_link_domains=mail_link_domains(body),
                        )
                    else:
                        card = VerificationCard(
                            availability="unavailable", reasons=["public_fields_unsupported"]
                        )
                except (JobFailure, PromptAssetError, ValueError):
                    card = VerificationCard(
                        availability="unavailable", reasons=["opportunity_reader_unavailable"]
                    )
        return WebObservation(
            cap=min((fact.web_cap for fact in facts), default=3),
            entities=[fact.model_dump() for fact in facts],
            card=card,
            reasons=tuple(reason for fact in facts for reason in fact.reasons),
        )

    return verify


def predict_verified_email(
    conn: sqlite3.Connection,
    situation: Situation,
    snapshot: PredictionSnapshot,
    *,
    clock: Clock,
    verify: Verifier,
    licence_level: int | Callable[[str, str, str], int],
    consumer: RegisteredConsumer | None = None,
    reader_callable: ReaderCallable | None = None,
) -> VerifiedPrediction:
    if situation.pack != "mail" or situation.family != "email_action":
        raise ValueError("D5 verifies email only")
    cutoff = clock.now_iso()
    if timestamp_key(cutoff) < timestamp_key(situation.occurred_at):
        raise ValueError("Decision precedes email")
    history = HistoryView(conn, cutoff)
    features = compute_features(
        situation, history, consumer=consumer, reader_callable=reader_callable
    )
    web = WebObservation(cap=0, reasons=("reader_unavailable",))
    if features.reader_ok and features.reader is not None:
        try:
            web = verify(situation, features, history)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            web = WebObservation(cap=0, reasons=("verification_unavailable",))
    final_cutoff = clock.now_iso()
    if timestamp_key(final_cutoff) < timestamp_key(cutoff):
        raise ValueError("Decision clock moved backwards")
    if final_cutoff != cutoff:
        history = HistoryView(conn, final_cutoff)
        features = compute_features(
            situation, history, consumer=consumer, reader_callable=reader_callable
        )
    pack = registry.get_descriptor(situation.pack)
    preview = evaluate_prediction(situation, features, pack, snapshot, licence_level=0)
    level = (
        licence_level(preview.class_key, preview.action, final_cutoff)
        if callable(licence_level)
        else licence_level
    )
    prediction = evaluate_prediction(
        situation, features, pack, snapshot, licence_level=level, restriction_cap=web.cap
    )
    return VerifiedPrediction(features, prediction, web, final_cutoff)


def persist_verified_email(
    conn: sqlite3.Connection,
    situation: Situation,
    snapshot: PredictionSnapshot,
    result: VerifiedPrediction,
    *,
    clock: Clock,
    consumer: RegisteredConsumer | None = None,
) -> Proposal:
    """Brain commits bounded features, one proposal and its validated draft atomically."""
    import json

    from probation.core.enums import GateDecision
    from probation.core.hashing import canonical_json, det_id
    from probation.db.access import Role, RoleAccess
    from probation.db.proposals import persist_proposal
    from probation.engine.licence import derive_licences
    from probation.llm.context import redaction_names
    from probation.llm.draft_persistence import prepare_reply_persistence
    from probation.llm.writer import generate_reply

    if conn.in_transaction:
        raise ValueError("Proposal composition requires committed observations")
    history = HistoryView(conn, result.cutoff)
    if history.get_outcomes([situation.id]):
        raise ValueError("A known outcome cannot follow a new prospective commitment")
    if history.get_raw_item(situation.raw_item_id) is None:
        raise ValueError("Proposal source not known")
    if situation.id in history.proposed_situation_ids():
        raise ValueError("An initial proposal is already committed")
    prediction, features = result.prediction, result.features
    licence = derive_licences(
        conn, result.cutoff, pair=(prediction.class_key, prediction.action)
    ).get((prediction.class_key, prediction.action))
    level = int(licence.level) if licence else 0
    # Persistence never turns an injected preview licence into execution authority.
    prediction = evaluate_prediction(
        situation,
        features,
        registry.get_descriptor("mail"),
        snapshot,
        licence_level=level,
        restriction_cap=result.web.cap,
    )
    sources = [source for entity in result.web.entities for source in entity.get("sources", [])]
    status = next(
        (str(entity["status"]) for entity in result.web.entities if entity.get("web_cap", 3) < 3),
        str(result.web.entities[0].get("status", "not_checked"))
        if result.web.entities
        else "not_checked",
    )
    proposal = Proposal(
        id=det_id("d5-proposal-v1", situation.id),
        situation_id=situation.id,
        family=situation.family,
        class_key=prediction.class_key,
        action=prediction.action,
        probs=prediction.probs,
        p_max=prediction.p_max,
        novelty=prediction.novelty,
        novel=prediction.novel,
        licence_level=level,
        cap=prediction.cap,
        gate=prediction.gate,
        reasons=list(dict.fromkeys((*prediction.reasons, *result.web.reasons))),
        web={
            "version": "d5.v1",
            "status": status,
            "cap": result.web.cap,
            "source_ids": [source["url"] for source in sources],
            "sources": sources,
            "entities": result.web.entities,
            "decision_cutoff": result.cutoff,
            "verification_card": result.web.card.model_dump() if result.web.card else None,
        },
        policy_version=snapshot.policy.policy_version,
        features_hash=features.features_hash,
        audit_holdout=prediction.audit_holdout,
        proposed_at=clock.now_iso(),
    )
    draft = None
    if proposal.action == "REPLY" and proposal.gate in {
        GateDecision.SUGGEST,
        GateDecision.HOLD_THEN_EXECUTE,
        GateDecision.EXECUTE_UNDO,
        GateDecision.EXECUTE_SILENT,
    }:
        raw = history.get_raw_item(situation.raw_item_id)
        assert raw is not None
        source = json.loads(raw["payload_json"])
        sender = str(source.get("from") or source.get("from_addr") or "")
        incoming = str(source.get("body_text") or source.get("body") or "")
        writer = generate_reply(
            consumer,
            incoming=incoming,
            original_sender=sender,
            situation_id=situation.id,
            preview_warrants_reply=True,
            display_names=redaction_names(sender, source.get("to", "")),
        )
        proposal, draft = prepare_reply_persistence(proposal, situation, history, writer)
    proposal = proposal.model_copy(update={"proposed_at": clock.now_iso()})
    if draft is not None:
        draft = draft.model_copy(update={"created_at": proposal.proposed_at})
    access = RoleAccess(conn, Role.BRAIN)
    with access.transaction():
        if HistoryView(conn, proposal.proposed_at).get_outcomes([situation.id]):
            raise ValueError("Outcome already known before commitment")
        access.execute_write(
            "features",
            """INSERT OR REPLACE INTO features
            (situation_id,deterministic_json,reader_json,reader_ok,featurizer_version,
            model_id,prompt_version,features_hash,created_at,provenance_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                situation.id,
                canonical_json(features.deterministic),
                canonical_json(features.reader) if features.reader is not None else None,
                int(features.reader_ok),
                features.featurizer_version,
                features.model_id,
                features.prompt_version,
                features.features_hash,
                result.cutoff,
                features.provenance_json,
            ),
        )
        return persist_proposal(access, proposal, draft=draft)
