"""Novelty uses injected embeddings, strict comparisons and no download fallback."""

import numpy as np
import pytest

from probation.engine.novelty import NoveltyDetector, NoveltyUnavailable


class Embeddings:
    identity = "synthetic-vectors-v1"

    def embed(self, texts):
        return np.array([[1.0, 0.0] if t != "far" else [0.0, 1.0] for t in texts])


def test_identical_vectors_zero_threshold_are_not_novel():
    n = NoveltyDetector(k=2, embedder=Embeddings()).fit(["a", "b", "c"])
    assert n.threshold == 0
    assert n.score("a") == (False, 0)
    assert n.score("far") == (True, 1)
    n.fit(["a"])
    assert not n.is_fitted and n.score("a") == (True, 1)


def test_missing_model_is_unavailable_not_tfidf():
    n = NoveltyDetector(k=1)
    with pytest.raises(NoveltyUnavailable):
        n.fit(["a", "b"])
    assert not n.is_fitted


def test_invalid_embedding_and_failed_refit_clear_state():
    n = NoveltyDetector(k=1, embedder=Embeddings()).fit(["a", "b"])
    with pytest.raises(NoveltyUnavailable):
        n.fit(["", "b"])
    assert not n.is_fitted
    with pytest.raises(NoveltyUnavailable):
        NoveltyDetector(k=1, embedder=lambda _: None)
