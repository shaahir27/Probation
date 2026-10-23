"""Verify preprovisioned MiniLM artifacts offline; never downloads or reads .env."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    model_dir, manifest = args.model_dir.resolve(), args.manifest.resolve()
    if not model_dir.is_dir() or not manifest.is_file():
        print(json.dumps({"available": False, "reason": "embedding_artifacts_missing"}))
        return 1
    source = Path(__file__).resolve().parents[1] / "backend/src"
    sys.path.insert(0, str(source))
    sys.dont_write_bytecode = True
    # Importing application settings must not probe the caller's project .env.
    os.chdir(model_dir)
    network_attempts: list[str] = []

    def guard(event: str, values: tuple[Any, ...]) -> None:
        if event == "socket.connect":
            network_attempts.append(event)
            raise RuntimeError("offline_verification_denied_network")
        if (
            event == "open"
            and isinstance(values[0], (str, bytes))
            and Path(os.fsdecode(values[0])).name == ".env"
        ):
            raise RuntimeError("offline_verification_denied_secret_read")

    sys.addaudithook(guard)
    try:
        import numpy as np
        from probation.engine.novelty import NoveltyDetector
        from probation.local_embeddings import LocalMiniLM

        model = LocalMiniLM(model_dir, manifest)
        texts = [
            "Synthetic robotics workshop newsletter.",
            "Synthetic library opening hours.",
        ]
        vectors = model.embed(texts)
        if vectors.shape != (2, 384) or not np.isfinite(vectors).all():
            raise ValueError("invalid_embedding_output")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
            raise ValueError("embedding_not_normalized")
        if not np.allclose(vectors, model.embed(texts), atol=1e-6):
            raise ValueError("embedding_not_repeatable")
        novelty = NoveltyDetector(k=2, embedder=model).fit([texts[0]] * 3)
        novel, distance = novelty.score(texts[0])
        if novel or network_attempts:
            raise ValueError("offline_novelty_smoke_failed")
        print(
            json.dumps(
                {
                    "available": True,
                    "provider_identity": model.identity,
                    "shape": list(vectors.shape),
                    "normalized": True,
                    "repeatable": True,
                    "duplicate_novel": novel,
                    "duplicate_distance": distance,
                    "network_attempts": len(network_attempts),
                }
            )
        )
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        # No library exception body/path/response is exposed.
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": type(exc).__name__,
                    "network_attempts": len(network_attempts),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
