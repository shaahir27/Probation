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
    from probation.llm.feature_pipeline import semantic_feature_version

    seed.execute(
        """INSERT INTO features(situation_id, deterministic_json, reader_json, reader_ok,
                 featurizer_version, features_hash, created_at) VALUES (?, ?, ?, 1, ?, 'wp1-hash', ?)""",
        (
            sit.id,
            json.dumps({"sender_tier": "known"}),
            json.dumps(
                {
                    "intent": "other",
                    "asks_me_to_do_something": False,
                    "has_deadline": False,
                    "deadline_text": None,
                    "money_involved": False,
                    "urgency": 1,
                    "formality": "neutral",
                    "asks_for_personal_info": False,
                    "looks_automated": False,
                }
            ),
            semantic_feature_version(),
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
        "probation.engine.prediction.decide_gate",
        lambda **kwargs: GateResult(GateDecision.EXECUTE_UNDO),
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


def test_same_instant_events_are_ordered_by_tie_id_not_insertion_order() -> None:
    """The replay timeline must have a total order.

    Authority: docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.3.2. Without a tie-break the
    order of two events at one instant is whatever the producing SQL returned, and SQLite
    does not guarantee that for equal keys, so a planner or index change could reorder a
    replay and change its ledger head.
    """
    from probation.engine.replay import (
        PRIORITY_SITUATION,
        ReplayEvent,
    )

    def event(tie_id: str) -> ReplayEvent:
        return ReplayEvent(
            timestamp="2026-01-01T10:00:00Z",
            priority=PRIORITY_SITUATION,
            kind="SITUATION",
            tie_id=tie_id,
        )

    forward = [event("sit-b"), event("sit-a"), event("sit-c")]
    assert [ev.tie_id for ev in sorted(forward, key=lambda e: e.sort_key())] == [
        "sit-a",
        "sit-b",
        "sit-c",
    ]
    # Fed in the opposite order, the result must be identical: the order comes from the key,
    # not from list position.
    backward = list(reversed(forward))
    assert [ev.tie_id for ev in sorted(backward, key=lambda e: e.sort_key())] == [
        "sit-a",
        "sit-b",
        "sit-c",
    ]

    # Priority still dominates: an outcome known at the same instant precedes the situation.
    outcome = ReplayEvent(
        timestamp="2026-01-01T10:00:00Z",
        priority=0,
        kind="OUTCOME_KNOWN",
        tie_id="zzz",
    )
    ordered = sorted([event("aaa"), outcome], key=lambda e: e.sort_key())
    assert [ev.kind for ev in ordered] == ["OUTCOME_KNOWN", "SITUATION"]


def test_situation_whose_outcome_is_already_known_is_not_proposed(
    tmp_path: Path,
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-instant outcome makes I-7 unsatisfiable, so the replay must fail closed.

    Authority: docs/CONTRACT.md I-7 (`proposed_at < known_at`, proposal ledger sequence
    before outcome ledger sequence). The outcome event sorts first, so proposing afterwards
    would break both halves of the invariant; the evidence is unusable instead.
    """
    from probation.db.ledger import append_ledger

    path = _replay_db(tmp_path, memory_db, basic_situation)
    replay = _force_candidate(monkeypatch)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        replay.Executor, "create_action", lambda *args, **kwargs: dispatched.append(kwargs)
    )

    known_at = basic_situation.occurred_at
    with get_connection(path) as conn:
        seq = append_ledger(
            conn,
            kind="outcome",
            ref_id=basic_situation.id,
            payload={
                "situation_id": basic_situation.id,
                "observed_action": "ARCHIVE",
                "strength": "STRONG",
                "source": "synthetic",
                "known_at": known_at,
            },
            created_at=known_at,
        )
        conn.execute(
            """INSERT INTO outcomes(situation_id, observed_action, strength, source,
               observed_at, known_at, details_json, ledger_seq)
               VALUES (?, 'ARCHIVE', 'STRONG', 'synthetic', ?, ?, '{}', ?)""",
            (basic_situation.id, known_at, known_at, seq),
        )
        conn.commit()

        replay.run_replay(conn, clock=Clock.replay(), until="2026-01-01T11:00:00Z")

        assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0, (
            "a proposal was created for a situation whose outcome was already known"
        )
        assert conn.execute("SELECT COUNT(*) FROM ledger WHERE kind='proposal'").fetchone()[0] == 0
    assert dispatched == []


def _seed_mail_pair(
    seed: sqlite3.Connection, first: str, second: str, sender: str
) -> tuple[str, str]:
    """Two incoming mail situations from one sender, `first` strictly before `second`."""
    ids = []
    for index, occurred_at in enumerate((first, second), start=1):
        sit_id = f"c11-sit-{index}"
        raw_id = f"c11-raw-{index}"
        seed.execute(
            "INSERT INTO sources VALUES ('wp1-source', 'mail', 'synthetic', 'synthetic-c11', ?)",
            (occurred_at,),
        ) if index == 1 else None
        seed.execute(
            """INSERT INTO raw_items(id, source_id, pack, item_kind, source_ref, occurred_at,
               known_at, payload_json, content_hash)
               VALUES (?, 'wp1-source', 'mail', 'mail_in', ?, ?, ?, ?, 'synthetic-c11')""",
            (
                raw_id,
                raw_id,
                occurred_at,
                occurred_at,
                json.dumps({"message_id": f"c11-msg-{index}", "in_reply_to": ""}),
            ),
        )
        seed.execute(
            """INSERT INTO situations(id, raw_item_id, pack, family, occurred_at, sender_key,
               content_hash, created_at)
               VALUES (?, ?, 'mail', 'email_action', ?, ?, 'synthetic-c11', ?)""",
            (sit_id, raw_id, occurred_at, sender, occurred_at),
        )
        ids.append(sit_id)
    seed.commit()
    return ids[0], ids[1]


def test_features_are_derived_at_the_situations_own_cutoff_not_in_a_pre_loop_batch(
    tmp_path: Path,
    memory_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History clues must see the outcomes that were already durable when the event fired.

    Authority: docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.3.3 ("derive feature history
    at each situation's historical cutoff, not using a future-influenced batch snapshot").
    Featurizing every situation before the timeline runs reads an empty `outcomes` table,
    so reply-history clues collapse to their degenerate defaults for the whole run.
    """
    from probation.core.types import Outcome
    from probation.db.connection import get_connection

    first_at = "2026-01-01T10:00:00Z"
    second_at = "2026-01-03T10:00:00Z"
    known_at = "2026-01-02T10:00:00Z"
    _seed_mail_pair(memory_db, first_at, second_at, "prof@national.ac.in")

    path = tmp_path / "c11.sqlite"
    with get_connection(path) as target:
        memory_db.backup(target)

    replay = _force_candidate(monkeypatch)

    def fake_resolve(sit: Situation, world: Any, now: Any, **kwargs: Any) -> Any:
        if sit.id == "c11-sit-1":
            return Outcome(
                situation_id=sit.id,
                observed_action="REPLY",
                observed_at=known_at,
                known_at=known_at,
                details={},
            )
        return None

    monkeypatch.setattr(replay, "resolve_mail_outcome", fake_resolve)

    class StubWorld:
        def get_messages(self) -> list[Any]:
            return []

    with get_connection(path) as conn:
        replay.run_replay(
            conn,
            clock=Clock.replay(),
            world=StubWorld(),
            until="2026-01-04T00:00:00Z",
        )
        row = conn.execute(
            "SELECT deterministic_json FROM features WHERE situation_id='c11-sit-2'"
        ).fetchone()
        assert row is not None, "the later situation was never featurized"
        clues = json.loads(row[0])

    assert clues["n_prior_replied"] == 1, (
        "reply history was derived before the earlier outcome was durable: "
        f"n_prior_replied={clues['n_prior_replied']}"
    )
    assert clues["n_prior_in"] == 1
    assert clues["reply_rate_sender"] == round(2.0 / 3.0, 4)
    assert clues["median_reply_hours_sender"] == 24.0
    assert clues["sender_tier"] == "known"
