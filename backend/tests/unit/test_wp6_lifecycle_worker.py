"""Bounded orchestration retains separate role capabilities and safe stage ordering."""

from threading import Event

import pytest

from probation.core.clock import Clock, parse_timestamp
from probation.core.lifecycle import LifecycleStoreUnavailable, ResponseIntent, binding_hash
from probation.core.review_binding import build_review_binding
from probation.db.access import Role, RoleAccess
from probation.db.connection import get_role_connection
from probation.db.lifecycle_responses import ResponseStore
from probation.workers.drift import review_outcome_events
from probation.workers.executor import Executor
from probation.workers.lifecycle import LifecycleCoordinator, RoleConnections, WorkerSteps
from probation.workers.response_resolver import resolve_responses
from probation.workers.restrictions import process_restriction_commands
from tests.unit.wp6_mail_fixture import GRANT, seed


def connections(path):
    return RoleConnections(
        *(
            get_role_connection(path, role)
            for role in (Role.RESOLVER, Role.EXAMINER, Role.EXECUTOR, Role.BRAIN)
        )
    )


def test_real_role_steps_accept_effect_then_restart_without_duplicate(tmp_path):
    bootstrap, world = seed(tmp_path)
    binding = build_review_binding(
        bootstrap,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of="2026-10-01T01:00:01Z",
        response="accept",
    )
    ResponseStore(RoleAccess(bootstrap, Role.API)).submit(
        ResponseIntent(
            request_id="approve",
            proposal_id="proposal",
            response="accept",
            owner_id="owner",
            responded_at="2026-10-01T01:00:01Z",
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
        )
    )
    bootstrap.close()
    clock = Clock.replay(parse_timestamp("2026-10-01T01:00:02Z"))
    for attempt in range(2):
        handles = connections(tmp_path / "engine.db")
        worker = Executor(
            handles.executor,
            world,
            clock=clock,
            licence_checker=lambda *_: 0,
            grant_resolver=lambda _: GRANT,
        )

        def examine(conn, at, limit):
            return review_outcome_events(conn, as_of=at) + process_restriction_commands(
                conn, as_of=at, limit=limit
            )

        steps = WorkerSteps(
            resolver=lambda conn, at, limit: resolve_responses(conn, as_of=at, limit=limit),
            examiner=examine,
            consume=lambda conn, at, limit, worker=worker: worker.process_responses(at, limit),
            effects=lambda conn, at, limit, worker=worker: sum(
                result.success for result in worker.process_queue(at)
            ),
        )
        tick = LifecycleCoordinator(handles, steps, clock=clock).tick(Event())
        assert not tick.errors
        assert tick.counts["effects"] == int(attempt == 0)
        assert (
            handles.resolver.execute(
                "SELECT COUNT(*) FROM outcome_events WHERE kind='decision'"
            ).fetchone()[0]
            == 1
        )
        assert handles.examiner.execute("SELECT COUNT(*) FROM drift_receipts").fetchone()[0] == 1
        for conn in handles.all():
            conn.close()
    assert world.conn.execute("SELECT COUNT(*) FROM mail_operations").fetchone()[0] == 1
    world.close()


def test_stop_between_stages_does_not_dispatch_and_role_mismatch_denied(tmp_path):
    bootstrap, world = seed(tmp_path)
    bootstrap.close()
    handles = connections(tmp_path / "engine.db")
    stop = Event()
    seen = []

    def resolver(conn, at, limit):
        seen.append("resolver")
        stop.set()
        return 0

    def forbidden(conn, at, limit):
        raise AssertionError("stopped stage ran")

    coordinator = LifecycleCoordinator(
        handles,
        WorkerSteps(resolver, forbidden, forbidden, forbidden),
        clock=Clock.replay(parse_timestamp("2026-10-01T01:00:02Z")),
    )
    assert coordinator.tick(stop).stopped
    assert seen == ["resolver"]
    with pytest.raises(ValueError):
        LifecycleCoordinator(
            RoleConnections(handles.examiner, handles.resolver, handles.executor, handles.brain),
            coordinator.steps,
            clock=coordinator.clock,
        )
    for conn in handles.all():
        conn.close()
    world.close()


def test_review_failure_aborts_effects(tmp_path):
    bootstrap, world = seed(tmp_path)
    bootstrap.close()
    handles = connections(tmp_path / "engine.db")
    seen = []

    def fail(conn, at, limit):
        raise LifecycleStoreUnavailable("review_unavailable")

    def effect(conn, at, limit):
        seen.append("effect")
        return 1

    tick = LifecycleCoordinator(
        handles,
        WorkerSteps(lambda *_: 0, fail, effect, effect),
        clock=Clock.replay(parse_timestamp("2026-10-01T01:00:02Z")),
    ).tick(Event())
    assert tick.errors == ("examiner:review_unavailable",)
    assert seen == []
    for conn in handles.all():
        conn.close()
    world.close()


def test_loop_passes_bounded_batches_and_stops_without_waiting(tmp_path):
    bootstrap, world = seed(tmp_path)
    bootstrap.close()
    handles = connections(tmp_path / "engine.db")
    seen = []

    def step(conn, at, limit):
        seen.append((conn.bound_role, at, limit))
        return 0

    coordinator = LifecycleCoordinator(
        handles,
        WorkerSteps(step, step, step, step),
        clock=Clock.replay(parse_timestamp("2026-10-01T01:00:02Z")),
        batch_size=7,
    )
    stop = Event()
    assert coordinator.run(stop, max_ticks=1) == 1
    assert [role for role, _, _ in seen] == [
        "resolver",
        "examiner",
        "executor",
        "executor",
        "examiner",
    ]
    assert all(limit == 7 for _, _, limit in seen)
    stop.set()
    assert coordinator.run(stop, max_ticks=1) == 0
    with pytest.raises(ValueError):
        coordinator.run(Event(), poll_seconds=2, max_ticks=0)
    for conn in handles.all():
        conn.close()
    world.close()
