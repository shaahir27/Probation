"""D3 exact approval and durable dispatch safety boundaries."""

from pathlib import Path

from probation.core.enums import GateDecision
from probation.core.lifecycle import ResponseIntent, binding_hash
from probation.core.review_binding import build_review_binding
from probation.db.access import Role, RoleAccess
from probation.db.lifecycle_responses import ResponseStore
from probation.workers.executor import Executor

from .wp6_mail_fixture import GRANT, NOW, seed


def test_unbound_mail_intent_cannot_use_licence_instead_of_source_authority(tmp_path: Path) -> None:
    conn, world = seed(tmp_path)
    worker = Executor(conn, world, licence_checker=lambda *_: 3)
    worker.create_action(
        "proposal",
        "mail",
        "ARCHIVE",
        {"message_id": "<m@test.local>"},
        2,
        True,
        GateDecision.EXECUTE_UNDO,
        NOW,
    )
    conn.commit()
    worker.process_queue(NOW)
    assert "INBOX" in world.get_message("<m@test.local>")["labels"]
    world.close()
    conn.close()


def test_explicit_authority_does_not_become_a_zero_level_licence(tmp_path: Path) -> None:
    conn, world = seed(tmp_path)
    binding = build_review_binding(
        conn,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=NOW,
        response="accept",
    )
    worker = Executor(conn, world, licence_checker=lambda *_: 0, grant_resolver=lambda _: GRANT)
    approved_at = "2026-10-01T01:00:01Z"
    ResponseStore(RoleAccess(conn, Role.API)).submit(
        ResponseIntent(
            request_id="approve",
            proposal_id="proposal",
            response="accept",
            owner_id="owner",
            responded_at=approved_at,
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
        )
    )
    assert worker.process_responses(approved_at) == 1
    results = worker.process_queue(approved_at)
    assert len(results) == 1 and results[0].success
    assert "INBOX" not in world.get_message("<m@test.local>")["labels"]
    stored = conn.execute("SELECT * FROM actions").fetchone()
    assert stored["authority_kind"] == "explicit_user" and stored["level_required"] == 1
    assert stored["status"] == "DONE" and stored["hold_until"] is None
    assert worker.process_responses(approved_at) == 0
    assert worker.process_queue(approved_at) == []
    assert world.conn.execute("SELECT count(*) FROM mail_operations").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM licence_cache WHERE level>0").fetchone()[0] == 0
    world.close()
    conn.close()
