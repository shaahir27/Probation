"""Durable replay recovery: fencing, crash boundaries, resume, and one shared projection.

Authority: docs/CONTRACT.md I-7, I-8, I-9, section 3 (Examiner-owned receipts) and
docs/wp9/D6_API_CONTRACT.md. Every scenario here is offline over synthetic rows.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.authority import OwnerContext, optional_owner
from probation.api.routes import replay as replay_route
from probation.config import settings
from probation.core.clock import Clock, format_timestamp, parse_timestamp, use_clock
from probation.core.replay_controls import ReplayCommandIntent, ReplayScope, server_replay_scope
from probation.db.access import Role, RoleAccess
from probation.db.connection import get_connection, init_db
from probation.db.ledger import verify_ledger
from probation.db.replay_commands import ReplayCommandStore
from probation.engine.replay import prepare_replay_session, run_replay
from probation.engine.replay_kernel import ReplayPosition, project_replay_state
from probation.workers.replay_controller import ReplayController

WORKSPACE = "demo"
OPERATIONAL_START = datetime(2026, 10, 24, tzinfo=UTC)
SIMULATED_START = datetime(2026, 1, 1, tzinfo=UTC)


def _operational(seconds: float) -> str:
    return format_timestamp(OPERATIONAL_START + timedelta(seconds=seconds))


def _controller(conn: sqlite3.Connection, controller_id: str) -> ReplayController:
    return ReplayController(
        RoleAccess(conn, Role.EXAMINER),
        workspace_id=WORKSPACE,
        run_id="active",
        controller_id=controller_id,
    )


def _intent(request_id: str, command: str, at: float, speed: int | None = None) -> Any:
    return ReplayCommandIntent(
        request_id=request_id,
        owner_id="owner",
        type=command,  # type: ignore[arg-type]
        scope=ReplayScope(workspace_id=WORKSPACE, run_id="active"),
        speed=speed,
        created_at=_operational(at),
    )


def _submit(conn: sqlite3.Connection, intent: Any) -> None:
    ReplayCommandStore(RoleAccess(conn, Role.API)).submit(intent)


def _started(memory_db: sqlite3.Connection) -> ReplayController:
    """A controller with a running, durably claimed replay from the simulated start."""
    _submit(memory_db, _intent("start", "replay_start", 0))
    controller = _controller(memory_db, "examiner-first")
    assert (
        controller.process_pending(
            operational_at=_operational(1), initial_simulated_at=format_timestamp(SIMULATED_START)
        )
        == 1
    )
    return controller


# ------------------------------------------------------------------ projections --


def test_api_and_controller_call_the_same_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read surface and the writer can no longer disagree: there is one projection."""
    path = tmp_path / "replay-projection.db"
    init_db(path)
    monkeypatch.setattr(settings, "db_path", path)
    app.dependency_overrides[optional_owner] = lambda: OwnerContext("owner", ())
    monkeypatch.setattr(app.state, "clock", Clock.replay(SIMULATED_START))
    client = TestClient(app)

    class FrozenOperational:
        """The API reads operational time; pinning it makes the two paths comparable."""

        value = _operational(0)

        @staticmethod
        def now_iso() -> str:
            return FrozenOperational.value

    class FrozenClockFactory:
        @staticmethod
        def live() -> type[FrozenOperational]:
            return FrozenOperational

    monkeypatch.setattr(replay_route, "Clock", FrozenClockFactory)
    try:
        assert client.post("/api/replay/start", json={"request_id": "shared"}).status_code == 202
        scope = server_replay_scope("owner", path)
        with get_connection(path) as conn:
            controller = ReplayController(
                RoleAccess(conn, Role.EXAMINER),
                workspace_id=scope.workspace_id,
                run_id=scope.run_id,
                controller_id="examiner-one",
            )
            assert (
                controller.process_pending(
                    operational_at=_operational(1),
                    initial_simulated_at=format_timestamp(SIMULATED_START),
                )
                == 1
            )
            controller.advance(elapsed_seconds=5, operational_at=_operational(6))
            FrozenOperational.value = _operational(10)
            api_state = client.get("/api/replay/state").json()
            controller_state = controller.state(operational_at=_operational(10))
    finally:
        app.dependency_overrides.pop(optional_owner, None)

    assert api_state["simulated_date"] == controller_state["simulated_at"]
    assert api_state["running"] is controller_state["running"] is True
    assert api_state["available"] == controller_state["available"]
    assert api_state["resumable"] == controller_state["resumable"]
    assert api_state["last_request_id"] == controller_state["last_request_id"] == "shared"
    assert api_state["speed"] == controller_state["speed"] == 1


