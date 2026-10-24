"""D2 real shared-pipeline exams must cover every hazard and freeze history."""

import json

import pytest

from probation.config import settings
from probation.core.history import HistoryView
from probation.engine.exam import run_exam
from probation.engine.exam_prediction import ExamPredictionContext
from tests.unit.test_exam_board import SoundPolicy, _populate_test_situations, context_for


def test_missing_or_unknown_verdict_data_cannot_default_to_a_pass():
    from probation.engine.exam import evaluate_exam_run

    for case in [
        {"expectation": "invariant", "critical": False},
        {"expectation": "unknown", "critical": False, "violated": False},
    ]:
        result = evaluate_exam_run("mail|request|known", "REPLY", 2, [case] * 30)
        assert result["passed"] is False


def test_missing_critical_operator_coverage_cannot_pass(memory_db, monkeypatch):
    import probation.engine.exam as board

    _populate_test_situations(memory_db)
    original = board.validate_mail_operator_result
    monkeypatch.setattr(
        board,
        "validate_mail_operator_result",
        lambda op, *a, **kw: False if op == "add_money_request" else original(op, *a, **kw),
    )
    policy = SoundPolicy()
    result = run_exam(
        memory_db,
        "mail|request|known",
        "REPLY",
        as_of="2026-07-01T00:00:00Z",
        prediction_context=context_for(memory_db, policy),
    )
    assert not result.passed
    assert "add_money_request" in result.details["missing_operators"]


def test_model_fitted_after_history_cutoff_is_invalid(memory_db):
    _populate_test_situations(memory_db)
    policy = SoundPolicy()
    original = context_for(memory_db, policy)
    context = ExamPredictionContext(
        original.snapshot,
        HistoryView(memory_db, "2026-06-01T00:00:00Z"),
        reader_callable=original.reader_callable,
    )
    result = run_exam(
        memory_db,
        "mail|request|known",
        "REPLY",
        as_of="2026-06-01T00:00:00Z",
        prediction_context=context,
    )
    assert not result.passed
    assert result.details["reason"] == "invalid_snapshot"


def test_frozen_history_retains_original_raw_payload(memory_db):
    _populate_test_situations(memory_db)
    frozen = context_for(memory_db, SoundPolicy()).frozen()
    before = frozen.history.get_raw_item("raw-test-000")["payload_json"]
    memory_db.execute(
        "UPDATE raw_items SET payload_json=? WHERE id='raw-test-000'",
        (json.dumps({"body": "changed"}),),
    )
    assert frozen.history.get_raw_item("raw-test-000")["payload_json"] == before


def test_frozen_history_does_not_materialize_future_rows(memory_db):
    _populate_test_situations(memory_db)
    cut = "2026-03-01T00:00:00Z"
    frozen = HistoryView(memory_db, cut).frozen()
    assert (
        frozen._conn.execute(
            "SELECT count(*) FROM raw_items WHERE known_at COLLATE UTC_TIMESTAMP > ?", (cut,)
        ).fetchone()[0]
        == 0
    )
    assert not memory_db.in_transaction


def test_wal_history_snapshot_is_readonly_and_survives_source_changes(tmp_path):
    from probation.db.connection import apply_schema, get_connection
    from probation.db.guards import AccessError

    conn = get_connection(tmp_path / "wal.db")
    apply_schema(conn)
    _populate_test_situations(conn)
    frozen = context_for(conn, SoundPolicy()).frozen()
    before = frozen.history.get_raw_item("raw-test-000")["payload_json"]
    conn.execute("UPDATE raw_items SET payload_json='{}'")
    conn.commit()
    assert frozen.history.get_raw_item("raw-test-000")["payload_json"] == before
    with pytest.raises(AccessError):
        frozen.history._conn.execute("DELETE FROM raw_items")
    conn.close()


def test_missing_edit_provider_cannot_get_a_synthetic_success(memory_db):
    _populate_test_situations(memory_db)
    original = context_for(memory_db, SoundPolicy())
    context = ExamPredictionContext(
        original.snapshot, original.history, reader_callable=original.reader_callable
    )
    result = run_exam(
        memory_db,
        "mail|request|known",
        "REPLY",
        as_of="2026-07-01T00:00:00Z",
        prediction_context=context,
    )
    assert not result.passed
    assert "paraphrase_body" in result.details["missing_operators"]


@pytest.mark.parametrize("level", [0, 1, 4, True])
def test_invalid_candidate_level_rejected(memory_db, level):
    with pytest.raises(ValueError):
        run_exam(
            memory_db,
            "mail|request|known",
            "REPLY",
            level_tested=level,
            as_of="2026-07-01T00:00:00Z",
        )


def test_actual_base_and_operator_counts_and_versions_are_recorded(memory_db):
    _populate_test_situations(memory_db)
    policy = SoundPolicy()
    result = run_exam(
        memory_db,
        "mail|request|known",
        "REPLY",
        as_of="2026-07-01T00:00:00Z",
        prediction_context=context_for(memory_db, policy),
    )
    assert result.passed
    assert result.details["valid_base_cases"] >= settings.exam_min_valid_cases
    assert len(result.details["base_ids"]) == result.details["valid_base_cases"]
    assert len(result.details["operator_coverage"]) == 10
    assert all(value > 0 for value in result.details["operator_coverage"].values())
    assert result.details["policy_version"] == policy.policy_version
    assert result.details["history_cutoff"] == "2026-07-01T00:00:00Z"
