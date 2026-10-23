"""Final WP4 integration gaps: provenance, bounded observations and model identity."""

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.db.ledger import append_ledger
from probation.engine.training import build_cohort

EARLY = "2026-01-01T10:00:00Z"
CUT = "2026-01-03T10:00:00Z"
LATE = "2026-01-05T10:00:00Z"


def test_file_origin_counts_exclude_not_yet_observed_raw(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    memory_db.execute(
        "UPDATE situations SET pack='files',family='file_destination',sender_key='origin'"
    )
    memory_db.execute("UPDATE raw_items SET known_at=?", (LATE,))
    stats = HistoryView(memory_db, CUT).file_statistics("origin")
    assert stats["n_prior_from_origin"] == 0
    memory_db.execute("UPDATE raw_items SET known_at=?", (EARLY,))
    assert HistoryView(memory_db, CUT).file_statistics("origin")["n_prior_from_origin"] == 1
    assert (
        HistoryView(memory_db, CUT).file_statistics("origin", basic_situation.id)[
            "n_prior_from_origin"
        ]
        == 0
    )


def test_system_actor_is_not_user_training_or_reply_history(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    append_ledger(
        memory_db,
        "outcome",
        basic_situation.id,
        {
            "situation_id": basic_situation.id,
            "known_at": EARLY,
            "source": "footprint",
            "strength": "STRONG",
            "observed_action": "REPLY",
            "details": {"actor": "executor"},
        },
        EARLY,
    )
    projection = HistoryView(memory_db, CUT).get_decision_projection()
    assert not projection[basic_situation.id]["eligible"]
    stats = HistoryView(memory_db, CUT).sender_statistics(basic_situation.sender_key or "")
    assert stats["replies"] == 0


def test_required_reader_missing_fields_is_excluded_from_training(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    append_ledger(
        memory_db,
        "outcome",
        basic_situation.id,
        {
            "situation_id": basic_situation.id,
            "known_at": EARLY,
            "source": "footprint",
            "strength": "STRONG",
            "observed_action": "REPLY",
        },
        EARLY,
    )
    memory_db.execute(
        "INSERT INTO features(situation_id,deterministic_json,reader_ok,featurizer_version,features_hash,created_at) VALUES (?, ?,1,'test','h',?)",
        (
            basic_situation.id,
            json.dumps({"__reader_required": True, "__deterministic_ok": True}),
            EARLY,
        ),
    )
    cohort = build_cohort(HistoryView(memory_db, CUT), "email_action", "test")
    assert not cohort.rows
    assert cohort.excluded["missing_required_reader"] == 1


def test_novelty_context_is_bounded_redacted_and_file_specific(basic_situation: Situation) -> None:
    from probation.llm.feature_pipeline import novelty_context

    mail = basic_situation.model_copy(update={"redacted_text": "owner@example.test " + "x" * 10000})
    text = novelty_context(mail, {})
    assert "owner@example.test" not in text and len(text) <= 4000
    file = mail.model_copy(update={"pack": "files", "family": "file_destination"})
    file_text = novelty_context(
        file, {"__name_tokens": "course lab", "origin_group": "github", "ext_group": "pdf"}
    )
    assert all(word in file_text for word in ("course", "lab", "github", "pdf"))
    assert "xxxx" not in file_text


def test_embedding_runtime_version_changes_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import sys
    from types import SimpleNamespace

    from probation import local_embeddings

    model = tmp_path / "model"
    model.mkdir()
    (model / "model.onnx").write_bytes(b"synthetic")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "model": local_embeddings.MODEL,
                "files": {"model.onnx": hashlib.sha256(b"synthetic").hexdigest()},
            }
        )
    )

    class Runtime:
        def __init__(self, **kwargs: object) -> None:
            pass

        def embed(self, texts: list[str]) -> list[np.ndarray]:
            return [np.ones(384) for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=Runtime))
    monkeypatch.setattr(local_embeddings, "version", lambda name: "1")
    first = local_embeddings.LocalMiniLM(model, manifest).identity
    monkeypatch.setattr(
        local_embeddings, "version", lambda name: "2" if name == "onnxruntime" else "1"
    )
    second = local_embeddings.LocalMiniLM(model, manifest).identity
    assert first != second


def test_invalid_fitted_encoder_input_fails_closed_at_shared_gate(
    basic_situation: Situation,
) -> None:
    from probation.core.types import Features
    from probation.engine.novelty import NoveltyDetector
    from probation.engine.policy import Policy
    from probation.engine.prediction import PredictionSnapshot, evaluate_prediction
    from probation.packs.registry import registry

    policy = Policy("file_destination").fit(
        [{"x": i % 2} for i in range(200)],
        ["MOVE_TO_FOLDER:Course/A" if i % 2 else "MOVE_TO_FOLDER:Course/B" for i in range(200)],
        [EARLY] * 200,
        CUT,
    )
    assert policy.is_fitted
    situation = basic_situation.model_copy(update={"pack": "files", "family": "file_destination"})
    features = Features(
        situation_id=situation.id,
        deterministic={
            "x": "invalid-numeric",
            "__reader_required": False,
            "__deterministic_ok": True,
            "__budget_ok": True,
        },
        reader_ok=True,
        featurizer_version="test",
        features_hash="h",
    )
    result = evaluate_prediction(
        situation,
        features,
        registry.get_descriptor("files"),
        PredictionSnapshot(policy, NoveltyDetector(), "seed", 0),
        licence_level=3,
    )
    assert result.gate.value == "ASK"
    assert result.action == "ABSTAIN" and "prediction_failed" in result.reasons


def test_offline_setup_check_missing_artifacts_is_explicit(tmp_path: Path) -> None:
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[3] / "scripts/verify_embeddings.py"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(script),
            "--model-dir",
            str(tmp_path / "absent"),
            "--manifest",
            str(tmp_path / "absent.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "available": False,
        "reason": "embedding_artifacts_missing",
    }
    assert result.stderr == ""
