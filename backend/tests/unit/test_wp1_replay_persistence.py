"""WP1: replay must persist the complete proposal durably before dispatch."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from probation.core.clock import Clock
from probation.core.enums import GateDecision
from probation.core.types import Situation
from probation.db.connection import get_connection
from probation.engine.gate import GateResult


def _replay_db(tmp_path: Path, seed: sqlite3.Connection, sit: Situation) -> Path:
    seed.execute(
        "UPDATE raw_items SET payload_json=? WHERE id=?",
        (json.dumps({"message_id": "synthetic-message"}), sit.raw_item_id),
    )
    seed.execute(
        """INSERT INTO features(situation_id, deterministic_json, reader_json, reader_ok,
                 featurizer_version, features_hash, created_at) VALUES (?, ?, ?, 1, 'wp1', 'wp1-hash', ?)""",
        (
            sit.id,
            json.dumps({"sender_tier": "known"}),
            json.dumps({"intent": "other"}),
            sit.occurred_at,
        ),
    )
    seed.commit()
    path = tmp_path / "wp1-replay.sqlite"
    with get_connection(path) as target:
        seed.backup(target)
    return path


def _force_candidate(monkeypatch: pytest.MonkeyPatch) -> Any:
    import probation.engine.replay as replay

    monkeypatch.setattr(
        replay.Policy,
        "predict",
        lambda self, features: ("ARCHIVE", 0.99, {"ARCHIVE": 0.99, "LEAVE": 0.01}, []),
    )
    monkeypatch.setattr(
        replay, "decide_gate", lambda **kwargs: GateResult(GateDecision.EXECUTE_UNDO)
    )
    return replay


def test_replay_dispatch_observes_complete_committed_proposal(
    tmp_path: Path,
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _replay_db(tmp_path, memory_db, basic_situation)
    replay = _force_candidate(monkeypatch)
    clock = Clock.replay()
    calls: list[str] = []

    class InspectExecutor:
        def __init__(self, conn: Any, world: Any = None, clock: Clock | None = None) -> None:
            self.clock = clock

        def create_action(self, **kwargs: Any) -> None:
            with get_connection(path) as observer:
                row = observer.execute(
                    "SELECT * FROM proposals WHERE id=?", (kwargs["proposal_id"],)
                ).fetchone()
                assert row is not None, "dispatch preceded durable proposal insertion"
                params = json.loads(row["params_json"])
                assert params["message_id"] == "synthetic-message"
                assert kwargs["params"] == params
                assert json.loads(row["explanation_json"])["features_hash"] == "wp1-hash"
                assert (
                    observer.execute(
                        "SELECT kind FROM ledger WHERE seq=?", (row["ledger_seq"],)
                    ).fetchone()[0]
                    == "proposal"
                )
            calls.append(kwargs["proposal_id"])

        def process_queue(self, **kwargs: Any) -> list[Any]:
            return []

    monkeypatch.setattr(replay, "Executor", InspectExecutor)
    with get_connection(path) as conn:
        replay.run_replay(conn, clock=clock, until="2026-01-01T11:00:00Z")
    assert calls == [f"prop-{basic_situation.id}"]


def test_replay_failed_proposal_rolls_back_its_ledger_and_never_dispatches(
    tmp_path: Path,
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _replay_db(tmp_path, memory_db, basic_situation)
    replay = _force_candidate(monkeypatch)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        replay.Executor, "create_action", lambda *args, **kwargs: dispatched.append(kwargs)
    )
    with get_connection(path) as conn:
        conn.execute(
            "CREATE TRIGGER reject_proposal BEFORE INSERT ON proposals BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            replay.run_replay(conn, until="2026-01-01T11:00:00Z")
        assert conn.execute("SELECT count(*) FROM ledger WHERE kind='proposal'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM proposals").fetchone()[0] == 0
    assert dispatched == []
