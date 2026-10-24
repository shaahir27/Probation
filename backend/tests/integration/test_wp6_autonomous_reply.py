"""Real D2 permission, held replies, restart-safe drift and re-examination.

Training rows, reader, editor and novelty are controlled synthetic fixtures;
this verifies backend behavior without claiming real provider/model quality.
"""

import json
from datetime import timedelta
from pathlib import Path

from probation.config import settings
from probation.core.clock import Clock, format_timestamp, parse_timestamp
from probation.core.enums import GateDecision
from probation.core.history import HistoryView
from probation.core.lifecycle import ResponseIntent, SourceGrant, binding_hash
from probation.core.review_binding import build_review_binding
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.connection import apply_schema, get_connection
from probation.db.ledger import verify_ledger
from probation.db.lifecycle_responses import ResponseStore
from probation.db.proposals import DraftRecord, persist_proposal
from probation.engine.exam import run_exam
from probation.engine.exam_prediction import ExamPredictionContext
from probation.engine.licence import derive_licences
from probation.engine.policy import Policy
from probation.engine.prediction import evaluate_prediction
from probation.llm.draft_validation import body_hash, validate_draft
from probation.llm.feature_pipeline import compute_features
from probation.packs.registry import registry
from probation.synth.world import SimWorld
from probation.workers.brain_followups import process_followups
from probation.workers.drift import review_outcome_events
from probation.workers.executor import Executor
from tests.unit.wp5_exam_fixtures import (
    _populate_test_situations,
    context_for,
    controlled_reader,
    fixture_editor,
)

PAIR = ("mail|request|known", "REPLY")
GRANT = SourceGrant("src-1", "synthetic-d3", "account-d3", "owner@test.local")


def add_reply(conn, context, fresh, suffix, sender=0):  # type: ignore[no-untyped-def]
    """Commit a shared-pipeline prediction and validated immutable draft."""
    raw_id, sid, pid = f"raw-{suffix}", f"d3-fresh-reply{suffix}", f"p-d3-{suffix}"
    payload = {
        "from": f"colleague{sender}@college.edu",
        "message_id": f"<d3-reply{suffix}@test.local>",
        "thread_id": f"thread-d3{suffix}",
        "subject": "Project inquiry",
        "body": "Hi Meena,\nCould you please reply regarding project planning?\nBest regards,\nColleague",
    }
    conn.execute(
        "INSERT INTO raw_items VALUES (?,'src-1','mail','mail_in',?,?,?,?,'fresh-source')",
        (raw_id, payload["message_id"], fresh, fresh, json.dumps(payload)),
    )
    situation = Situation(
        id=sid,
        raw_item_id=raw_id,
        pack="mail",
        family="email_action",
        occurred_at=fresh,
        sender_key=payload["from"],
        content_hash="fresh-source",
        redacted_text=payload["body"],
        created_at=fresh,
    )
    conn.execute(
        """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,sender_key,content_hash,redacted_text,created_at)
        VALUES (?,?,?, ?,?,?,?,?,?)""",
        (
            sid,
            raw_id,
            "mail",
            "email_action",
            fresh,
            situation.sender_key,
            situation.content_hash,
            situation.redacted_text,
            fresh,
        ),
    )
    features = compute_features(
        situation, HistoryView(conn, fresh), reader_callable=controlled_reader
    )
    conn.execute(
        """INSERT INTO features(situation_id,deterministic_json,reader_json,reader_ok,featurizer_version,
        features_hash,created_at,provenance_json) VALUES (?,?,?,1,?,?,?,?)""",
        (
            sid,
            json.dumps(features.deterministic),
            json.dumps(features.reader),
            features.featurizer_version,
            features.features_hash,
            fresh,
            features.provenance_json,
        ),
    )
    licence = derive_licences(conn, fresh)[PAIR]
    assert int(licence.level) == 2
    prediction = evaluate_prediction(
        situation,
        features,
        registry.get_descriptor("mail"),
        context.snapshot,
        licence_level=int(licence.level),
    )
    assert prediction.class_key == PAIR[0] and prediction.action == "REPLY"
    assert prediction.gate == GateDecision.HOLD_THEN_EXECUTE
    text = "Thank you for the information."
    validate_draft(text, payload["body"], needs_user_input=False)
    params = {
        "draft_proposal_id": pid,
        "to_addr": payload["from"],
        "draft_body_hash": body_hash(text),
    }
    proposal = Proposal(
        id=pid,
        situation_id=sid,
        family="email_action",
        class_key=prediction.class_key,
        action=prediction.action,
        probs=prediction.probs,
        p_max=prediction.p_max,
        novelty=prediction.novelty,
        novel=prediction.novel,
        licence_level=int(licence.level),
        cap=prediction.cap,
        gate=prediction.gate,
        params=params,
        policy_version=context.snapshot.policy.policy_version,
        features_hash=features.features_hash,
        proposed_at=fresh,
    )
    conn.commit()
    persist_proposal(
        RoleAccess(conn, Role.BRAIN),
        proposal,
        draft=DraftRecord(
            body_text=text,
            needs_user_input=False,
            validator_ok=True,
            model_id="fake-writer",
            prompt_version="v1",
            created_at=fresh,
        ),
    )
    binding = build_review_binding(
        conn,
        pid,
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=fresh,
        response="accept",
    )
    return proposal, binding, payload


