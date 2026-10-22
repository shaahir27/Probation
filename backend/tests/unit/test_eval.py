"""Unit and acceptance tests for Phase 10: Evaluation & Benchmarks (T-EVAL).

Authority: docs/TEST_PLAN.md T-EVAL, docs/EVALUATION_PLAN.md sections 3, 4, 5, 6, 7.
Tests metric functions against hand-computed golden fixtures matching to 1e-9.
Tests Baselines B0, B1, B2, B3, human study harness, and evaluation runner orchestration.
"""

import sqlite3
from pathlib import Path

import pytest

from probation.core.enums import Gate
from probation.core.types import Situation
from probation.engine.replay import run_replay
from probation.eval.baselines import (
    AskAlwaysBaseline,
    GenericRulesBaseline,
    LLMConfidenceBaseline,
    MajorityBaseline,
)
from probation.eval.human_study import (
    generate_human_study_items,
    run_human_study_simulation,
)
from probation.eval.metrics import (
    compute_agreement,
    compute_autonomous_coverage,
    compute_autonomous_error_rate,
    compute_calibration,
    compute_chain_metrics,
    compute_drift_metrics,
    compute_harm_weighted_error,
    compute_interruptions,
    compute_precision,
)
from probation.eval.run_eval import (
    export_evaluation_results,
    run_evaluation,
)


def make_situation(
    situation_id: str = "sit-1",
    family: str = "email_action",
    redacted_text: str = "",
) -> Situation:
    """Helper to construct minimal Situation for evaluation testing."""
    return Situation(
        id=situation_id,
        pack="",
        family=family,
        raw_item_id="",
        occurred_at="2026-10-01T10:00:00Z",
        sender_key="",
        content_hash="",
        redacted_text=redacted_text,
        hands_off_reason=None,
        variant="",
        created_at="",
    )


def test_t_eval_precision_hand_computed() -> None:
    """T-EVAL: Test precision k/n against hand-computed fixture."""
    assert compute_precision(7, 10) == pytest.approx(0.70, abs=1e-9)
    assert compute_precision(0, 10) == pytest.approx(0.0, abs=1e-9)
    assert compute_precision(10, 10) == pytest.approx(1.0, abs=1e-9)
    assert compute_precision(5, 0) == pytest.approx(0.0, abs=1e-9)
    assert compute_precision(-1, -5) == pytest.approx(0.0, abs=1e-9)


def test_t_eval_agreement_hand_computed() -> None:
    """T-EVAL: Test agreement with and without abstentions against hand-computed fixture."""
    predictions = ["REPLY", "ARCHIVE", "ABSTAIN", "ACCEPT"]
    ground_truth = ["REPLY", "LEAVE", "ARCHIVE", "ACCEPT"]

    res = compute_agreement(predictions, ground_truth, abstention_token="ABSTAIN")

    # Non-abstained: 3 items ("REPLY", "ARCHIVE", "ACCEPT")
    # Matches non-abstained: "REPLY"=="REPLY", "ACCEPT"=="ACCEPT" -> 2
    # Non-abstained rate: 2/3 = 0.6666666666666666
    assert res.total == 4
    assert res.non_abstained == 3
    assert res.agreement_non_abstained == pytest.approx(2.0 / 3.0, abs=1e-9)

    # All items: 4 items, 2 matches -> 2/4 = 0.50
    assert res.agreement_all == pytest.approx(0.50, abs=1e-9)


def test_t_eval_agreement_empty_and_mismatched() -> None:
    """T-EVAL: Test agreement edge cases."""
    res_empty = compute_agreement([], [])
    assert res_empty.agreement_all == 0.0
    assert res_empty.total == 0

    res_mismatch = compute_agreement(["A"], ["A", "B"])
    assert res_mismatch.agreement_all == 0.0


def test_t_eval_autonomous_error_rate_hand_computed() -> None:
    """T-EVAL: Test autonomous error rate against hand-computed fixture."""
    auto_actions = ["REPLY", "ARCHIVE", "MOVE_TO_FOLDER", "ACCEPT", "LEAVE"]
    true_actions = ["REPLY", "ARCHIVE", "TRASH", "ACCEPT", "DECLINE"]

    # 5 actions, 2 mismatches ("MOVE_TO_FOLDER"!="TRASH", "LEAVE"!="DECLINE")
    # Error rate: 2 / 5 = 0.40
    err = compute_autonomous_error_rate(auto_actions, true_actions)
    assert err == pytest.approx(0.40, abs=1e-9)

    assert compute_autonomous_error_rate([], []) == 0.0


