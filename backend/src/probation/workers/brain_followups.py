"""Fresh restricted predictions, Brain-owned; Executor never rewrites proposals."""

import json
import sqlite3
from collections.abc import Mapping

from probation.core.clock import format_timestamp, timestamp_key
from probation.core.enums import GateDecision
from probation.core.hashing import det_id
from probation.core.history import HistoryView
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.proposals import persist_proposal
from probation.engine.licence import derive_licences
from probation.engine.policy import Policy
from probation.engine.prediction import PredictionSnapshot, evaluate_prediction
from probation.llm.consumers import RegisteredConsumer
from probation.llm.draft_persistence import prepare_reply_persistence
from probation.llm.reader import ReaderCallable
from probation.llm.writer import generate_reply
from probation.packs.registry import registry
from probation.workers.prediction import predict_current


def process_followups(
    conn: sqlite3.Connection,
    *,
    as_of: str,
    snapshots: Mapping[str, PredictionSnapshot],
    consumer: RegisteredConsumer | None = None,
    reader_callable: ReaderCallable | None = None,
    limit: int = 32,
) -> list[str]:
    if conn.in_transaction:
        raise ValueError("Brain followups require committed cancellation requests")
    if not 1 <= limit <= 100:
        raise ValueError("Invalid followup batch")
    now = format_timestamp(as_of)
    view = HistoryView(conn, now)
    access = RoleAccess(conn, Role.BRAIN)
    saved: list[str] = []
    licences = derive_licences(conn, now)
    for row in view.followup_records(limit):
        snapshot = snapshots.get(str(row["proposal_family"]))
        if (
            snapshot is None
            or not isinstance(snapshot.policy, Policy)
            or not snapshot.policy.is_fitted
            or not snapshot.policy.as_of
            or snapshot.policy.family != str(row["proposal_family"])
            or timestamp_key(snapshot.policy.as_of) > timestamp_key(now)
        ):
            continue  # no fabricated prediction or confidence without a real snapshot
        proposal_id = "followup-" + det_id("authority-followup-v1", row["cancelled_action_id"])
        if access.conn.execute("SELECT 1 FROM proposals WHERE id=?", (proposal_id,)).fetchone():
            continue
        situation = Situation(
            **{
                key: row[key]
                for key in (
                    "id",
                    "pack",
                    "family",
                    "raw_item_id",
                    "occurred_at",
                    "sender_key",
                    "content_hash",
                    "redacted_text",
                    "hands_off_reason",
                    "variant",
                    "created_at",
                )
            }
        )
        features, prediction = predict_current(
            situation,
            view,
            snapshot,
            as_of=now,
            licence_level=0,
            restriction_cap=1,
            consumer=consumer,
            reader_callable=reader_callable,
        )
        permission = licences.get((prediction.class_key, prediction.action))
        level = min(1, int(permission.level)) if permission is not None else 0
        prediction = evaluate_prediction(
            situation,
            features,
            registry.get_descriptor(situation.pack),
            snapshot,
            licence_level=level,
            restriction_cap=1,
        )
        proposal = Proposal(
            id=proposal_id,
            situation_id=situation.id,
            family=situation.family,
            class_key=prediction.class_key,
            action=prediction.action,
            probs=prediction.probs,
            p_max=prediction.p_max,
            novelty=prediction.novelty,
            novel=prediction.novel,
            licence_level=level,
            cap=min(1, prediction.cap),
            gate=prediction.gate,
            reasons=[*prediction.reasons, "authority_lost_followup"],
            params={},
            explanation={
                "original_proposal_id": row["original_proposal_id"],
                "cancelled_action_id": row["cancelled_action_id"],
                "prediction_as_of": now,
            },
            policy_version=snapshot.policy.policy_version,
            features_hash=features.features_hash,
            proposed_at=now,
            audit_holdout=prediction.audit_holdout,
            followup_of_action_id=str(row["cancelled_action_id"]),
        )
        draft = None
        if proposal.action == "REPLY" and proposal.gate == GateDecision.SUGGEST:
            raw = view.get_raw_item(situation.raw_item_id)
            if raw is None:
                continue
            source = json.loads(raw["payload_json"])
            writer = generate_reply(
                consumer,
                incoming=str(source.get("body", "")),
                original_sender=str(source.get("from") or source.get("from_addr") or ""),
                situation_id=situation.id,
                preview_warrants_reply=True,
            )
            proposal, draft = prepare_reply_persistence(proposal, situation, view, writer)
        persist_proposal(access, proposal, draft=draft)
        saved.append(proposal_id)
    return saved