def test_state_reports_the_application_clock_before_any_replay_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed clock semantics still hold: no run means the injected clock is shown."""
    path = tmp_path / "replay-clock.db"
    init_db(path)
    monkeypatch.setattr(settings, "db_path", path)
    clock = Clock.replay(datetime(2026, 6, 1, 10, 0, 0, 123456, tzinfo=UTC))
    monkeypatch.setattr(app.state, "clock", clock)
    app.dependency_overrides[optional_owner] = lambda: OwnerContext("owner", ())
    try:
        state = TestClient(app).get("/api/replay/state")
    finally:
        app.dependency_overrides.pop(optional_owner, None)
    assert state.status_code == 200
    assert state.json()["simulated_date"] == clock.now_iso()
    assert state.json()["running"] is False
    assert state.json()["available"] is True
    assert "last_request_id" not in state.json()


def test_projection_never_counts_simulated_time_without_a_live_lease() -> None:
    checkpoint = {
        "running": True,
        "speed": 100,
        "simulated_at": "2026-01-01T00:00:00Z",
        "operational_at": "2026-10-24T00:00:00Z",
        "receipt_state": "claimed",
        "valid_until": "2026-10-24T00:00:30Z",
        "controller_epoch": 3,
        "receipt_fence": 3,
    }
    expired = project_replay_state(
        checkpoint,
        operational_at="2026-10-24T00:05:00Z",
        default_simulated_at="2026-10-24T00:05:00Z",
        mode="replay",
    )
    assert expired.running is False
    assert expired.simulated_at == "2026-01-01T00:00:00Z"
    assert expired.resumable is True
    assert expired.reason == "lease_expired"
    live = project_replay_state(
        checkpoint,
        operational_at="2026-10-24T00:00:20Z",
        default_simulated_at="2026-10-24T00:00:20Z",
        mode="replay",
    )
    assert live.running is True
    assert live.simulated_at == "2026-01-01T00:33:20Z"
    # Past the lease the projection stops counting, even though the claim row still says claimed.
    boundary = project_replay_state(
        checkpoint,
        operational_at="2026-10-24T00:00:40Z",
        default_simulated_at="2026-10-24T00:00:40Z",
        mode="replay",
    )
    assert boundary.running is False and boundary.resumable is True


def test_stale_controller_epoch_is_fenced_out_of_the_read_surface() -> None:
    """A checkpoint written under a dead epoch may not claim that the run is alive."""
    projection = project_replay_state(
        {
            "running": True,
            "speed": 1,
            "simulated_at": "2026-01-01T00:00:00Z",
            "operational_at": "2026-10-24T00:00:00Z",
            "receipt_state": "claimed",
            "valid_until": "2026-10-24T00:00:30Z",
            "controller_epoch": 2,
            "receipt_fence": 5,
        },
        operational_at="2026-10-24T00:00:10Z",
        default_simulated_at="2026-10-24T00:00:10Z",
        mode="replay",
    )
    assert projection.running is False
    assert projection.available is False
    assert projection.reason == "stale_controller_epoch"


# ---------------------------------------------------------------------- fencing ---


def test_two_competing_controllers_cannot_both_advance(memory_db: sqlite3.Connection) -> None:
    controller = _started(memory_db)
    rival = _controller(memory_db, "examiner-rival")
    controller.advance(elapsed_seconds=1, operational_at=_operational(2))
    before = controller.state(operational_at=_operational(3))["simulated_at"]

    # A live lease held by somebody else fences the rival out: it advances nothing and writes
    # nothing, and it reports the run as unavailable rather than pretending to own it.
    refused = rival.advance(elapsed_seconds=60, operational_at=_operational(3))
    assert refused["running"] is False
    assert refused["available"] is False
    assert refused["reason"] == "claim_held_elsewhere"
    assert rival.engine_position() == controller.engine_position()
    assert controller.state(operational_at=_operational(3))["simulated_at"] == before

    # When the lease lapses exactly one controller takes over, at a higher fence.
    takeover = rival.advance(elapsed_seconds=1, operational_at=_operational(40))
    assert takeover["running"] is True
    store = ReplayCommandStore(RoleAccess(memory_db, Role.API))
    checkpoint = store.checkpoint(workspace_id=WORKSPACE, run_id="active")
    assert checkpoint is not None
    assert checkpoint["claim_owner"] == "examiner-rival"
    assert int(checkpoint["controller_epoch"]) == 2

    # The previous owner is now fenced: its write is refused and changes nothing durable.
    fenced = controller.advance(elapsed_seconds=5, operational_at=_operational(41))
    assert fenced["available"] is False
    after = store.checkpoint(workspace_id=WORKSPACE, run_id="active")
    assert after is not None and after["controller_epoch"] == checkpoint["controller_epoch"]
    assert after["simulated_at"] == checkpoint["simulated_at"]


def test_duplicate_commands_and_repeated_ticks_are_idempotent(
    memory_db: sqlite3.Connection,
) -> None:
    _submit(memory_db, _intent("start", "replay_start", 0))
    _submit(memory_db, _intent("start", "replay_start", 0))
    controller = _controller(memory_db, "examiner-once")
    initial = format_timestamp(SIMULATED_START)
    assert (
        controller.process_pending(operational_at=_operational(1), initial_simulated_at=initial)
        == 1
    )
    # The intent is consumed once: a second pass finds nothing queued.
    assert (
        controller.process_pending(operational_at=_operational(2), initial_simulated_at=initial)
        == 0
    )
    first = controller.advance(elapsed_seconds=3, operational_at=_operational(3))["simulated_at"]
    again = controller.advance(elapsed_seconds=0, operational_at=_operational(4))["simulated_at"]
    assert first == again == "2026-01-01T00:00:03Z"
    states = [
        str(row["state"])
        for row in memory_db.execute("SELECT state FROM command_receipts WHERE consumer='examiner'")
    ]
    assert states == ["claimed"]
    assert memory_db.execute("SELECT COUNT(*) FROM command_requests").fetchone()[0] == 1, (
        "a replayed intent must not insert a second durable command"
    )


# ------------------------------------------------------------------------ resume --


def test_replay_resumes_after_a_clean_stop(memory_db: sqlite3.Connection) -> None:
    """A stopped controller leaves a truthful, resumable state, not a dead end."""
    controller = _started(memory_db)
    controller.advance(elapsed_seconds=7, operational_at=_operational(8))
    stopped_at = controller.state()["simulated_at"]
    controller.pause_and_finish(_operational(9))

    state = controller.state(operational_at=_operational(10))
    assert state["running"] is False
    assert state["available"] is True, "a clean stop must not make the surface unreportable"
    assert state["resumable"] is True
    assert state["reason"] == "controller_stopped"
    assert state["simulated_at"] == stopped_at

    resumed = _controller(memory_db, "examiner-resume")
    _submit(memory_db, _intent("resume", "replay_start", 11))
    assert (
        resumed.process_pending(
            operational_at=_operational(12), initial_simulated_at="2020-01-01T00:00:00Z"
        )
        == 1
    )
    after = resumed.state(operational_at=_operational(12))
    assert after["running"] is True
    assert after["simulated_at"] == stopped_at, "resume must continue, never restart the history"
    assert parse_timestamp(str(after["simulated_at"])) >= SIMULATED_START
    resumed.advance(elapsed_seconds=2, operational_at=_operational(14))
    assert resumed.state()["simulated_at"] == "2026-01-01T00:00:09Z"


def test_old_start_command_does_not_resurrect_a_run(memory_db: sqlite3.Connection) -> None:
    """A consumed anchor stays consumed: an expired lease must not restart a paused run."""
    controller = _started(memory_db)
    _submit(memory_db, _intent("halt", "replay_pause", 2))
    assert (
        controller.process_pending(
            operational_at=_operational(3), initial_simulated_at=format_timestamp(SIMULATED_START)
        )
        == 1
    )
    store = ReplayCommandStore(RoleAccess(memory_db, Role.EXAMINER))
    # Long after every lease has lapsed, nothing is queued any more.
    assert store.pending(_operational(600)) == []
    assert controller.state(operational_at=_operational(600))["running"] is False


def test_pause_command_survives_a_controller_restart(memory_db: sqlite3.Connection) -> None:
    _started(memory_db)
    _submit(memory_db, _intent("halt", "replay_pause", 2))
    second = _controller(memory_db, "examiner-b")
    # While the first controller's lease is live the rival is fenced out; it cannot claim a pause
    # it has no authority to perform.
    assert (
        second.process_pending(
            operational_at=_operational(3), initial_simulated_at=format_timestamp(SIMULATED_START)
        )
        == 0
    )
    assert second.state(operational_at=_operational(3))["running"] is True
    # Once the dead lease lapses, the restart takes the run over and applies the durable intent.
    assert (
        second.process_pending(
            operational_at=_operational(40), initial_simulated_at=format_timestamp(SIMULATED_START)
        )
        == 1
    )
    assert second.state(operational_at=_operational(41))["running"] is False
    assert second.state(operational_at=_operational(41))["reason"] == "owner_paused"
    assert second.advance(elapsed_seconds=10, operational_at=_operational(42))["running"] is False


def test_must_resume_is_reported_when_a_paused_decision_has_no_later_response_time(
    memory_db: sqlite3.Connection,
) -> None:
    """Truthful state: an unanswered decision can only be closed by advancing replay."""
    _seed_open_decision(memory_db)
    controller = _started(memory_db)
    controller.pause_and_finish(_operational(2))
    paused = controller.state(operational_at=_operational(3))
    assert paused["running"] is False and paused["must_resume"] is True
    memory_db.execute(
        """INSERT INTO outcomes(situation_id,observed_action,strength,source,observed_at,known_at,
        details_json,ledger_seq) VALUES ('must-sit','LEAVE','WEAK','window_close',
        '2026-01-02T00:00:00Z','2026-01-02T00:00:00Z','{}',2)"""
    )
    memory_db.commit()
    assert controller.state(operational_at=_operational(4))["must_resume"] is False


def _seed_open_decision(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO sources(id,pack,kind,ref,imported_at)
        VALUES ('must-src','mail','synthetic','r','2026-01-01T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,occurred_at,known_at,
        payload_json,content_hash) VALUES ('must-raw','must-src','mail','mail_in','must-raw',
        '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','{}','h')"""
    )
    conn.execute(
        """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,content_hash,created_at)
        VALUES ('must-sit','must-raw','mail','email_action','2026-01-01T00:00:00Z','h',
        '2026-01-01T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO proposals(id,situation_id,family,class_key,action,probs_json,p_max,novelty,
        novel,licence_level,cap,gate,reasons_json,params_json,explanation_json,web_json,
        policy_version,features_hash,audit_holdout,proposed_at,ledger_seq)
        VALUES ('must-prop','must-sit','email_action','mail|other|known','LEAVE','{}',1,1,1,0,0,
        'ASK','[]','{}','{}','{}','v1','h',0,'2026-01-01T00:00:00Z',1)"""
    )
    conn.commit()


