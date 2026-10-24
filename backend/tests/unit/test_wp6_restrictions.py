"""Pending negative controls and completed resumes obey scope and actual time."""

from probation.core.lifecycle import CommandIntent, CommandScope
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_commands import CommandStore
from probation.db.lifecycle_receipts import ReceiptStore
from probation.workers.restrictions import process_restriction_commands, restrictions_for

T = "2026-06-01T01:00:00Z"
SCOPE = CommandScope(connection_id="connection", account_id="account")


def submit(conn, key, kind, at=T, scope=SCOPE, owner="owner"):
    return CommandStore(RoleAccess(conn, Role.API)).submit(
        CommandIntent(request_id=key, owner_id=owner, type=kind, scope=scope, created_at=at)
    )


def state(conn, at=T):
    return restrictions_for(
        conn,
        owner_id="owner",
        connection_id="connection",
        account_id="account",
        resource_id="message",
        class_key="mail|fyi|frequent",
        action="ARCHIVE",
        as_of=at,
    )


def test_pending_pause_blocks_before_review_and_resume_requires_completion(memory_db):
    submit(memory_db, "pause", "pause")
    assert state(memory_db).blocked
    assert state(memory_db).revision == "0"
    assert process_restriction_commands(memory_db, as_of=T) == 1
    assert state(memory_db).paused and state(memory_db).revision == "pause"
    submit(memory_db, "resume", "resume", "2026-06-01T01:01:00Z")
    assert state(memory_db, "2026-06-01T01:01:00Z").paused
    assert process_restriction_commands(memory_db, as_of="2026-06-01T01:01:00Z") == 1
    assert not state(memory_db, "2026-06-01T01:01:00Z").blocked
    assert state(memory_db).paused  # later completion never changes an earlier answer
    assert process_restriction_commands(memory_db, as_of="2026-06-01T01:01:00Z") == 0


def test_revocation_cannot_be_cleared_by_resume_and_other_scopes_do_not_leak(memory_db):
    submit(memory_db, "other", "pause", owner="another")
    submit(memory_db, "future", "pause", "2027-01-01T00:00:00Z")
    submit(
        memory_db,
        "other_action",
        "pause",
        scope=SCOPE.model_copy(update={"class_key": "mail|fyi|frequent", "action": "REPLY"}),
    )
    assert not state(memory_db).blocked
    submit(memory_db, "revoke", "revoke")
    assert state(memory_db).revoked
    process_restriction_commands(memory_db, as_of=T)
    submit(memory_db, "resume", "resume", "2026-06-01T01:01:00Z")
    process_restriction_commands(memory_db, as_of="2026-06-01T01:01:00Z")
    assert state(memory_db, "2026-06-01T01:01:00Z").revoked


def test_completed_resume_cannot_clear_an_inflight_pause(memory_db):
    submit(memory_db, "pause", "pause")
    receipts = ReceiptStore(RoleAccess(memory_db, Role.EXAMINER))
    assert receipts.claim_command("pause", now=T, owner="busy-examiner") is not None
    later = "2026-06-01T01:00:01Z"
    submit(memory_db, "resume", "resume", later)
    assert process_restriction_commands(memory_db, as_of=later) == 1
    assert state(memory_db, later).paused


def test_resume_only_clears_the_exact_pause_scope(memory_db):
    submit(memory_db, "global-pause", "pause")
    process_restriction_commands(memory_db, as_of=T)
    narrow = SCOPE.model_copy(update={"resource_id": "message"})
    later = "2026-06-01T01:00:01Z"
    submit(memory_db, "resource-resume", "resume", later, narrow)
    process_restriction_commands(memory_db, as_of=later)
    assert state(memory_db, later).paused
    submit(memory_db, "global-resume", "resume", "2026-06-01T01:00:02Z")
    process_restriction_commands(memory_db, as_of="2026-06-01T01:00:02Z")
    assert not state(memory_db, "2026-06-01T01:00:02Z").paused
