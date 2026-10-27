"""Real fake-target effects, hold/cancel and durable crash/restart acceptance."""

from pathlib import Path

import pytest

from probation.core.clock import Clock, parse_timestamp
from probation.core.enums import GateDecision
from probation.core.lifecycle import ResponseIntent, binding_hash
from probation.core.review_binding import build_review_binding
from probation.db.access import Role, RoleAccess
from probation.db.connection import get_connection
from probation.db.lifecycle_actions import ActionStore
from probation.db.lifecycle_responses import ResponseStore
from probation.packs.mail.lifecycle_io import MailReceipt
from probation.synth.world import SimWorld
from probation.workers.executor import Executor
from tests.unit.wp6_mail_fixture import GRANT, NOW, seed

LATER = "2026-10-01T01:00:01Z"


def worker(conn, world, level=2, owner="executor"):  # type: ignore[no-untyped-def]
    return Executor(
        conn,
        world,
        licence_checker=lambda *_: level,
        grant_resolver=lambda _: GRANT,
        worker_id=owner,
    )


def approve(conn, action="ARCHIVE"):  # type: ignore[no-untyped-def]
    binding = build_review_binding(
        conn,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=LATER,
        response="accept",
    )
    ResponseStore(RoleAccess(conn, Role.API)).submit(
        ResponseIntent(
            request_id="approve",
            proposal_id="proposal",
            response="accept",
            owner_id="owner",
            responded_at=LATER,
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
        )
    )
    return binding


def undo_request(conn, action_id, at, key="undo"):  # type: ignore[no-untyped-def]
    binding = ActionStore(RoleAccess(conn, Role.EXECUTOR)).get_binding(action_id)
    ResponseStore(RoleAccess(conn, Role.API)).submit(
        ResponseIntent(
            request_id=key,
            proposal_id="proposal",
            action_id=action_id,
            response="undo",
            owner_id="owner",
            responded_at=at,
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
        )
    )


def test_autonomous_reply_holds_full_ten_minutes_and_cancel_prevents_send(tmp_path: Path) -> None:
    conn, world = seed(tmp_path, "REPLY", autonomous=True)
    binding = build_review_binding(
        conn,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=NOW,
        response="accept",
    )
    executor = worker(conn, world)
    action = executor.create_action(
        "proposal",
        "mail",
        "REPLY",
        binding.params,
        2,
        False,
        GateDecision.HOLD_THEN_EXECUTE,
        NOW,
        binding=binding,
    )
    assert action.hold_until == "2026-10-01T01:10:00Z"
    assert executor.process_queue("2026-10-01T01:09:59Z") == []
    undo_request(conn, action.id, "2026-10-01T01:09:59Z")
    executor.process_responses("2026-10-01T01:09:59Z")
    executor.process_queue("2026-10-01T01:09:59Z")
    assert ActionStore(executor.role_access).get(action.id).status == "CANCELLED"
    assert (
        world.conn.execute("SELECT count(*) FROM messages WHERE labels LIKE '%SENT%'").fetchone()[0]
        == 0
    )
    assert (
        conn.execute("SELECT count(*) FROM outcome_events WHERE kind='cancel'").fetchone()[0] == 1
    )
    assert executor.process_queue("2026-10-01T01:11:00Z") == []
    world.close()
    conn.close()


def test_crash_after_send_reopen_reconciles_one_sent_message_without_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, world = seed(tmp_path, "REPLY")
    approve(conn, "REPLY")
    executor = worker(conn, world, level=0, owner="first")
    executor.process_responses(LATER)
    original = world.apply_mail

    def crash(*args, **kwargs):  # type: ignore[no-untyped-def]
        original(*args, **kwargs)
        raise SystemExit("synthetic process death after effect")

    monkeypatch.setattr(world, "apply_mail", crash)
    with pytest.raises(SystemExit):
        executor.process_queue(LATER)
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "PENDING"
    assert conn.execute("SELECT state FROM execution_attempts").fetchone()[0] == "dispatched"
    world.close()
    conn.close()
    reopened = get_connection(tmp_path / "engine.db")
    target = SimWorld(tmp_path / "world.db", user_addresses=[GRANT.from_addr])
    recovered = worker(reopened, target, level=0, owner="second")
    results = recovered.process_queue("2026-10-01T01:00:32Z")
    assert len(results) == 1 and results[0].success
    assert reopened.execute("SELECT status FROM actions").fetchone()[0] == "DONE"
    assert (
        target.conn.execute("SELECT count(*) FROM messages WHERE labels LIKE '%SENT%'").fetchone()[
            0
        ]
        == 1
    )
    assert target.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 1
    assert recovered.process_queue("2026-10-01T01:00:33Z") == []
    target.close()
    reopened.close()


