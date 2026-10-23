"""Explicitly provisioned, verified local embedding I/O; no automatic download."""

import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from probation.engine.novelty import NoveltyUnavailable

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class LocalMiniLM:
    """Manifest lists every artifact as relative-path -> SHA256; caller provisions it."""

    def __init__(self, model_dir: Path, manifest_path: Path) -> None:
        try:
            self._load(model_dir, manifest_path)
        except NoveltyUnavailable:
            raise
        except Exception as exc:
            raise NoveltyUnavailable("embedding_artifacts_unavailable") from exc

    def _load(self, model_dir: Path, manifest_path: Path) -> None:
        root = model_dir.resolve(strict=True)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("model") != MODEL or not manifest.get("files"):
            raise NoveltyUnavailable("embedding_manifest_invalid")
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        if actual != set(manifest["files"]):
            raise NoveltyUnavailable("embedding_manifest_incomplete")
        for relative, expected in manifest["files"].items():
            target = root / relative
            if target.is_symlink() or not target.resolve().is_relative_to(root):
                raise NoveltyUnavailable("embedding_artifact_escape")
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise NoveltyUnavailable("embedding_artifact_hash_mismatch")
        # Imported only after explicit path and complete hash verification. Fastembed's
        # installed implementation supports both flags; no default cache discovery.
        from fastembed import TextEmbedding

        self.identity = hashlib.sha256(
            json.dumps(
                {
                    "manifest": manifest,
                    "runtime": version("fastembed"),
                    "preprocessing": "minilm-local-v1",
                    "normalization": "l2",
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        try:
            self._model = TextEmbedding(
                model_name=MODEL,
                specific_model_path=str(root),
                local_files_only=True,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            raise NoveltyUnavailable("embedding_runtime_unavailable") from exc

    def embed(self, texts: list[str]) -> NDArray[np.float64]:
        try:
            vectors = np.asarray(list(self._model.embed(texts)), dtype=np.float64)
            if vectors.shape != (len(texts), 384) or not np.isfinite(vectors).all():
                raise NoveltyUnavailable("embedding_shape_or_values_invalid")
            return vectors
        except Exception as exc:
            raise NoveltyUnavailable("embedding_inference_failed") from exc
