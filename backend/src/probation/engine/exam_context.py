"""Rebuild the ordinary bounded WP4 inference state for standalone Examiner jobs."""

import sqlite3

from probation.core.history import HistoryView
from probation.engine.exam_prediction import ExamPredictionContext
from probation.engine.licence import family_for_class
from probation.engine.novelty import EmbeddingProvider
from probation.engine.runtime_snapshot import build_runtime_snapshot
from probation.llm.consumers import RegisteredConsumer, offline_consumer
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
    return ExamPredictionContext(
        build_runtime_snapshot(
            conn, family, as_of, embedder=embedder, reader_stub=reader_callable is not None
        ),
        history,
        consumer or offline_consumer(conn),
        reader_callable,
    )