def test_confirmed_failure_is_distinct_from_unknown_and_never_marks_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, world = seed(tmp_path)
    approve(conn)
    executor = worker(conn, world, level=0)
    executor.process_responses(LATER)
    monkeypatch.setattr(
        world,
        "apply_mail",
        lambda *_: MailReceipt(
            "failed", safe_code="revision_changed", after_state={"confirmed_no_effect": True}
        ),
    )
    result = executor.process_queue(LATER)
    assert result and not result[0].success
    assert conn.execute("SELECT state FROM execution_attempts").fetchone()[0] == "failed"
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "FAILED"
    assert "INBOX" in world.get_message("<m@test.local>")["labels"]
    world.close()
    conn.close()


def test_undo_deadline_and_two_requests_do_not_repeat_compensation(tmp_path: Path) -> None:
    conn, world = seed(tmp_path)
    approve(conn)
    executor = worker(conn, world, level=0)
    executor.process_responses(LATER)
    executor.process_queue(LATER)
    action_id = conn.execute("SELECT id FROM actions").fetchone()[0]
    undo_at = "2026-10-01T01:00:02Z"
    undo_request(conn, action_id, undo_at, "undo-1")
    undo_request(conn, action_id, undo_at, "undo-2")
    assert executor.process_responses(undo_at) == 2
    executor.process_queue(undo_at)
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "UNDONE"
    assert conn.execute("SELECT count(*) FROM outcome_events WHERE kind='undo'").fetchone()[0] == 1
    assert world.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 2
    assert executor.process_undo(action_id, undo_at).success
    assert world.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 2
    world.close()
    conn.close()


def test_expired_undo_preserves_completed_action_and_target_state(tmp_path: Path) -> None:
    conn, world = seed(tmp_path)
    approve(conn)
    executor = worker(conn, world, level=0)
    executor.process_responses(LATER)
    executor.process_queue(LATER)
    action_id = conn.execute("SELECT id FROM actions").fetchone()[0]
    late = "2026-10-08T01:00:02Z"
    undo_request(conn, action_id, late)
    result = executor.process_undo(action_id, late)
    assert not result.success and result.error == "undo_expired"
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "DONE"
    assert "INBOX" not in world.get_message("<m@test.local>")["labels"]
    assert conn.execute("SELECT count(*) FROM outcome_events WHERE kind='undo'").fetchone()[0] == 0
    world.close()
    conn.close()


