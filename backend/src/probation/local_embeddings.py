"""Explicitly provisioned, verified local embedding I/O; no automatic download."""

import hashlib
import json
import os
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
        # Configure process-local caches before the runtime import. No user/global cache
        # fallback, even when a caller did not use the development smoke launcher.
        cache = root.parents[1] / ".cache"
        locations = {
            "HF_HOME": "huggingface",
            "HF_HUB_CACHE": "huggingface/hub",
            "HUGGINGFACE_HUB_CACHE": "huggingface/hub",
            "HF_ASSETS_CACHE": "huggingface/assets",
            "HF_XET_CACHE": "huggingface/xet",
            "XDG_CACHE_HOME": ".",
            "SENTENCE_TRANSFORMERS_HOME": "sentence-transformers",
            "TRANSFORMERS_CACHE": "transformers",
            "FASTEMBED_CACHE_PATH": "fastembed",
            "TEMP": "tmp",
            "TMP": "tmp",
            "TMPDIR": "tmp",
        }
        for key, relative in locations.items():
            path = cache / relative
            path.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(path)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        # Imported only after explicit path and complete hash verification. Fastembed's
        # installed implementation supports both flags; no default cache discovery.
        from fastembed import TextEmbedding

        self.identity = hashlib.sha256(
            json.dumps(
                {
                    "manifest": manifest,
                    "runtime": {
                        name: version(name) for name in ("fastembed", "onnxruntime", "numpy")
                    },
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
                cache_dir=str(cache / "fastembed"),
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
