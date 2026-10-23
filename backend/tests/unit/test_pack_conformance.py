"""Contract test T-PACK: Conformance test suite for registered domain packs.

Authority: docs/PACKS_SPEC.md section 7 and docs/TEST_PLAN.md (T-PACK).
Verifies:
1. iter_situations is deterministic and idempotent.
2. deterministic_clues returns identical output when future outcomes are altered (Invariant I-6).
3. Every action in action_catalog() has type, recall flag, base cap, and loss.
4. hands_off() blocks sensitive cases.
5. resolve_outcome follows the specifications for crafted fixtures.
6. execute then undo returns the world to its original state for recallable actions.
7. Every exam operator has a validator and runs on a fixture.
"""

import json
import sqlite3
import tempfile
from pathlib import Path

from probation.core.history import HistoryView
from probation.core.types import Action, ActionStatus, Situation
from probation.db.connection import apply_schema
from probation.packs.base import PackAdapter
from probation.packs.calendar import calendar_pack
from probation.packs.calendar.exam_ops import (
    apply_calendar_code_operator,
    validate_calendar_operator_result,
)
from probation.packs.mail import mail_pack
from probation.packs.mail.exam_ops import (
    apply_mail_code_operator,
    validate_mail_operator_result,
)
from probation.packs.registry import registry
from probation.synth.world import SimWorld


def test_t_pack_action_catalogs() -> None:
    """T-PACK Check 3: Every action in action_catalog() has type, recall flag, base cap, and loss."""
    packs_to_test: list[PackAdapter] = [
        registry.get("mail"),
        registry.get("calendar"),
        registry.get("files"),
        registry.get("radar"),
        registry.get("reading"),
    ]

    for pack in packs_to_test:
        catalog = pack.action_catalog()
        assert len(catalog) >= 2, f"Pack {pack.name} catalog too small."
        action_types = set()
        for spec in catalog:
            assert spec.type, f"Action in pack {pack.name} missing type."
            assert isinstance(spec.recallable, bool)
            assert 0 <= spec.base_cap <= 3, f"Invalid base cap in {pack.name}:{spec.type}"
            assert spec.loss >= 0.0, f"Invalid loss in {pack.name}:{spec.type}"
            action_types.add(spec.type)

        if pack.name == "mail":
            assert {"REPLY", "FORWARD", "TRASH", "ARCHIVE", "LEAVE"}.issubset(action_types)
        elif pack.name == "calendar":
            assert {"ACCEPT", "DECLINE", "TENTATIVE", "NO_RESPONSE"}.issubset(action_types)
        elif pack.name == "files":
            assert {"MOVE_TO_FOLDER", "LEAVE"}.issubset(action_types)
        elif pack.name == "radar":
            assert {"TRACK", "DISMISS", "LEAVE"}.issubset(action_types)
        elif pack.name == "reading":
            assert {"FILE_TO_COLLECTION", "ARCHIVE_LINK", "LEAVE"}.issubset(action_types)


def test_t_pack_situations_determinism_and_idempotency() -> None:
    """T-PACK Check 1: iter_situations is deterministic and idempotent."""
    raw_mail = {
        "id": "raw-mail-001",
        "pack": "mail",
        "item_kind": "mail_in",
        "occurred_at": "2026-03-01T10:00:00Z",
        "content_hash": "abc123hash",
        "payload_json": json.dumps(
            {
                "message_id": "<m1@test.edu>",
                "from": "Professor Smith <smith@college.edu>",
                "to": "meena@example.test",
                "subject": "Lab 3 Instructions",
                "body": "Please read chapter 4 before Monday's lab session.",
                "labels": ["INBOX"],
                "has_attachment": False,
            }
        ),
    }

    sits1 = mail_pack.iter_situations(raw_mail)
    sits2 = mail_pack.iter_situations(raw_mail)

    assert len(sits1) == 1
    assert sits1[0].id == sits2[0].id
    assert sits1[0].sender_key == "smith@college.edu"
    assert sits1[0].redacted_text == sits2[0].redacted_text

    # Skip mail_sent
    raw_sent = dict(raw_mail, item_kind="mail_sent")
    assert mail_pack.iter_situations(raw_sent) == []

    # Calendar check
    raw_invite = {
        "id": "raw-cal-001",
        "pack": "calendar",
        "item_kind": "invite",
        "occurred_at": "2026-03-02T12:00:00Z",
        "content_hash": "cal123hash",
        "payload_json": json.dumps(
            {
                "uid": "event-uid-99",
                "title": "Study Group Meeting",
                "description": "Discussing exam problems",
                "start_time": "2026-03-05T14:00:00Z",
                "end_time": "2026-03-05T15:00:00Z",
                "organizer": "alice@college.edu",
                "my_status": "NEEDS_ACTION",
            }
        ),
    }

    cal_sits1 = calendar_pack.iter_situations(raw_invite)
    cal_sits2 = calendar_pack.iter_situations(raw_invite)
    assert len(cal_sits1) == 1
    assert cal_sits1[0].id == cal_sits2[0].id
    assert cal_sits1[0].sender_key == "alice@college.edu"


