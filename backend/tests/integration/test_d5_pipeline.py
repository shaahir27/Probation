"""D5 ordering, cutoff and restriction conformance using synthetic observations."""

import json

from probation.core.clock import Clock, parse_timestamp
from probation.core.history import HistoryView
from probation.engine.prediction import PredictionSnapshot


def form(_):
    return {
        "intent": "request",
        "asks_me_to_do_something": True,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": False,
        "urgency": 1,
        "formality": "neutral",
        "asks_for_personal_info": False,
        "looks_automated": False,
    }, True


class Policy:
    policy_version = "synthetic-d5"

    def predict(self, fields):
        assert "page" not in fields and "web" not in fields
        return "ARCHIVE", 0.99, {"ARCHIVE": 0.99, "LEAVE": 0.01}, []


class Novelty:
    def score(self, text):
        assert "UNTRUSTED PAGE" not in text
        return False, 0.0


def test_reader_precedes_web_and_final_cutoff_includes_response(memory_db, basic_situation):
    from probation.workers.d5_verification import WebObservation, predict_verified_email

    clock = Clock.replay(parse_timestamp(basic_situation.occurred_at))
    observed = []

    def verify(situation, features, history):
        assert features.reader_ok
        observed.append(history.as_of)
        clock.set_time(parse_timestamp("2026-01-01T10:00:05Z"))
        return WebObservation(cap=1, entities=[{"status": "lookalike"}])

    result = predict_verified_email(
        memory_db,
        basic_situation,
        PredictionSnapshot(Policy(), Novelty(), "d5", 0),
        clock=clock,
        verify=verify,
        reader_callable=form,
        licence_level=3,
    )
    assert observed == [basic_situation.occurred_at]
    assert result.cutoff == "2026-01-01T10:00:05Z"
    assert json.loads(result.features.provenance_json)["cutoff"] == result.cutoff
    assert result.prediction.gate.value == "SUGGEST"
    assert result.prediction.probs == {"ARCHIVE": 0.99, "LEAVE": 0.01}


def test_failed_reader_never_dispatches_web(memory_db, basic_situation):
    from probation.workers.d5_verification import predict_verified_email

    def forbidden(*args):
        raise AssertionError("Web called after invalid reader")

    result = predict_verified_email(
        memory_db,
        basic_situation,
        PredictionSnapshot(Policy(), Novelty(), "d5", 0),
        clock=Clock.replay(parse_timestamp(basic_situation.occurred_at)),
        verify=forbidden,
        reader_callable=lambda _: ({"intent": "invalid"}, True),
        licence_level=3,
    )
    assert result.prediction.gate.value == "ASK"
    assert result.web.cap == 3


def test_web_failure_preserves_baseline(memory_db, basic_situation):
    from probation.workers.d5_verification import predict_verified_email

    def unavailable(*args):
        raise OSError("synthetic provider failure")

    result = predict_verified_email(
        memory_db,
        basic_situation,
        PredictionSnapshot(Policy(), Novelty(), "d5", 0),
        clock=Clock.replay(parse_timestamp(basic_situation.occurred_at)),
        verify=unavailable,
        reader_callable=form,
        licence_level=3,
    )
    assert result.prediction.gate.value == "EXECUTE_UNDO"
    assert result.web.cap == 3
    assert result.web.reasons == ("verification_unavailable",)


def test_feature_cutoff_records_actual_bounded_history(memory_db, basic_situation):
    from probation.llm.feature_pipeline import compute_features

    cutoff = "2026-01-02T10:00:00Z"
    features = compute_features(
        basic_situation, HistoryView(memory_db, cutoff), reader_callable=form
    )
    assert json.loads(features.provenance_json)["cutoff"] == cutoff


def test_changed_generation_features_cannot_execute_old_policy_snapshot(memory_db, basic_situation):
    from probation.workers.d5_verification import WebObservation, predict_verified_email

    policy = Policy()
    policy.provenance = {"semantic_versions": ["previous-generation-profile"]}
    result = predict_verified_email(
        memory_db,
        basic_situation,
        PredictionSnapshot(policy, Novelty(), "d5", 0),
        clock=Clock.replay(parse_timestamp(basic_situation.occurred_at)),
        verify=lambda *_: WebObservation(),
        reader_callable=form,
        licence_level=3,
    )
    assert result.prediction.gate.value == "ASK"
    assert "feature_identity_mismatch" in result.prediction.reasons


def test_verified_proposal_persists_caution_without_promoting_injected_licence(
    memory_db, basic_situation
):
    from probation.db.ledger import verify_ledger
    from probation.workers.d5_verification import (
        WebObservation,
        persist_verified_email,
        predict_verified_email,
    )

    clock = Clock.replay(parse_timestamp(basic_situation.occurred_at))
    snapshot = PredictionSnapshot(Policy(), Novelty(), "d5", 0)
    result = predict_verified_email(
        memory_db,
        basic_situation,
        snapshot,
        clock=clock,
        verify=lambda *_: WebObservation(
            cap=1,
            entities=[
                {
                    "status": "lookalike",
                    "web_cap": 1,
                    "sources": [
                        {
                            "title": "Official provenance",
                            "url": "https://nvidia.com/",
                        }
                    ],
                }
            ],
        ),
        reader_callable=form,
        licence_level=3,
    )
    proposal = persist_verified_email(memory_db, basic_situation, snapshot, result, clock=clock)
    assert proposal.licence_level == 0 and proposal.gate.value == "SHADOW"
    assert proposal.web["cap"] == 1
    assert proposal.web["sources"][0]["url"] == "https://nvidia.com/"
    assert memory_db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1
    assert verify_ledger(memory_db)[0]
