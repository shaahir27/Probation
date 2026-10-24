"""Frozen prospective synthetic scenario through the real shared WP3/WP4 pipeline."""

import json
from datetime import timedelta

from probation.core.clock import format_timestamp, parse_timestamp
from probation.core.enums import EvidenceStrength, GateDecision
from probation.core.history import HistoryView
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.connection import apply_schema, get_connection
from probation.db.ledger import verify_ledger
from probation.db.proposals import persist_proposal
from probation.engine.evidence import aggregate_evidence
from probation.engine.exam import run_exam
from probation.engine.exam_prediction import ExamPredictionContext
from probation.engine.licence import derive_licences
from probation.engine.novelty import NoveltyDetector
from probation.engine.policy import Policy
from probation.engine.prediction import PredictionSnapshot, evaluate_prediction
from probation.engine.training import build_cohort, fit_cohort
from probation.llm.feature_pipeline import compute_features, semantic_feature_version
from probation.packs.registry import registry
from tests.stubs.embeddings import RecordedEmbeddings
from tests.unit.test_exam_board import fixture_editor

PAIR = ("mail|fyi|frequent", "ARCHIVE")


class SemanticFixtureEmbeddings:
    """Small fake semantic provider; no claim of MiniLM or language quality."""

    identity = "d2-public-synthetic-semantic-fixture-v1"

    def embed(self, texts):
        import numpy as np

        return np.asarray(
            [
                [1.0, 0.0, 0.0]
                if "Monthly update" in text
                else [0.0, 1.0, 0.0]
                if "project planning question" in text
                else [0.0, 0.0, 1.0]
                for text in texts
            ]
        )


def scenario_reader(situation):
    text = situation.redacted_text or ""
    return {
        "intent": "fyi" if "Monthly update" in text else "request",
        "asks_me_to_do_something": "Monthly update" not in text,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": "$250" in text,
        "urgency": 1,
        "formality": "casual" if text.startswith("Hi Meena,") else "formal",
        "asks_for_personal_info": "OTP" in text,
        "looks_automated": False,
    }, True