def test_clock_expiring_while_provider_runs_requires_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, world = seed(tmp_path)
    approve(conn)
    clock = Clock.replay(parse_timestamp(LATER))
    executor = Executor(
        conn, world, clock=clock, licence_checker=lambda *_: 0, grant_resolver=lambda _: GRANT
    )
    executor.process_responses()
    original = world.apply_mail

    def slow(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = original(*args, **kwargs)
        clock.advance_seconds(40)
        return result

    monkeypatch.setattr(world, "apply_mail", slow)
    first = executor.process_queue()
    assert first and not first[0].success
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "PENDING"
    assert conn.execute("SELECT state FROM execution_attempts").fetchone()[0] == "dispatched"
    monkeypatch.setattr(world, "apply_mail", original)
    second = executor.process_queue()
    assert second and second[0].success
    assert world.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 1
    world.close()
    conn.close()


def test_action_transition_and_attempt_confirmation_rollback_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probation.core.lifecycle import LifecycleDenied

    conn, world = seed(tmp_path)
    approve(conn)
    executor = worker(conn, world, level=0)
    executor.process_responses(LATER)
    original = ActionStore.transition

    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise LifecycleDenied("synthetic finalization interruption")

    monkeypatch.setattr(ActionStore, "transition", fail)
    assert not executor.process_queue(LATER)[0].success
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "PENDING"
    assert conn.execute("SELECT state FROM execution_attempts").fetchone()[0] == "dispatched"
    monkeypatch.setattr(ActionStore, "transition", original)
    assert executor.process_queue("2026-10-01T01:00:32Z")[0].success
    assert world.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 1
    world.close()
    conn.close()


def test_fresh_oauth_authorization_supersedes_an_earlier_revoke_for_undo(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from probation.core.lifecycle import CommandIntent, CommandScope
    from probation.db.lifecycle_commands import CommandStore
    from probation.workers.restrictions import process_restriction_commands

    conn, world = seed(tmp_path)
    approve(conn)
    executor = worker(conn, world, level=0)
    executor.process_responses(LATER)
    executor.process_queue(LATER)
    action_id = conn.execute("SELECT id FROM actions").fetchone()[0]
    CommandStore(RoleAccess(conn, Role.API)).submit(
        CommandIntent(
            request_id="revoke",
            owner_id="owner",
            type="revoke",
            scope=CommandScope(connection_id=GRANT.connection_id, account_id=GRANT.account_id),
            created_at="2026-10-01T01:00:02Z",
        )
    )
    process_restriction_commands(conn, as_of="2026-10-01T01:00:03Z")
    undo_request(conn, action_id, "2026-10-01T01:00:04Z")
    blocked = executor.process_undo(action_id, "2026-10-01T01:00:05Z")
    assert not blocked.success and blocked.error == "restriction_changed"

    reauthorized = Executor(
        conn,
        world,
        licence_checker=lambda *_: 0,
        grant_resolver=lambda _: replace(GRANT, authorized_at="2026-10-01T01:00:06Z"),
    )
    undone = reauthorized.process_undo(action_id, "2026-10-01T01:00:07Z")
    assert undone.success
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "UNDONE"
    assert "INBOX" in world.get_message("<m@test.local>")["labels"]
    world.close()
    conn.close()


def test_replay_controls_do_not_poison_execution_restrictions(tmp_path: Path) -> None:
    from probation.core.replay_controls import ReplayCommandIntent, server_replay_scope
    from probation.db.replay_commands import ReplayCommandStore
    from probation.workers.restrictions import current_restrictions

    conn, world = seed(tmp_path)
    binding = build_review_binding(
        conn,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=LATER,
        response="accept",
    )
    ReplayCommandStore(RoleAccess(conn, Role.API)).submit(
        ReplayCommandIntent(
            request_id="replay-start",
            owner_id="owner",
            type="replay_start",
            scope=server_replay_scope("owner", tmp_path / "engine.db"),
            created_at=LATER,
        )
    )
    restrictions = current_restrictions(conn, binding, LATER, class_key="mail|other|known")
    assert restrictions.revision == "0"
    assert not restrictions.blocked
    assert restrictions.reasons == ()
    world.close()
    conn.close()


def test_pending_revocation_blocks_undo_effect(tmp_path: Path) -> None:
    from probation.core.lifecycle import CommandIntent, CommandScope
    from probation.db.lifecycle_commands import CommandStore

    conn, world = seed(tmp_path)
    approve(conn)
    executor = worker(conn, world, level=0)
    executor.process_responses(LATER)
    executor.process_queue(LATER)
    action_id = conn.execute("SELECT id FROM actions").fetchone()[0]
    CommandStore(RoleAccess(conn, Role.API)).submit(
        CommandIntent(
            request_id="revoke",
            owner_id="owner",
            type="revoke",
            scope=CommandScope(connection_id=GRANT.connection_id, account_id=GRANT.account_id),
            created_at="2026-10-01T01:00:02Z",
        )
    )
    undo_request(conn, action_id, "2026-10-01T01:00:03Z")
    result = executor.process_undo(action_id, "2026-10-01T01:00:03Z")
    assert not result.success and result.error == "restriction_changed"
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "DONE"
    assert "INBOX" not in world.get_message("<m@test.local>")["labels"]
    world.close()
    conn.close()


def test_unknown_missing_receipt_never_retries_send_or_claims_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn, world = seed(tmp_path, "REPLY")
    approve(conn, "REPLY")
    executor = worker(conn, world, level=0)
    executor.process_responses(LATER)
    calls = []

    def unknown(*args):  # type: ignore[no-untyped-def]
        calls.append(args[0])
        return MailReceipt("unknown", safe_code="transport_ambiguous")

    monkeypatch.setattr(world, "apply_mail", unknown)
    assert not executor.process_queue(LATER)[0].success
    assert not executor.process_queue("2026-10-01T01:00:32Z")[0].success
    assert not executor.process_queue("2026-10-01T01:01:03Z")[0].success
    assert len(calls) == 1
    assert conn.execute("SELECT state FROM execution_attempts").fetchone()[0] == "unknown"
    assert conn.execute("SELECT status FROM actions").fetchone()[0] == "PENDING"
    assert (
        world.conn.execute("SELECT count(*) FROM messages WHERE labels LIKE '%SENT%'").fetchone()[0]
        == 0
    )
    world.close()
    conn.close()


def test_restricted_forward_uses_exact_reviewed_recipient_and_source_content(
    tmp_path: Path,
) -> None:
    conn, world = seed(tmp_path)
    controlled = "controlled@test.local"
    binding = build_review_binding(
        conn,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=LATER,
        response="edit",
        edited_action="FORWARD",
        forward_recipient=controlled,
        allowed_forward_recipients=(controlled,),
    )
    ResponseStore(RoleAccess(conn, Role.API)).submit(
        ResponseIntent(
            request_id="forward",
            proposal_id="proposal",
            response="edit",
            edited_action="FORWARD",
            owner_id="owner",
            responded_at=LATER,
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
        )
    )
    executor = Executor(
        conn,
        world,
        licence_checker=lambda *_: 0,
        grant_resolver=lambda _: GRANT,
        allowed_forward_recipients=(controlled,),
    )
    executor.process_responses(LATER)
    result = executor.process_queue(LATER)
    assert result and result[0].success
    sent = world.conn.execute("SELECT * FROM messages WHERE labels LIKE '%SENT%'").fetchall()
    assert (
        len(sent) == 1
        and sent[0]["to_addr"] == controlled
        and sent[0]["from_addr"] == GRANT.from_addr
    )
    assert sent[0]["body"] == binding.body_text and "Some information." in sent[0]["body"]
    assert sent[0]["in_reply_to"] is None and sent[0]["thread_id"] != "thread"
    assert conn.execute("SELECT hold_until FROM actions").fetchone()[0] is None
    world.close()
    conn.close()
