"""K-NN distance-based novelty detector.

Authority: docs/ENGINE_SPEC.md section 5.
"""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


class NoveltyDetector:
    """K-NN cosine distance novelty detector for out-of-distribution situations."""

    def __init__(self, k: int = 10, percentile: float = 95.0) -> None:
        self.k = k
        self.percentile = percentile
        self.threshold: float = 1.0
        self.vectorizer: TfidfVectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=512,
            sublinear_tf=True,
            norm="l2",
        )
        self.training_vectors: np.ndarray | None = None
        self.is_fitted: bool = False

    def fit(self, texts: list[str]) -> "NoveltyDetector":
        """Fit detector on situation redacted texts and calibrate percentile threshold."""
        clean_texts = [t.strip() if t and t.strip() else "empty_text" for t in texts]

        # Invariant: With fewer than NOVELTY_K + 1 training rows, novel=True
        if len(clean_texts) < self.k + 1:
            self.training_vectors = None
            self.threshold = 1.0
            self.is_fitted = False
            return self

        try:
            x_mat = self.vectorizer.fit_transform(clean_texts).toarray()
        except ValueError:
            self.is_fitted = False
            return self

        # Normalize L2
        norms = np.linalg.norm(x_mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        x_mat = x_mat / norms
        self.training_vectors = x_mat

        # Compute pairwise cosine distances: 1 - (u dot v)
        sim_matrix = np.clip(np.dot(x_mat, x_mat.T), -1.0, 1.0)
        dist_matrix = 1.0 - sim_matrix

        # Leave-one-out mean distance to K nearest neighbors
        n_samples = len(clean_texts)
        loo_distances = np.zeros(n_samples, dtype=np.float64)

        for i in range(n_samples):
            # Exclude self distance (index i)
            row_dists = np.delete(dist_matrix[i], i)
            row_dists.sort()
            k_dists = row_dists[: self.k]
            loo_distances[i] = np.mean(k_dists)

        self.threshold = float(np.percentile(loo_distances, self.percentile))
        self.is_fitted = True
        return self

    def score(self, text: str) -> tuple[bool, float]:
        """Compute mean distance to K nearest training points and novelty verdict.

        Returns (is_novel, mean_distance).
        """
        # If fewer than K + 1 rows, always novel
        if (
            not self.is_fitted
            or self.training_vectors is None
            or len(self.training_vectors) < self.k + 1
        ):
            return (True, 1.0)

        query_text = text.strip() if text and text.strip() else "empty_text"
        try:
            q_vec = self.vectorizer.transform([query_text]).toarray()[0]
        except ValueError:
            return (True, 1.0)

        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return (True, 1.0)

        q_vec = q_vec / q_norm

        # Cosine distance to all training points
        sims = np.clip(np.dot(self.training_vectors, q_vec), -1.0, 1.0)
        dists = 1.0 - sims
        dists.sort()
        mean_k_dist = float(np.mean(dists[: self.k]))

        is_novel = bool(mean_k_dist >= self.threshold)
        return (is_novel, mean_k_dist)


def is_novel_point(
    point: list[float], reference_points: list[list[float]], threshold: float
) -> bool:
    """Legacy helper for numeric point distance."""
    if len(reference_points) < 5:
        return True
    p = np.array(point)
    refs = np.array(reference_points)
    dists = np.linalg.norm(refs - p, axis=1)
    return bool(np.mean(np.sort(dists)[:5]) > threshold)