# ------------------------------------------------------------ shared engine path --


def _reader(situation: Any) -> tuple[dict[str, Any] | None, bool]:
    return (
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
        },
        True,
    )


def _replay_connection(tmp_path: Path, name: str, count: int) -> sqlite3.Connection:
    path = tmp_path / name
    init_db(path)
    conn = get_connection(path)
    conn.execute(
        """INSERT INTO sources(id,pack,kind,ref,imported_at)
        VALUES ('src','mail','synthetic','synthetic-recovery','2026-01-01T00:00:00Z')"""
    )
    for index in range(count):
        occurred = format_timestamp(SIMULATED_START + timedelta(days=index, hours=10))
        conn.execute(
            """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,occurred_at,known_at,
            payload_json,content_hash) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                f"rec-raw-{index}",
                "src",
                "mail",
                "mail_in",
                f"rec-raw-{index}",
                occurred,
                occurred,
                '{"message_id": "synthetic-recovery", "from": "sender@test.invalid",'
                ' "to": "owner@test.invalid", "subject": "Synthetic", "body": "Synthetic body"}',
                "synthetic-hash",
            ),
        )
        conn.execute(
            """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,sender_key,
            content_hash,redacted_text,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                f"rec-sit-{index}",
                f"rec-raw-{index}",
                "mail",
                "email_action",
                occurred,
                "sender@test.invalid",
                "synthetic-hash",
                "<PERSON_1> synthetic body",
                occurred,
            ),
        )
    conn.commit()
    return conn


