"""Frozen counterfactual adapter: same feature/prediction code, no operational writes."""

import copy
import hashlib
from dataclasses import dataclass
from typing import Any

from probation.core.history import HistoryView
from probation.core.identity import normalize_address
from probation.core.types import Situation
from probation.engine.prediction import Prediction, PredictionSnapshot, evaluate_prediction
from probation.llm.consumers import RegisteredConsumer
from probation.llm.feature_pipeline import compute_features
from probation.llm.reader import ReaderCallable
from probation.packs.registry import registry


@dataclass(frozen=True)
class ExamPredictionContext:
    snapshot: PredictionSnapshot
    history: HistoryView
    consumer: RegisteredConsumer | None = None
    reader_callable: ReaderCallable | None = None

    def manifest(self) -> dict[str, Any]:
        from probation.config import settings
        from probation.llm.feature_pipeline import semantic_feature_version

        novelty = self.snapshot.novelty
        vectors = getattr(novelty, "training_vectors", None)
        return {
            "policy_digest": getattr(self.snapshot.policy, "policy_digest", ""),
            "policy_version": self.snapshot.policy.policy_version,
            "model_cutoff": getattr(self.snapshot.policy, "as_of", None),
            "history_cutoff": self.history.as_of,
            "history_digest": self.history.permission_history_digest(),
            "feature_version": semantic_feature_version(stub=self.reader_callable is not None),
            "novelty_type": type(novelty).__qualname__,
            "novelty_vectors": hashlib.sha256(vectors.tobytes()).hexdigest()
            if vectors is not None
            else None,
            "novelty_references": getattr(novelty, "reference_ids", []),
            "novelty_threshold": getattr(novelty, "threshold", None),
            "embedding_identity": getattr(getattr(novelty, "embedder", None), "identity", None),
            "audit_seed": self.snapshot.audit_seed,
            "audit_fraction": self.snapshot.audit_fraction,
            "attention_cost": self.snapshot.attention_cost,
            "configured_models": [settings.model_reader, settings.model_exam_edits],
        }

    def frozen(self) -> "ExamPredictionContext":
        from probation.engine.novelty import NoveltyDetector

        # ONNX sessions are read-only runtime capabilities, not pickleable model state.
        # Copy the fitted reference arrays/IDs while retaining the provisioned embedder.
        novelty = copy.copy(self.snapshot.novelty)
        if isinstance(novelty, NoveltyDetector):
            if novelty.training_vectors is not None:
                novelty.training_vectors = novelty.training_vectors.copy()
                novelty.training_vectors.flags.writeable = False
            novelty.reference_ids = list(novelty.reference_ids)
        else:
            novelty = copy.deepcopy(novelty)
        snapshot = PredictionSnapshot(
            copy.deepcopy(self.snapshot.policy),
            novelty,
            self.snapshot.audit_seed,
            self.snapshot.audit_fraction,
            self.snapshot.attention_cost,
        )
        return ExamPredictionContext(
            snapshot, self.history.frozen(), self.consumer, self.reader_callable
        )

    def predict(
        self, situation: Situation, payload: dict[str, Any], text: str, level: int
    ) -> Prediction:
        payload = dict(payload)
        if situation.pack == "mail":
            payload["body"] = text
            sender = normalize_address(str(payload.get("from") or payload.get("from_addr") or ""))
            situation = situation.model_copy(update={"sender_key": sender, "redacted_text": text})
        elif situation.pack == "calendar":
            situation = situation.model_copy(
                update={
                    "sender_key": normalize_address(str(payload.get("organizer", ""))),
                    "redacted_text": text,
                }
            )
        elif situation.pack == "files":
            if "name" in payload:
                payload["filename"] = payload["name"]
            if "size" in payload:
                payload["size_bytes"] = payload["size"]
            filename = str(payload.get("filename", ""))
            # The descriptor's hands-off function reads the situation text.
            text = f"Filename: {filename}"
            situation = situation.model_copy(update={"redacted_text": text})
        situation = situation.model_copy(update={"redacted_text": text})
        view = self.history.with_current_payload(situation.raw_item_id, payload)
        features = compute_features(
            situation, view, consumer=self.consumer, reader_callable=self.reader_callable
        )
        return evaluate_prediction(
            situation,
            features,
            registry.get_descriptor(situation.pack),
            self.snapshot,
            licence_level=level,
        )
