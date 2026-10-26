"""Build the fitted prediction snapshot shared by the Brain and Examiner."""

import sqlite3

from probation.config import settings
from probation.core.history import HistoryView
from probation.engine.novelty import EmbeddingProvider, NoveltyDetector, NoveltyUnavailable
from probation.engine.policy import Policy
from probation.engine.prediction import PredictionSnapshot
from probation.engine.training import build_cohort, fit_cohort
from probation.llm.feature_pipeline import semantic_feature_version


def build_runtime_snapshot(
    conn: sqlite3.Connection,
    family: str,
    as_of: str,
    *,
    embedder: EmbeddingProvider | None = None,
    reader_stub: bool = False,
) -> PredictionSnapshot:
    """Fit only on history visible at ``as_of``; failed novelty remains unavailable."""
    history = HistoryView(conn, as_of)
    cohort = build_cohort(history, family, semantic_feature_version(stub=reader_stub))
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
        # Prediction detects the unavailable detector and asks rather than inventing a score.
        pass
    return PredictionSnapshot(
        policy, novelty, settings.audit_seed, settings.audit_fraction, settings.attention_cost
    )