def prospective_scenario(*, semantic_embeddings=True):
    conn = get_connection(":memory:")
    apply_schema(conn)
    start = parse_timestamp("2026-05-01T00:00:00Z")
    conn.execute(
        "INSERT INTO sources VALUES ('scenario','mail','synthetic','d2-scenario-v1',?)",
        (format_timestamp(start),),
    )
    policy = Policy("email_action")  # production cold-start 200, never overridden
    novelty = NoveltyDetector(
        embedder=SemanticFixtureEmbeddings() if semantic_embeddings else RecordedEmbeddings()
    )
    for i in range(340):
        t = format_timestamp(start + timedelta(hours=i))
        known = format_timestamp(start + timedelta(hours=i, seconds=1))
        sid = f"scenario-{i:03d}"
        archive = i % 4 != 0
        body = (
            "Hi Meena,\nMonthly update: team project progress is available for your records.\nBest regards,\nColleague"
            if archive
            else "Hi Meena,\nCould you please reply regarding the project planning question?\nBest regards,\nColleague"
        )
        payload = {"from": "colleague@college.example", "subject": "Project update", "body": body}
        conn.execute(
            "INSERT INTO raw_items VALUES (?,'scenario','mail','mail_in',?,?,?,?,'h')",
            (sid, sid, t, t, json.dumps(payload)),
        )
        conn.execute(
            """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,sender_key,
            content_hash,redacted_text,created_at) VALUES (?,?,'mail','email_action',?,?,'h',?,?)""",
            (sid, sid, t, payload["from"], body, t),
        )
        situation = Situation(
            id=sid,
            raw_item_id=sid,
            pack="mail",
            family="email_action",
            occurred_at=t,
            sender_key=payload["from"],
            content_hash="h",
            redacted_text=body,
            created_at=t,
        )
        history = HistoryView(conn, t)
        if i == 200:
            cohort = build_cohort(history, "email_action", semantic_feature_version(stub=True))
            assert len(cohort.rows) == 200
            fit_cohort(policy, cohort, t)
            novelty.fit(
                [row.redacted_text for row in cohort.rows],
                reference_ids=[row.situation_id for row in cohort.rows],
                family="email_action",
            )
            assert policy.is_fitted
        features = compute_features(situation, history, reader_callable=scenario_reader)
        conn.execute(
            """INSERT INTO features(situation_id,deterministic_json,reader_json,reader_ok,
          featurizer_version,features_hash,created_at,provenance_json) VALUES (?,?,?,1,?,?,?,?)""",
            (
                sid,
                json.dumps(features.deterministic),
                json.dumps(features.reader),
                features.featurizer_version,
                features.features_hash,
                t,
                features.provenance_json,
            ),
        )
        snapshot = PredictionSnapshot(policy, novelty, "probation-audit-v1", 0.1)
        prediction = evaluate_prediction(
            situation, features, registry.get_descriptor("mail"), snapshot, licence_level=0
        )
        assert prediction.gate == GateDecision.SHADOW
        proposal = Proposal(
            id=f"p-{sid}",
            situation_id=sid,
            family="email_action",
            class_key=prediction.class_key,
            action=prediction.action,
            probs=prediction.probs,
            p_max=prediction.p_max,
            novelty=prediction.novelty,
            novel=prediction.novel,
            licence_level=0,
            cap=prediction.cap,
            gate=prediction.gate,
            policy_version=policy.policy_version,
            features_hash=features.features_hash,
            proposed_at=t,
        )
        persist_proposal(RoleAccess(conn, Role.BRAIN), proposal)
        # The evaluator reveals the user's decision only after commitment, using
        # the existing Resolver-owned event contract, never a policy truth input.
        actual = "ARCHIVE" if archive else "REPLY"
        event = {
            "situation_id": sid,
            "observed_action": actual,
            "strength": EvidenceStrength.STRONG.value,
            "source": "user_response",
            "known_at": known,
        }
        seq = RoleAccess(conn, Role.RESOLVER).append_ledger("outcome", sid, event, created_at=known)
        conn.execute(
            "INSERT INTO outcomes VALUES (?,?,?,'user_response',?,?,'{}',?)",
            (sid, actual, "STRONG", known, known, seq),
        )
        conn.commit()
    cutoff = format_timestamp(start + timedelta(hours=341))
    stats = aggregate_evidence(conn, cutoff, persist=False)[PAIR]
    assert stats.n_strong == stats.k_strong == 105
    assert stats.lb_strong >= 0.95
    context = ExamPredictionContext(
        PredictionSnapshot(policy, novelty, "probation-audit-v1", 0.1),
        HistoryView(conn, cutoff),
        fixture_editor(),
        scenario_reader,
    )
    before = derive_licences(conn, cutoff)[PAIR]
    assert int(before.level) == 1  # numeric agreement alone cannot authorize
    exam = run_exam(conn, *PAIR, level_tested=2, as_of=cutoff, seed=705, prediction_context=context)
    if not semantic_embeddings:
        assert not exam.passed
        assert int(derive_licences(conn, cutoff)[PAIR].level) == 1
        return conn, exam, before
    assert exam.passed, exam.details
    view = derive_licences(conn, cutoff)[PAIR]
    assert int(view.level) == 2 and view.exam_run_id == exam.run_id
    assert verify_ledger(conn)[0]
    assert conn.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
    # A new alarm blocks the exact same strong cohort until a later passed exam.
    RoleAccess(conn, Role.EXAMINER).append_ledger(
        "drift_alarm",
        "scenario-alarm",
        {"class_key": PAIR[0], "action": PAIR[1], "kind": "cusum"},
        created_at=cutoff,
    )
    blocked = derive_licences(conn, cutoff)[PAIR]
    assert int(blocked.level) == 1
    return conn, exam, view


def test_qualifying_and_blocked_synthetic_replay_are_deterministic():
    first, exam, view = prospective_scenario()
    second, repeated, repeated_view = prospective_scenario()
    try:
        assert exam == repeated and view == repeated_view
        assert (
            first.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()[0]
            == second.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()[0]
        )
    finally:
        first.close()
        second.close()


def test_nonsemantic_embedding_control_does_not_earn_permission():
    conn, exam, view = prospective_scenario(semantic_embeddings=False)
    try:
        assert exam.invariance_flip_rate > 0.03
        assert int(view.level) == 1
    finally:
        conn.close()
