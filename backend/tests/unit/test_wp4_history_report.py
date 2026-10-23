"""Immutable historical projection and hand-counted report denominators."""

import json

import pytest

from probation.core.history import HistoryView
from probation.db.ledger import append_ledger
from probation.engine.report import summarize_proposals
from probation.engine.training import build_cohort


def event(db, sid, action, when, source="footprint", strength="STRONG"):
    append_ledger(
        db,
        "outcome",
        sid,
        {
            "situation_id": sid,
            "observed_action": action,
            "known_at": when,
            "source": source,
            "strength": strength,
        },
        when,
    )


def test_immutable_projection_survives_future_correction(memory_db, basic_situation):
    sid = basic_situation.id
    event(memory_db, sid, "ARCHIVE", "2026-01-02T00:00:00Z")
    event(memory_db, sid, "UNDO", "2026-01-04T00:00:00Z", "undo")
    earlier = HistoryView(memory_db, "2026-01-03T00:00:00Z").get_decision_projection()
    later = HistoryView(memory_db, "2026-01-05T00:00:00Z").get_decision_projection()
    assert earlier[sid]["observed_action"] == "ARCHIVE"
    assert not later[sid]["eligible"]
    assert HistoryView(memory_db, "2026-01-01T00:00:00Z").get_decision_projection() == {}


def test_cohort_deduplicates_and_filters_semantic_version(memory_db, basic_situation):
    sid = basic_situation.id
    memory_db.execute(
        """INSERT INTO features(situation_id,deterministic_json,reader_ok,
                       featurizer_version,features_hash,created_at) VALUES (?, ?, 1, 'v-test','hash',?)""",
        (sid, json.dumps({"x": 1}), basic_situation.occurred_at),
    )
    event(memory_db, sid, "ARCHIVE", "2026-01-02T00:00:00Z")
    hist = HistoryView(memory_db, "2026-01-03T00:00:00Z")
    assert len(build_cohort(hist, "email_action", "v-test").rows) == 1
    assert build_cohort(hist, "email_action", "other").excluded == {"incompatible_features": 1}
    event(memory_db, sid, "REPLY", "2026-01-02T12:00:00Z")
    assert not build_cohort(hist, "email_action", "v-test").rows


def test_aggregate_queries_use_known_immutable_decisions(memory_db, basic_situation):
    sid = basic_situation.id
    memory_db.execute("UPDATE situations SET sender_key='sender@example.test' WHERE id=?", (sid,))
    event(memory_db, sid, "REPLY", "2026-01-02T10:00:00Z")
    hist = HistoryView(memory_db, "2026-01-03T00:00:00Z")
    assert hist.sender_statistics("sender@example.test")["reply_hours"] == [24.0]
    assert hist.sender_statistics("sender@example.test", sid)["messages"] == 0
    event(memory_db, sid, "UNDO", "2026-01-04T00:00:00Z", "undo")
    assert hist.sender_statistics("sender@example.test")["replies"] == 1
    assert (
        HistoryView(memory_db, "2026-01-05T00:00:00Z").sender_statistics("sender@example.test")[
            "replies"
        ]
        == 0
    )


def test_fifty_seeded_future_mutations_preserve_bounded_training(memory_db, basic_situation):
    import random
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(260):
        when = (base + timedelta(hours=i)).isoformat()
        raw, sid = f"raw-{i}", f"situation-{i}"
        memory_db.execute(
            """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,
                          occurred_at,known_at,payload_json,content_hash)
                          VALUES (?,'wp1-source','mail','mail_in',?,?,?,'{}','hash')""",
            (raw, raw, when, when),
        )
        memory_db.execute(
            """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,
                          content_hash,created_at) VALUES (?,?,'mail','email_action',?,'hash',?)""",
            (sid, raw, when, when),
        )
        memory_db.execute(
            """INSERT INTO features(situation_id,deterministic_json,reader_ok,
                          featurizer_version,features_hash,created_at) VALUES (?, ?,1,'test','hash',?)""",
            (sid, json.dumps({"x": i % 2}), when),
        )
        event(memory_db, sid, "REPLY" if i % 2 else "ARCHIVE", when)
    cuts = random.Random(42).sample(range(200, 259), 50)
    from probation.engine.policy import Policy
    from probation.engine.training import fit_cohort

    for index in cuts:
        cutoff = (base + timedelta(hours=index)).isoformat()
        history = HistoryView(memory_db, cutoff)
        before = build_cohort(history, "email_action", "test")
        p = fit_cohort(Policy("email_action"), before, cutoff)
        memory_db.execute(
            "UPDATE features SET deterministic_json=? WHERE situation_id=?",
            (json.dumps({"x": index + 100}), f"situation-{index + 1}"),
        )
        after = build_cohort(history, "email_action", "test")
        assert before == after
        assert fit_cohort(Policy("email_action"), after, cutoff).policy_digest == p.policy_digest


def test_report_counts_abstention_and_pending_ask_independently():
    proposals = [
        {
            "situation_id": str(i),
            "family": "email_action",
            "class_key": "mail|test",
            "action": a,
            "gate": g,
        }
        for i, (a, g) in enumerate(
            [("ARCHIVE", "SUGGEST"), ("ABSTAIN", "SHADOW"), ("REPLY", "ASK"), ("REPLY", "ASK")]
        )
    ]
    decisions = {
        str(i): {"observed_action": "ARCHIVE", "strength": "STRONG", "eligible": True}
        for i in range(3)
    }
    report = summarize_proposals(proposals, decisions, {"0": "ARCHIVE"}, None)
    assert (report["same"], report["different"], report["would_ask"], report["unresolved"]) == (
        1,
        2,
        3,
        1,
    )
    assert report["agreement_all"] == {
        "numerator": 1,
        "denominator": 3,
        "rate": pytest.approx(1 / 3),
    }
    assert report["agreement_non_abstained"]["rate"] == 0.5
    assert report["coverage"]["rate"] == pytest.approx(2 / 3)
    assert report["baselines"]["b0"]["denominator"] == 1
    assert report["baselines"]["b0"]["missing"] == 2
    assert summarize_proposals([], {}, None, None)["accuracy"] is None


def test_calendar_conflict_ignores_future_final_status(memory_db, basic_situation):
    payload = json.dumps(
        {
            "organizer": "organizer@example.test",
            "my_status": "ACCEPTED",
            "start_time": "2026-01-10T10:00:00Z",
            "end_time": "2026-01-10T11:00:00Z",
        }
    )
    memory_db.execute(
        """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,
                      occurred_at,known_at,payload_json,content_hash)
                      VALUES ('calendar-raw','wp1-source','calendar','invite','uid',?,?,?,'hash')""",
        (basic_situation.occurred_at, basic_situation.occurred_at, payload),
    )
    memory_db.execute(
        """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,
                      sender_key,content_hash,created_at) VALUES
                      ('calendar-prior','calendar-raw','calendar','invite_rsvp',?,'organizer@example.test','hash',?)""",
        (basic_situation.occurred_at, basic_situation.occurred_at),
    )
    event(memory_db, "calendar-prior", "ACCEPT", "2026-01-04T00:00:00Z")
    for cutoff, expected in [("2026-01-03T00:00:00Z", 0), ("2026-01-05T00:00:00Z", 1)]:
        stats = HistoryView(memory_db, cutoff).calendar_statistics(
            "organizer@example.test",
            "current",
            "2026-01-10T10:30:00Z",
            "2026-01-10T11:30:00Z",
            "Asia/Kolkata",
        )
        assert stats["conflicts_count"] == expected
