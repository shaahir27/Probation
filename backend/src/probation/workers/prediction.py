"""Role-level composition for a current/live tick; no persistence or target effects.

Replay and exam adapters use these same feature and pure prediction functions.
Connection polling, consent and durable supervision remain WP12 responsibilities.
"""

from probation.core.clock import format_timestamp, timestamp_key
from probation.core.history import HistoryView
from probation.core.types import Features, Situation
from probation.engine.prediction import Prediction, PredictionSnapshot, evaluate_prediction
from probation.llm.consumers import RegisteredConsumer
from probation.llm.feature_pipeline import compute_features
from probation.llm.reader import ReaderCallable
from probation.packs.registry import registry


def predict_current(
    situation: Situation,
    history: HistoryView,
    snapshot: PredictionSnapshot,
    *,
    as_of: str,
    licence_level: int,
    restriction_cap: int = 3,
    consumer: RegisteredConsumer | None = None,
    reader_callable: ReaderCallable | None = None,
) -> tuple[Features, Prediction]:
    if history.as_of != format_timestamp(as_of) or timestamp_key(as_of) < timestamp_key(
        situation.occurred_at
    ):
        raise ValueError("Prediction history and decision cutoff disagree")
    features = compute_features(
        situation, history, consumer=consumer, reader_callable=reader_callable
    )
    prediction = evaluate_prediction(
        situation,
        features,
        registry.get_descriptor(situation.pack),
        snapshot,
        licence_level=licence_level,
        restriction_cap=restriction_cap,
    )
    return features, prediction