def start_held(conn, world, context, fresh, suffix, sender=0):  # type: ignore[no-untyped-def]
    proposal, binding, payload = add_reply(conn, context, fresh, suffix, sender)
    clock = Clock.replay(parse_timestamp(fresh))
    world.add_message(
        f"current-{suffix}",
        payload["message_id"],
        payload["thread_id"],
        payload["from"],
        GRANT.from_addr,
        payload["subject"],
        payload["body"],
        ["INBOX"],
        fresh,
    )
    worker = Executor(conn, world, clock=clock, grant_resolver=lambda _: GRANT)
    assert worker._default_licence_checker(*PAIR, fresh) == 2
    action = worker.create_action(
        proposal.id,
        "mail",
        "REPLY",
        binding.params,
        2,
        False,
        proposal.gate,
        fresh,
        binding=binding,
    )
    assert action.hold_until == format_timestamp(parse_timestamp(fresh) + timedelta(minutes=10))
    return action, worker, proposal, binding


def hold_then_cancel(conn, world, context, fresh, suffix, before_cancel=None):  # type: ignore[no-untyped-def]
    action, worker, proposal, binding = start_held(conn, world, context, fresh, suffix)
    if before_cancel is not None:
        before_cancel()
    clock = worker.clock
    cancel_at = format_timestamp(parse_timestamp(fresh) + timedelta(minutes=9, seconds=59))
    clock.set_time(parse_timestamp(cancel_at))
    assert worker.process_queue() == []
    ResponseStore(RoleAccess(conn, Role.API)).submit(
        ResponseIntent(
            request_id=f"cancel-{suffix}",
            proposal_id=proposal.id,
            response="undo",
            action_id=action.id,
            owner_id="owner",
            responded_at=cancel_at,
            reviewed_payload=binding,
            reviewed_payload_hash=binding_hash(binding),
        )
    )
    assert worker.process_responses() == 1
    result = worker.process_queue()
    assert result and result[0].success
    assert (
        conn.execute("SELECT status FROM actions WHERE id=?", (action.id,)).fetchone()[0]
        == "CANCELLED"
    )
    assert (
        world.conn.execute("SELECT count(*) FROM messages WHERE labels LIKE '%SENT%'").fetchone()[0]
        == 0
    )
    assert derive_licences(conn, cancel_at)[PAIR].n_strong == 120
    return cancel_at, worker