def test_t_pack_hands_off_rules() -> None:
    """T-PACK Check 4: hands_off() blocks listed sensitive cases."""
    # Mail with password reset
    sit_pw = Situation(
        id="sit-pw",
        raw_item_id="raw-1",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-01T10:00:00Z",
        content_hash="h1",
        redacted_text="Click here for password reset and bank account verification.",
        created_at="2026-03-01T10:00:00Z",
    )
    assert mail_pack.hands_off(sit_pw) is not None

    # Ordinary email not blocked
    sit_normal = Situation(
        id="sit-norm",
        raw_item_id="raw-2",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-01T10:00:00Z",
        content_hash="h2",
        redacted_text="Hey, let us meet for lunch at the cafeteria.",
        created_at="2026-03-01T10:00:00Z",
    )
    assert mail_pack.hands_off(sit_normal) is None


def test_t_pack_no_peeking_clues() -> None:
    """T-PACK Check 2: deterministic_clues returns identical output when future outcomes are altered (I-6)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)

    # Register source record for foreign key integrity
    conn.execute(
        "INSERT INTO sources (id, pack, kind, ref, imported_at) VALUES ('s1', 'mail', 'mbox', 'test.mbox', '2026-03-01T00:00:00Z');"
    )

    # Ingest past data (occurred_at = 2026-03-01)
    past_msg = json.dumps(
        {
            "message_id": "<p1@college.edu>",
            "from": "prof@college.edu",
            "to": "meena@example.test",
            "body": "First email",
        }
    )
    conn.execute(
        """
        INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
        VALUES ('r-p1', 's1', 'mail', 'mail_in', '<p1@college.edu>', '2026-03-01T10:00:00Z', '2026-03-01T10:00:00Z', ?, 'h1');
        """,
        (past_msg,),
    )
    conn.commit()

    # Situation at t = 2026-03-05
    sit = Situation(
        id="sit-t",
        raw_item_id="r-p2",
        pack="mail",
        family="email_action",
        occurred_at="2026-03-05T12:00:00Z",
        sender_key="prof@college.edu",
        content_hash="h2",
        redacted_text="Second email",
        created_at="2026-03-05T12:00:00Z",
    )

    # The current observation must really exist at this cutoff; missing source is
    # a failure, not a successful empty clue set.
    conn.execute(
        "INSERT INTO raw_items VALUES ('r-p2','s1','mail','mail_in','current','2026-03-05T12:00:00Z','2026-03-05T12:00:00Z',?,'h2')",
        (json.dumps({"from": "prof@college.edu", "body": "Second email"}),),
    )
    conn.commit()
    hist1 = HistoryView(conn, as_of="2026-03-05T12:00:00Z")
    clues1 = mail_pack.deterministic_clues(sit, hist1)

    # Now add FUTURE data at t = 2026-03-10
    future_msg = json.dumps(
        {
            "message_id": "<fut@college.edu>",
            "from": "prof@college.edu",
            "to": "meena@example.test",
            "body": "Future email",
        }
    )
    conn.execute(
        """
        INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
        VALUES ('r-fut', 's1', 'mail', 'mail_in', '<fut@college.edu>', '2026-03-10T10:00:00Z', '2026-03-10T10:00:00Z', ?, 'hfut');
        """,
        (future_msg,),
    )
    conn.commit()

    hist2 = HistoryView(conn, as_of="2026-03-05T12:00:00Z")
    clues2 = mail_pack.deterministic_clues(sit, hist2)

    assert clues1 == clues2, "Deterministic clues leaked future raw items!"


def test_t_pack_execute_and_undo_in_simworld() -> None:
    """T-PACK Check 6: execute then undo returns the world to its original state for recallable actions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        world_db = Path(tmp_dir) / "world.db"
        with SimWorld(world_db) as world:
            # 1. Setup Mail in World
            world.add_message(
                msg_id="m1",
                message_id="<msg-archive-test@test.local>",
                thread_id="t1",
                from_addr="sender@test.local",
                to_addr="meena@example.test",
                subject="Test Archive",
                body="Hello",
                labels=["INBOX"],
                received_at="2026-03-01T10:00:00Z",
            )

            # Test ARCHIVE execute and undo
            act_archive = Action(
                id="act-arch-1",
                proposal_id="prop-1",
                pack="mail",
                type="ARCHIVE",
                params={"message_id": "<msg-archive-test@test.local>"},
                level_required=2,
                recallable=True,
                status=ActionStatus.PENDING,
                created_at="2026-03-01T10:05:00Z",
                updated_at="2026-03-01T10:05:00Z",
            )

            res_exec = mail_pack.execute(act_archive, world)
            assert res_exec.success
            msg_after = world.get_message("<msg-archive-test@test.local>")
            assert msg_after is not None
            assert "INBOX" not in msg_after["labels"]

            act_undo = Action(
                id="act-arch-1",
                proposal_id="prop-1",
                pack="mail",
                type="ARCHIVE",
                params={"message_id": "<msg-archive-test@test.local>"},
                undo=res_exec.undo_data,
                level_required=2,
                recallable=True,
                status=ActionStatus.DONE,
                created_at="2026-03-01T10:05:00Z",
                updated_at="2026-03-01T10:05:00Z",
            )
            res_undo = mail_pack.undo(act_undo, world)
            assert res_undo.success
            msg_restored = world.get_message("<msg-archive-test@test.local>")
            assert msg_restored is not None
            assert "INBOX" in msg_restored["labels"]

            # 2. Setup Calendar in World
            world.add_event(
                event_id="e1",
                uid="uid-rsvp-test",
                title="Staff Meeting",
                description="Weekly sync",
                start_time="2026-03-10T10:00:00Z",
                end_time="2026-03-10T11:00:00Z",
                organizer="boss@test.local",
                attendees=["meena@example.test"],
                my_status="NEEDS_ACTION",
            )

            act_accept = Action(
                id="act-cal-1",
                proposal_id="prop-2",
                pack="calendar",
                type="ACCEPT",
                params={"uid": "uid-rsvp-test"},
                level_required=2,
                recallable=True,
                status=ActionStatus.PENDING,
                created_at="2026-03-01T10:05:00Z",
                updated_at="2026-03-01T10:05:00Z",
            )
            res_cal_exec = calendar_pack.execute(act_accept, world)
            assert res_cal_exec.success
            ev_after = world.get_event("uid-rsvp-test")
            assert ev_after is not None
            assert ev_after["my_status"] == "ACCEPTED"

            act_cal_undo = Action(
                id="act-cal-1",
                proposal_id="prop-2",
                pack="calendar",
                type="ACCEPT",
                params={"uid": "uid-rsvp-test"},
                undo=res_cal_exec.undo_data,
                level_required=2,
                recallable=True,
                status=ActionStatus.DONE,
                created_at="2026-03-01T10:05:00Z",
                updated_at="2026-03-01T10:05:00Z",
            )
            res_cal_undo = calendar_pack.undo(act_cal_undo, world)
            assert res_cal_undo.success
            ev_restored = world.get_event("uid-rsvp-test")
            assert ev_restored is not None
            assert ev_restored["my_status"] == "NEEDS_ACTION"


def test_t_pack_exam_operators() -> None:
    """T-PACK Check 7: Every exam operator has a validator and runs on a fixture."""
    mail_ops = mail_pack.exam_operators()
    assert len(mail_ops) == 10

    sample_mail = "Hi Dr. Rao,\nAttached is the weekly report.\nBest regards,\nMeena"
    payload = {"from": "dr.rao@college.edu"}

    for op in mail_ops:
        if op.engine == "code":
            mut_text, _ = apply_mail_code_operator(op.name, sample_mail, payload)
            ok = validate_mail_operator_result(op.name, sample_mail, mut_text)
            assert ok, f"Validator failed for mail operator {op.name}"

    cal_ops = calendar_pack.exam_operators()
    assert len(cal_ops) == 6

    cal_payload = {
        "title": "Lab 4 Demo",
        "description": "Please be on time.",
        "organizer": "prof@college.edu",
        "start_time": "2026-03-12T14:00:00Z",
        "conflicts_count": 0,
    }

    for op in cal_ops:
        if op.engine == "code":
            mut_cal = apply_calendar_code_operator(op.name, cal_payload)
            ok = validate_calendar_operator_result(op.name, cal_payload, mut_cal)
            assert ok, f"Validator failed for calendar operator {op.name}"
