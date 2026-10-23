"""Deterministic nonzero test vectors; not production MiniLM compatibility evidence."""

import hashlib

import numpy as np


class RecordedEmbeddings:
    identity = "synthetic-sha256-vectors-v1"

    def embed(self, texts):
        return np.asarray(
            [
                np.frombuffer(hashlib.sha256(text.encode()).digest(), dtype=np.uint8).astype(float)
                + 1
                for text in texts
            ]
        )