def test_t_eval_harm_weighted_error_hand_computed() -> None:
    """T-EVAL: Test harm-weighted error with explicit loss values against hand-computed fixture."""
    auto_actions = ["ARCHIVE", "REPLY"]
    true_actions = ["ARCHIVE", "LEAVE"]
    losses = {"ARCHIVE": 5.0, "REPLY": 40.0, "LEAVE": 1.0}

    # Total loss: loss("ARCHIVE") + loss("REPLY") = 5.0 + 40.0 = 45.0
    # Error loss: "REPLY" != "LEAVE" -> 40.0
    # Harm-weighted error: 40.0 / 45.0 = 8 / 9 = 0.8888888888888888
    harm_err = compute_harm_weighted_error(auto_actions, true_actions, losses=losses)
    assert harm_err == pytest.approx(40.0 / 45.0, abs=1e-9)


def test_t_eval_autonomous_coverage_hand_computed() -> None:
    """T-EVAL: Test autonomous coverage against hand-computed fixture."""
    # 15 non-noop correctly handled out of 20 non-noop situations
    cov = compute_autonomous_coverage(auto_correct_count=15, non_noop_count=20)
    assert cov == pytest.approx(0.75, abs=1e-9)
    assert compute_autonomous_coverage(0, 0) == 0.0


def test_t_eval_interruptions_hand_computed() -> None:
    """T-EVAL: Test attention units formula: 100 * (asks + 0.3 * suggestions) / N."""
    asks = 10
    suggestions = 20
    total = 100

    metrics = compute_interruptions(
        asks=asks, suggestions=suggestions, total_situations=total, suggestion_weight=0.3
    )
    assert metrics.asks_per_100 == pytest.approx(10.0, abs=1e-9)
    assert metrics.suggestions_per_100 == pytest.approx(20.0, abs=1e-9)
    # 10 + 0.3 * 20 = 16.0
    assert metrics.attention_units_per_100 == pytest.approx(16.0, abs=1e-9)

    empty_metrics = compute_interruptions(0, 0, 0)
    assert empty_metrics.attention_units_per_100 == 0.0


def test_t_eval_calibration_ece_and_brier_hand_computed() -> None:
    """T-EVAL: Test ECE and Brier score over 10 equal-width bins matching to 1e-9."""
    confidences = [0.15, 0.15, 0.85, 0.95]
    matches = [True, False, True, True]

    cal = compute_calibration(confidences, matches, num_bins=10)

    assert cal.ece == pytest.approx(0.225, abs=1e-9)
    assert cal.brier == pytest.approx(0.1925, abs=1e-9)
    assert cal.bin_counts[1] == 2
    assert cal.bin_counts[8] == 1
    assert cal.bin_counts[9] == 1
    assert cal.bin_accuracies[1] == pytest.approx(0.50, abs=1e-9)
    assert cal.bin_confidences[1] == pytest.approx(0.15, abs=1e-9)


def test_t_eval_drift_metrics_hand_computed() -> None:
    """T-EVAL: Test drift detection delay and pre-drift false alarms."""
    alarms = [
        {"day": 50, "situation_idx": 500},
        {"day": 110, "situation_idx": 1100},
        {"day": 125, "situation_idx": 1250},
        {"day": 130, "situation_idx": 1300},
    ]

    drift = compute_drift_metrics(
        alarms=alarms,
        drift_day=120,
        drift_situation_idx=1200,
        pre_drift_window_days=60,
    )

    assert drift.detected is True
    assert drift.detection_delay_days == 5
    assert drift.detection_delay_situations == 50
    assert drift.false_alarms_pre_drift == 1


def test_t_eval_chain_metrics_hand_computed() -> None:
    """T-EVAL: Test precision and recall on mined vs planted chains."""
    planted = [
        {
            "trigger": {"family": "email_action", "intent": "request"},
            "follow": [{"action": "REPLY"}],
        },
        {
            "trigger": {"family": "email_action", "intent": "deadline"},
            "follow": [{"action": "BLOCK_TIME"}],
        },
    ]

    mined = [
        {
            "trigger": {"family": "email_action", "intent": "request"},
            "follow": [{"action": "REPLY"}],
        },
        {
            "trigger": {"family": "file_destination", "intent": "download"},
            "follow": [{"action": "MOVE_TO_FOLDER"}],
        },
    ]

    res = compute_chain_metrics(mined_chains=mined, planted_chains=planted)
    assert res.matched_count == 1
    assert res.mined_count == 2
    assert res.planted_count == 2
    assert res.precision == pytest.approx(0.50, abs=1e-9)
    assert res.recall == pytest.approx(0.50, abs=1e-9)


