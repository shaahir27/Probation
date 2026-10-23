"""Offline loader validates artifacts before runtime initialization."""

import hashlib
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from probation.engine.novelty import NoveltyUnavailable
from probation.local_embeddings import MODEL, LocalMiniLM


def test_missing_artifacts_raise_typed_unavailable_without_runtime(tmp_path):
    with pytest.raises(NoveltyUnavailable, match="artifacts_unavailable"):
        LocalMiniLM(tmp_path / "absent", tmp_path / "absent.json")


def test_loader_enforces_offline_runtime_and_artifact_hashes(tmp_path, monkeypatch):
    root = tmp_path / "model"
    root.mkdir()
    artifact = root / "model.onnx"
    artifact.write_bytes(b"synthetic model, never loaded as ONNX")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "model": MODEL,
                "files": {"model.onnx": hashlib.sha256(artifact.read_bytes()).hexdigest()},
            }
        )
    )
    calls = []

    class FakeRuntime:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def embed(self, texts):
            return [np.ones(384) for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=FakeRuntime))
    loader = LocalMiniLM(root, manifest)
    assert loader.embed(["synthetic text"]).shape == (1, 384)
    assert calls[0]["local_files_only"] is True
    assert calls[0]["specific_model_path"] == str(root.resolve())
    artifact.write_bytes(b"changed")
    with pytest.raises(NoveltyUnavailable, match="hash_mismatch"):
        LocalMiniLM(root, manifest)
    assert len(calls) == 1  # no runtime or transport route on invalid artifacts