def test_actual_exam_hold_corrections_across_restart_and_real_reexamination(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "engine.db")
    apply_schema(conn)
    _populate_test_situations(conn, count=120)
    cutoff = "2026-07-01T00:00:00Z"
    assert review_outcome_events(conn, as_of=cutoff) == 120
    assert (
        conn.execute("SELECT count(*) FROM drift_state WHERE last_alarm_at IS NOT NULL").fetchone()[
            0
        ]
        == 0
    )
    policy = Policy("email_action")
    assert policy.cold_start_min == 200
    policy.fit(
        [{"has_deadline": False}] * 1000 + [{"has_deadline": True}] * 1000,
        ["REPLY"] * 1000 + ["LEAVE"] * 1000,
        ["2026-01-01T00:00:00Z"] * 2000,
        as_of=cutoff,
    )
    context = context_for(conn, policy)
    before = derive_licences(conn, cutoff)[PAIR]
    assert int(before.level) == 1 and before.n_strong == 120
    exam = run_exam(conn, *PAIR, level_tested=2, as_of=cutoff, seed=706, prediction_context=context)
    assert exam.passed and exam.critical_violations == 0
    permitted = derive_licences(conn, cutoff)[PAIR]
    assert int(permitted.level) == 2 and permitted.exam_run_id == exam.run_id
    assert permitted.lb_strong >= settings.l2_min_lb
    with SimWorld(tmp_path / "world.db", user_addresses=[GRANT.from_addr]) as world:
        first_at, first_worker = hold_then_cancel(conn, world, context, "2026-07-01T00:00:01Z", "")
        assert first_worker._default_licence_checker(*PAIR, first_at) == 0
        assert review_outcome_events(conn, as_of=first_at) == 1
        assert first_worker._default_licence_checker(*PAIR, first_at) == 2
        assert (
            conn.execute(
                "SELECT last_alarm_at FROM drift_state WHERE class_key=? AND action=?", PAIR
            ).fetchone()[0]
            is None
        )
        assert verify_ledger(conn) == (True, None)
    conn.close()
    # A fresh connection/worker cannot forget the first consumed correction.
    conn = get_connection(tmp_path / "engine.db")
    context = ExamPredictionContext(
        context.snapshot,
        HistoryView(conn, "2026-07-01T00:10:02Z"),
        fixture_editor(),
        controlled_reader,
    )
    with SimWorld(tmp_path / "world.db", user_addresses=[GRANT.from_addr]) as world:
        pending = []

        def queue_before_alarm():
            third = start_held(conn, world, context, "2026-07-01T00:10:03Z", "-three", sender=1)
            original = tuple(
                conn.execute("SELECT * FROM proposals WHERE id=?", (third[2].id,)).fetchone()
            )
            pending.append((third, original))

        second_at, second_worker = hold_then_cancel(
            conn, world, context, "2026-07-01T00:10:02Z", "-two", queue_before_alarm
        )
        assert review_outcome_events(conn, as_of=second_at) == 1
        assert review_outcome_events(conn, as_of=second_at) == 0
        assert second_worker._default_licence_checker(*PAIR, second_at) < 2
        blocked = derive_licences(conn, second_at)[PAIR]
        assert int(blocked.level) == 1 and blocked.n_strong == 120
        assert (
            conn.execute("SELECT count(*) FROM outcome_events WHERE kind='cancel'").fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT last_alarm_at FROM drift_state WHERE class_key=? AND action=?", PAIR
            ).fetchone()[0]
            == second_at
        )
        (third_action, third_worker, third_proposal, _), original = pending[0]
        due = third_action.hold_until
        third_worker.clock.set_time(parse_timestamp(due))
        cancelled = third_worker.process_queue()
        assert cancelled and not cancelled[0].success and cancelled[0].error == "licence_lost"
        assert (
            conn.execute("SELECT status FROM actions WHERE id=?", (third_action.id,)).fetchone()[0]
            == "CANCELLED"
        )
        linked = process_followups(
            conn,
            as_of=due,
            snapshots={"email_action": context.snapshot},
            reader_callable=controlled_reader,
        )
        assert len(linked) == 1
        followup = conn.execute("SELECT * FROM proposals WHERE id=?", (linked[0],)).fetchone()
        assert followup["followup_of_action_id"] == third_action.id
        assert (
            followup["gate"] in {"SUGGEST", "ASK", "SHADOW"}
            and followup["licence_level"] <= 1
            and followup["cap"] <= 1
        )
        assert json.loads(followup["explanation_json"])["original_proposal_id"] == third_proposal.id
        assert (
            tuple(
                conn.execute("SELECT * FROM proposals WHERE id=?", (third_proposal.id,)).fetchone()
            )
            == original
        )
        assert (
            process_followups(
                conn,
                as_of=due,
                snapshots={"email_action": context.snapshot},
                reader_callable=controlled_reader,
            )
            == []
        )
        after = format_timestamp(parse_timestamp(due) + timedelta(seconds=1))
        refreshed_context = ExamPredictionContext(
            context.snapshot, HistoryView(conn, after), fixture_editor(), controlled_reader
        )
        reexam = run_exam(
            conn, *PAIR, level_tested=2, as_of=after, seed=707, prediction_context=refreshed_context
        )
        assert reexam.passed and reexam.critical_violations == 0
        restored = derive_licences(conn, after)[PAIR]
        assert int(restored.level) == 2 and restored.exam_run_id == reexam.run_id
        assert restored.n_strong == restored.k_strong == 120
        assert (
            world.conn.execute(
                "SELECT count(*) FROM messages WHERE labels LIKE '%SENT%'"
            ).fetchone()[0]
            == 0
        )
        assert verify_ledger(conn) == (True, None)
    conn.close()