def _business_rows(conn: sqlite3.Connection) -> dict[str, Any]:
    """Everything a replay is allowed to change, read deterministically."""
    queries = {
        "proposals": "SELECT id,situation_id,class_key,action,gate,proposed_at,ledger_seq,"
        "policy_version,features_hash FROM proposals ORDER BY id",
        "outcomes": "SELECT situation_id,observed_action,strength,known_at,ledger_seq "
        "FROM outcomes ORDER BY situation_id",
        "ledger": "SELECT kind,ref_id,payload_json FROM ledger ORDER BY seq",
        "features": "SELECT situation_id,features_hash FROM features ORDER BY situation_id",
        "licence_cache": "SELECT class_key,action,level,valid_until FROM licence_cache "
        "ORDER BY class_key,action",
        "actions": "SELECT id,proposal_id,type,status FROM actions ORDER BY id",
    }
    return {name: [tuple(row) for row in conn.execute(sql)] for name, sql in queries.items()}


def _windows(horizon_days: int) -> list[str]:
    return [
        format_timestamp(SIMULATED_START + timedelta(days=day, hours=23, minutes=59))
        for day in range(horizon_days)
    ]


def test_uninterrupted_and_resumed_replay_produce_the_same_results(tmp_path: Path) -> None:
    """Batch drain versus windowed replay: one shared kernel, one outcome."""
    count = 3
    batch = _replay_connection(tmp_path, "batch.db", count)
    run_replay(batch, clock=Clock.replay(), reader_callable=_reader)
    expected = _business_rows(batch)
    assert len(expected["proposals"]) == count
    assert verify_ledger(batch)[0] is True
    assert len(expected["ledger"]) > 0
    batch.close()

    windowed = _replay_connection(tmp_path, "windowed.db", count)
    clock = Clock.replay(SIMULATED_START - timedelta(days=1))
    with use_clock(clock):
        session = prepare_replay_session(windowed, clock, reader_callable=_reader)
        assert session is not None
        for horizon in _windows(count):
            session.advance_to(horizon)
        assert session.remaining == 0
        session.finish()
    assert _business_rows(windowed) == expected
    assert verify_ledger(windowed)[0] is True
    windowed.close()