def test_baselines_b0_majority() -> None:
    """Test Baseline B0 (Majority class)."""
    b0 = MajorityBaseline()
    sit = make_situation(family="email_action")
    # Cold start
    assert b0.predict(sit).action == "REPLY"

    # Feed history
    b0.update("email_action", "ARCHIVE")
    b0.update("email_action", "ARCHIVE")
    b0.update("email_action", "REPLY")
    assert b0.predict(sit).action == "ARCHIVE"


def test_baselines_b1_ask_always() -> None:
    """Test Baseline B1 (Ask always)."""
    b1 = AskAlwaysBaseline()
    sit = make_situation(family="email_action")
    pred = b1.predict(sit)
    assert pred.gate == Gate.ASK
    assert pred.is_autonomous is False
    assert pred.action == "REPLY"


def test_baselines_b2_generic_rules() -> None:
    """Test Baseline B2 (Generic heuristics)."""
    b2 = GenericRulesBaseline()

    # Mail newsletter -> auto ARCHIVE
    sit_news = make_situation(family="email_action", redacted_text="Weekly newsletter")
    res_news = b2.predict(sit_news, payload={"intent": "newsletter"})
    assert res_news.action == "ARCHIVE"
    assert res_news.gate in {Gate.EXECUTE_UNDO, Gate.HOLD_THEN_EXECUTE}
    assert res_news.is_autonomous is True

    # Mail personal request -> ASK
    sit_req = make_situation(family="email_action", redacted_text="Can you review this?")
    res_req = b2.predict(sit_req, payload={"intent": "request", "looks_automated": False})
    assert res_req.action == "REPLY"
    assert res_req.gate == Gate.ASK
    assert res_req.is_autonomous is False

    # Calendar always ASK
    sit_cal = make_situation(family="invite_rsvp")
    res_cal = b2.predict(sit_cal)
    assert res_cal.gate == Gate.ASK
    assert res_cal.is_autonomous is False


def test_baselines_b3_llm_confidence_sweeps() -> None:
    """Test Baseline B3 threshold sweep over tau."""
    sit = make_situation(situation_id="test-1", family="email_action", redacted_text="Team meeting")
    cached = {"test-1": ("REPLY", 0.85)}

    b3_low = LLMConfidenceBaseline(tau=0.70, cached_predictions=cached)
    res_low = b3_low.predict(sit)
    assert res_low.action == "REPLY"
    assert res_low.confidence == 0.85
    assert res_low.is_autonomous is True
    assert res_low.gate == Gate.EXECUTE_UNDO

    b3_high = LLMConfidenceBaseline(tau=0.90, cached_predictions=cached)
    res_high = b3_high.predict(sit)
    assert res_high.action == "REPLY"
    assert res_high.confidence == 0.85
    assert res_high.is_autonomous is False
    assert res_high.gate == Gate.ASK


def test_human_study_simulation() -> None:
    """Test human study pool generation and participant learning curve."""
    items = generate_human_study_items(seed=42)
    assert len(items) == 150

    results = run_human_study_simulation(seed=42, n_participants=3)
    assert len(results["participants"]) == 3
    assert len(results["learning_curve"]) == 150
    assert results["mean_final_agreement"] > 0.0


def test_run_eval_orchestrator(
    tmp_path: Path, memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    """Test full evaluation runner orchestration and export."""
    run_replay(memory_db)
    engine_path = tmp_path / "engine.db"
    with sqlite3.connect(engine_path) as target:
        memory_db.backup(target)
    res = run_evaluation(db_path=engine_path, suite="fast", seed=7)
    assert "metadata" in res
    assert res["metadata"]["total_situations"] == 1
    assert (
        memory_db.execute("SELECT situation_id FROM proposals").fetchone()[0] == basic_situation.id
    )
    assert "main_comparison" in res
    assert "ablations" in res
    assert "resource_efficiency" in res

    j_out = tmp_path / "test_main.json"
    m_out = tmp_path / "test_tables.md"
    export_evaluation_results(res, json_path=j_out, markdown_path=m_out)

    assert j_out.exists()
    assert m_out.exists()

    md_content = m_out.read_text(encoding="utf-8")
    assert "# Probation Benchmark Evaluation Results" in md_content
    assert "Probation (Ours)" in md_content
    assert "B0 (Majority Class)" in md_content
