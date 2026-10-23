"""Injected local embeddings and bounded-memory cosine novelty, ENGINE_SPEC 5."""

from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class NoveltyUnavailable(ValueError):
    """Missing/invalid embedding input is not an ordinary novelty score."""


class EmbeddingProvider(Protocol):
    identity: str

    def embed(self, texts: list[str]) -> NDArray[np.float64]: ...


class NoveltyDetector:
    def __init__(
        self,
        k: int = 10,
        percentile: float = 95.0,
        *,
        embedder: EmbeddingProvider | None = None,
        batch_size: int = 64,
    ) -> None:
        if k < 1 or not 0 <= percentile <= 100 or batch_size < 1:
            raise ValueError("invalid_novelty_configuration")
        if embedder is not None and not hasattr(embedder, "embed"):
            raise NoveltyUnavailable("invalid_embedding_provider")
        self.k, self.percentile = k, percentile
        self.embedder, self.batch_size = embedder, batch_size
        self._reset()

    def _reset(self) -> None:
        self.training_vectors: NDArray[np.float64] | None = None
        self.threshold = 1.0
        self.is_fitted = False
        self.status = "cold_start"
        self.reference_ids: list[str] = []
        self.family: str | None = None

    def _vectors(self, texts: list[str]) -> NDArray[np.float64]:
        if self.embedder is None:
            raise NoveltyUnavailable("embedding_provider_missing")
        if any(not t.strip() for t in texts):
            raise NoveltyUnavailable("empty_novelty_text")
        try:
            parts = [
                np.asarray(self.embedder.embed(texts[i : i + self.batch_size]), dtype=np.float64)
                for i in range(0, len(texts), self.batch_size)
            ]
        except Exception as exc:
            raise NoveltyUnavailable("embedding_inference_failed") from exc
        if any(
            x.ndim != 2 or x.shape[0] != min(self.batch_size, len(texts) - i * self.batch_size)
            for i, x in enumerate(parts)
        ):
            raise NoveltyUnavailable("invalid_embedding_shape")
        try:
            vectors = np.concatenate(parts)
        except ValueError as exc:
            raise NoveltyUnavailable("inconsistent_embedding_dimension") from exc
        if vectors.shape[1] == 0 or not np.isfinite(vectors).all():
            raise NoveltyUnavailable("invalid_embedding_values")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.isfinite(norms).all() or (norms == 0).any():
            raise NoveltyUnavailable("invalid_embedding_norm")
        return np.asarray(vectors / norms, dtype=np.float64)

    def fit(
        self, texts: list[str], *, reference_ids: list[str] | None = None, family: str | None = None
    ) -> "NoveltyDetector":
        self._reset()
        if len(texts) < self.k + 1:
            return self
        ids = reference_ids if reference_ids is not None else [str(i) for i in range(len(texts))]
        if len(ids) != len(texts) or len(set(ids)) != len(ids):
            raise NoveltyUnavailable("invalid_reference_identity")
        order = sorted(range(len(texts)), key=lambda i: ids[i])
        try:
            x = self._vectors([texts[i] for i in order])
            distances: list[float] = []
            # At most batch_size * N distances, never an unrestricted N * N allocation.
            for start in range(0, len(x), self.batch_size):
                d = np.clip(1.0 - x[start : start + self.batch_size] @ x.T, 0.0, 2.0)
                for offset, row in enumerate(d):
                    row[start + offset] = np.inf
                    # Stable sorting preserves reference-ID order for ties.
                    distances.append(float(np.mean(np.sort(row, kind="stable")[: self.k])))
            self.threshold = float(np.percentile(distances, self.percentile))
            self.training_vectors = x
            self.reference_ids = [ids[i] for i in order]
            self.family = family
            self.is_fitted = True
            self.status = "ready"
            return self
        except (ValueError, FloatingPointError):
            self._reset()
            self.status = "unavailable"
            raise

    def score(self, text: str, *, family: str | None = None) -> tuple[bool, float]:
        if self.status == "unavailable":
            raise NoveltyUnavailable("novelty_unavailable")
        if not self.is_fitted or self.training_vectors is None:
            return True, 1.0
        if family is not None and family != self.family:
            raise NoveltyUnavailable("novelty_family_mismatch")
        query = self._vectors([text])[0]
        if len(query) != self.training_vectors.shape[1]:
            raise NoveltyUnavailable("embedding_dimension_changed")
        distances = np.clip(1.0 - self.training_vectors @ query, 0.0, 2.0)
        distance = float(np.mean(np.sort(distances, kind="stable")[: self.k]))
        return bool(distance > self.threshold), distance

    def similarity_scores(self, text: str) -> dict[str, float]:
        """Bounded one-query similarities for eligible example selection, not evidence."""
        if not self.is_fitted or self.training_vectors is None:
            return {}
        query = self._vectors([text])[0]
        if query.shape[0] != self.training_vectors.shape[1]:
            raise NoveltyUnavailable("embedding_dimension_changed")
        scores = self.training_vectors @ query
        return {sid: float(score) for sid, score in zip(self.reference_ids, scores, strict=True)}


def is_novel_point(
    point: list[float], reference_points: list[list[float]], threshold: float
) -> bool:
    if len(reference_points) < 5:
        return True
    p, refs = np.asarray(point), np.asarray(reference_points)
    if not np.isfinite(p).all() or not np.isfinite(refs).all():
        raise NoveltyUnavailable("invalid_numeric_novelty")
    distances = np.linalg.norm(refs - p, axis=1)
    return bool(np.mean(np.sort(distances)[:5]) > threshold)