def test_crash_at_each_effect_boundary_reconciles_without_duplicating_effects(
    tmp_path: Path,
) -> None:
    """Re-reaching an already-applied event must not write a second effect anywhere."""
    count = 3
    reference = _replay_connection(tmp_path, "clean.db", count)
    run_replay(reference, clock=Clock.replay(), reader_callable=_reader)
    expected = _business_rows(reference)
    ledger_length = reference.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    assert verify_ledger(reference)[0] is True
    reference.close()

    for cut in range(1, count + 1):
        crashed = _replay_connection(tmp_path, f"crash-{cut}.db", count)
        clock = Clock.replay(SIMULATED_START - timedelta(days=1))
        with use_clock(clock):
            partial = prepare_replay_session(crashed, clock, reader_callable=_reader)
            assert partial is not None
            partial.advance_to(_windows(cut)[-1])
            position = partial.position
        assert isinstance(position, ReplayPosition)
        crashed.close()  # the process dies: models, cursor and clock are all lost

        recovered = get_connection(tmp_path / f"crash-{cut}.db")
        clock = Clock.replay(SIMULATED_START - timedelta(days=1))
        with use_clock(clock):
            resumed = prepare_replay_session(recovered, clock, reader_callable=_reader)
            assert resumed is not None
            resumed.advance_to(None)
            resumed.finish()
        assert _business_rows(recovered) == expected, f"diverged after a crash at cut {cut}"
        assert recovered.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == ledger_length
        assert verify_ledger(recovered)[0] is True
        recovered.close()


