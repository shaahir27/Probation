"""Test T-EXEC: Executor side-effect execution, hold queue, licence re-check, and undo in SimWorld.

Authority: docs/CONTRACT.md section 8, I-2, I-10, I-20, and docs/TEST_PLAN.md T-EXEC.
"""

from pathlib import Path

from probation.core.enums import ActionStatus, GateDecision
from probation.db.connection import apply_schema, get_connection
from probation.synth.world import SimWorld
from probation.workers.executor import Executor


def test_t_exec_mail_and_calendar_simworld(tmp_path: Path) -> None:
    """Verify execution, hold queue, licence re-check, and undo in SimWorld for mail and calendar."""
    probation_db_path = tmp_path / "probation.db"
    world_db_path = tmp_path / "world.db"

    conn = get_connection(probation_db_path)
    apply_schema(conn)
    cur = conn.cursor()

    # Insert sources, raw items, and situations to satisfy foreign key constraints
    cur.execute(
        """
        INSERT INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-mail', 'mail', 'mbox', 'ref-1', '2026-05-01T00:00:00Z'),
               ('src-cal', 'calendar', 'ics', 'ref-2', '2026-05-01T00:00:00Z');
        """
    )
    cur.execute(
        """
        INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
        VALUES ('raw-1', 'src-mail', 'mail', 'mail_in', '<msg-1@test.local>', '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', '{}', 'h1'),
               ('raw-2', 'src-cal', 'calendar', 'cal_event', 'event-uid-1', '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', '{}', 'h2'),
               ('raw-3', 'src-cal', 'calendar', 'cal_event', 'event-uid-3', '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', '{}', 'h3');
        """
    )
    cur.execute(
        """
        INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
        VALUES ('sit-1', 'raw-1', 'mail', 'email_action', '2026-05-01T10:00:00Z', 'h1', '2026-05-01T10:00:00Z'),
               ('sit-2', 'raw-2', 'calendar', 'invite_rsvp', '2026-05-01T10:00:00Z', 'h2', '2026-05-01T10:00:00Z'),
               ('sit-cal-3', 'raw-3', 'calendar', 'invite_rsvp', '2026-05-01T10:00:00Z', 'h3', '2026-05-01T10:00:00Z');
        """
    )
    cur.execute(
        """
        INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
        VALUES ('prop-1', 'sit-1', 'email_action', 'mail|request|known', 'ARCHIVE', '{}', 0.9, 0.1, 0, 2, 3, 'EXECUTE_UNDO', '[]', 'v1', 'h1', 0, '2026-05-01T10:00:00Z', 1),
               ('prop-2', 'sit-2', 'invite_rsvp', 'calendar|sync', 'ACCEPT', '{}', 0.99, 0.1, 0, 2, 2, 'HOLD_THEN_EXECUTE', '[]', 'v1', 'h2', 0, '2026-05-01T10:00:00Z', 2),
               ('prop-3', 'sit-cal-3', 'invite_rsvp', 'calendar|sync', 'ACCEPT', '{}', 0.99, 0.1, 0, 2, 2, 'HOLD_THEN_EXECUTE', '[]', 'v1', 'h3', 0, '2026-05-01T10:00:00Z', 3);
        """
    )
    conn.commit()

    sim_world = SimWorld(world_db_path)
    # Add a sample message and event to sim_world
    sim_world.add_message(
        msg_id="msg-1",
        message_id="<msg-1@test.local>",
        thread_id="th-1",
        from_addr="sender@example.com",
        to_addr="user@probation.local",
        subject="Important Announcement",
        body="Here is some info.",
        labels=["INBOX"],
        received_at="2026-05-01T10:00:00Z",
    )
    sim_world.add_event(
        event_id="ev-1",
        uid="event-uid-1",
        title="Weekly Sync",
        description="Sync meeting",
        start_time="2026-05-02T14:00:00Z",
        end_time="2026-05-02T15:00:00Z",
        organizer="boss@example.com",
        attendees=["user@probation.local"],
        status="CONFIRMED",
        my_status="NEEDS_ACTION",
    )

    executor = Executor(conn, sim_world)
    # Allow level 2 licences by default in test
    executor.licence_checker = lambda class_key, action, as_of: 2

    # 1. Immediate Execution (EXECUTE_UNDO): ARCHIVE mail
    act_id1 = "act-mail-archive"
    cur.execute(
        """
        INSERT INTO actions (id, proposal_id, pack, type, params_json, level_required, recallable, status, hold_until, created_at, updated_at)
        VALUES (?, 'prop-1', 'mail', 'ARCHIVE', '{"message_id": "<msg-1@test.local>"}', 2, 1, 'PENDING', NULL, '2026-05-01T10:05:00Z', '2026-05-01T10:05:00Z');
        """,
        (act_id1,),
    )
    conn.commit()

    # Process queue
    results = executor.process_queue(as_of="2026-05-01T10:05:00Z")
    assert len(results) == 1
    assert results[0].success
    assert results[0].action_id == act_id1

    # Check SimWorld state: INBOX label removed
    msg = sim_world.get_message("<msg-1@test.local>")
    assert msg is not None
    assert "INBOX" not in msg["labels"]

    # Check action status in DB
    cur.execute("SELECT status, undo_json FROM actions WHERE id = ?", (act_id1,))
    row = cur.fetchone()
    assert row["status"] == ActionStatus.DONE.value
    assert row["undo_json"] is not None

    # Idempotency check: running process_queue again does not re-execute
    results2 = executor.process_queue(as_of="2026-05-01T10:05:30Z")
    assert len(results2) == 0

    # 2. Undo ARCHIVE: restores INBOX label
    undo_res = executor.process_undo(action_id=act_id1, as_of="2026-05-01T10:10:00Z")
    assert undo_res.success
    msg_restored = sim_world.get_message("<msg-1@test.local>")
    assert msg_restored is not None
    assert "INBOX" in msg_restored["labels"]

    cur.execute("SELECT status FROM actions WHERE id = ?", (act_id1,))
    assert cur.fetchone()["status"] == ActionStatus.UNDONE.value

    # Check that strong disagreement outcome was written
    cur.execute("SELECT * FROM outcomes WHERE source = 'undo'")
    outcome_row = cur.fetchone()
    assert outcome_row is not None
    assert outcome_row["observed_action"] == "UNDO"
    assert outcome_row["strength"] == "STRONG"

    # 3. Hold Queue (HOLD_THEN_EXECUTE): RSVP ACCEPT on calendar
    act_id2 = "act-cal-accept"
    hold_time = "2026-05-01T10:15:00Z"
    cur.execute(
        """
        INSERT INTO actions (id, proposal_id, pack, type, params_json, level_required, recallable, status, hold_until, created_at, updated_at)
        VALUES (?, 'prop-2', 'calendar', 'ACCEPT', '{"uid": "event-uid-1"}', 2, 0, 'HELD', ?, '2026-05-01T10:05:00Z', '2026-05-01T10:05:00Z');
        """,
        (act_id2, hold_time),
    )
    conn.commit()

    # Before hold_time: process_queue does NOT execute
    pre_results = executor.process_queue(as_of="2026-05-01T10:10:00Z")
    assert len(pre_results) == 0
    ev_pre = sim_world.get_event("event-uid-1")
    assert ev_pre is not None
    assert ev_pre["my_status"] == "NEEDS_ACTION"

    # At or after hold_time: process_queue executes
    post_results = executor.process_queue(as_of="2026-05-01T10:15:00Z")
    assert len(post_results) == 1
    assert post_results[0].success
    ev_post = sim_world.get_event("event-uid-1")
    assert ev_post is not None
    assert ev_post["my_status"] == "ACCEPTED"

    # 4. Licence lost during hold: action is CANCELLED and SUGGEST proposal emitted
    act_id3 = "act-cal-lost"
    cur.execute(
        """
        INSERT INTO actions (id, proposal_id, pack, type, params_json, level_required, recallable, status, hold_until, created_at, updated_at)
        VALUES (?, 'prop-3', 'calendar', 'ACCEPT', '{"uid": "event-uid-1"}', 2, 0, 'HELD', '2026-05-01T10:10:00Z', '2026-05-01T10:00:00Z', '2026-05-01T10:00:00Z');
        """,
        (act_id3,),
    )
    conn.commit()

    # Inject licence re-check that returns level 0 (licence lost due to alarm or evidence drop)
    executor.licence_checker = lambda class_key, action, as_of: 0

    lost_results = executor.process_queue(as_of="2026-05-01T10:11:00Z")
    assert len(lost_results) == 0  # Not executed
    cur.execute("SELECT status FROM actions WHERE id = ?", (act_id3,))
    assert cur.fetchone()["status"] == ActionStatus.CANCELLED.value

    # Verify that the proposal gate was updated to SUGGEST
    cur.execute("SELECT gate FROM proposals WHERE situation_id = 'sit-cal-3'")
    assert cur.fetchone()["gate"] == GateDecision.SUGGEST.value

    sim_world.close()
    conn.close()
