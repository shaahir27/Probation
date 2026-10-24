"""Rebuild the ordinary bounded WP4 inference state for standalone Examiner jobs."""

import sqlite3

from probation.config import settings
from probation.core.history import HistoryView
from probation.engine.exam_prediction import ExamPredictionContext
from probation.engine.licence import family_for_class
from probation.engine.novelty import EmbeddingProvider, NoveltyDetector, NoveltyUnavailable
from probation.engine.policy import Policy
from probation.engine.prediction import PredictionSnapshot
from probation.engine.training import build_cohort, fit_cohort
from probation.llm.consumers import RegisteredConsumer, offline_consumer
from probation.llm.feature_pipeline import semantic_feature_version
from probation.llm.reader import ReaderCallable


def build_exam_context(
    conn: sqlite3.Connection,
    class_key: str,
    as_of: str,
    *,
    consumer: RegisteredConsumer | None = None,
    reader_callable: ReaderCallable | None = None,
    embedder: EmbeddingProvider | None = None,
) -> ExamPredictionContext:
    history = HistoryView(conn, as_of)
    family = family_for_class(class_key)
    cohort = build_cohort(
        history, family, semantic_feature_version(stub=reader_callable is not None)
    )
    policy = fit_cohort(
        Policy(
            family,
            cold_start_min=settings.cold_start_min_situations,
            train_half_life_days=settings.train_half_life_days,
            files_topk=settings.files_topk_folders,
        ),
        cohort,
        as_of,
    )
    if embedder is None:
        from probation.local_embeddings import LocalMiniLM

        embedder = LocalMiniLM(settings.embedding_model_dir, settings.embedding_manifest_path)
    novelty = NoveltyDetector(settings.novelty_k, settings.novelty_pctl, embedder=embedder)
    refs = [row for row in cohort.rows if row.redacted_text.strip()]
    try:
        novelty.fit(
            [row.redacted_text for row in refs],
            reference_ids=[row.situation_id for row in refs],
            family=family,
        )
    except NoveltyUnavailable:
        # The shared prediction seam will return ASK; no fallback score is invented.
        pass
    return ExamPredictionContext(
        PredictionSnapshot(
            policy, novelty, settings.audit_seed, settings.audit_fraction, settings.attention_cost
        ),
        history,
        consumer or offline_consumer(conn),
        reader_callable,
    )