def test_replayed_time_drives_what_the_engine_processes(tmp_path: Path) -> None:
    """start/pause/speed change engine state, because the pump reads the simulated instant."""
    conn = _replay_connection(tmp_path, "pump.db", 3)
    _submit(conn, _intent("pump-start", "replay_start", 0))
    controller = ReplayController(
        RoleAccess(conn, Role.EXAMINER),
        workspace_id=WORKSPACE,
        run_id="active",
        controller_id="examiner-pump",
    )
    clock = Clock.replay(SIMULATED_START - timedelta(days=1))

    def factory() -> Any:
        return prepare_replay_session(conn, clock, reader_callable=_reader)

    proposals = lambda: int(conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0])  # noqa: E731

    with use_clock(clock):
        assert (
            controller.process_pending(
                operational_at=_operational(1),
                initial_simulated_at=format_timestamp(SIMULATED_START),
            )
            == 1
        )
        # The replayed clock is still at the simulated start: the 10:00 situations are ahead of
        # it, so the engine is given nothing but the opening ticks.
        controller.advance(elapsed_seconds=0, operational_at=_operational(2))
        assert controller.pump(factory, operational_at=_operational(2)) > 0
        assert proposals() == 0, "replay proposed history its simulated clock had not reached"

        # Two seconds of real time at speed 1 is two seconds of history: still short of 10:00.
        controller.advance(elapsed_seconds=2, operational_at=_operational(4))
        controller.pump(factory, operational_at=_operational(4))
        assert proposals() == 0

        # The same distance at speed 100 reaches far more of the stream.
        _submit(conn, _intent("pump-speed", "replay_speed", 5, speed=100))
        assert (
            controller.process_pending(
                operational_at=_operational(6),
                initial_simulated_at=format_timestamp(SIMULATED_START),
            )
            == 1
        )
        controller.advance(elapsed_seconds=400, operational_at=_operational(403))
        controller.pump(factory, operational_at=_operational(403))
        assert proposals() == 1, "speed 100 must advance the engine, not only the display"
        horizon = parse_timestamp(str(controller.state()["simulated_at"]))
        assert horizon.hour >= 11
        assert (
            conn.execute(
                """SELECT COUNT(*) FROM proposals p JOIN situations s ON s.id=p.situation_id
                WHERE s.occurred_at COLLATE UTC_TIMESTAMP > ?""",
                (format_timestamp(horizon),),
            ).fetchone()[0]
            == 0
        )

        # Pausing stops the pipeline and freezes the simulated instant it was driven to.
        _submit(conn, _intent("pump-pause", "replay_pause", 404))
        assert (
            controller.process_pending(
                operational_at=_operational(405),
                initial_simulated_at=format_timestamp(SIMULATED_START),
            )
            == 1
        )
        frozen = controller.state()["simulated_at"]
        assert controller.pump(factory, operational_at=_operational(406)) == 0
        assert controller.state()["simulated_at"] == frozen
        assert proposals() == 1
        assert (
            controller.simulated_as_of(
                operational_at=_operational(407), fallback_iso="2026-05-05T00:00:00Z"
            )
            == "2026-05-05T00:00:00Z"
        ), "a paused run must not hijack the pipeline clock"
    conn.close()
