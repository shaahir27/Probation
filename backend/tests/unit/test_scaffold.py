"""Unit test verifying Phase 0 scaffold integrity and core invariant baseline functions.

Authority: docs/TEST_PLAN.md section 2 and docs/IMPLEMENTATION_PLAN.md Phase 0.
"""

import sqlite3
from datetime import UTC, datetime

import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode, GateDecision
from probation.core.hashing import canonical_json, det_id
from probation.db.ledger import append_ledger, verify_ledger
from probation.engine.gate import evaluate_gate
from probation.engine.handsoff import is_hands_off
from probation.llm.redact import redact
from probation.web.query_guard import validate_tavily_query


def test_clock_monotonic_and_settable() -> None:
    """T-CLOCK: Replay clock is monotonic and settable; cannot move backwards."""
    clock = Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    assert clock.now_iso() == "2026-01-01T00:00:00Z"

    clock.advance_seconds(3600)
    assert clock.now_iso() == "2026-01-01T01:00:00Z"

    # Moving backwards must raise ValueError
    earlier = datetime(2025, 12, 31, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        clock.set_time(earlier)


def test_det_id_deterministic() -> None:
    """T-ID: Deterministic ID generation matches across identical inputs."""
    id1 = det_id("mail", "msg_123", "situation")
    id2 = det_id("mail", "msg_123", "situation")
    assert id1 == id2
    assert len(id1) == 64


def test_canonical_json_key_invariance() -> None:
    """T-LEDGER: Canonical JSON is invariant to key order."""
    dict_a = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
    dict_b = {"a": 2, "z": 1, "m": {"a": 4, "b": 3}}
    assert canonical_json(dict_a) == canonical_json(dict_b)
    assert " " not in canonical_json(dict_a)


def test_schema_initialization_and_ledger_integrity(memory_db: sqlite3.Connection) -> None:
    """T-LEDGER: Database schema applies and append/verify works on hash chain."""
    # Verify tables created
    cursor = memory_db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    expected_tables = {
        "meta",
        "sources",
        "raw_items",
        "situations",
        "features",
        "llm_cache",
        "proposals",
        "outcomes",
        "drafts",
        "actions",
        "user_responses",
        "class_stats",
        "licence_cache",
        "exam_runs",
        "exam_cases",
        "drift_state",
        "family_shift",
        "habits",
        "chains",
        "ledger",
        "exposure_log",
        "web_facts",
        "tavily_calls",
        "extractions",
        "quarantine_outputs",
        "clock_state",
    }
    assert expected_tables.issubset(tables)

    # Test ledger append and verify
    seq1 = append_ledger(
        memory_db,
        kind="proposal",
        ref_id="prop_01",
        payload={"action": "TRASH"},
        created_at="2026-01-01T00:00:00Z",
    )
    assert seq1 == 1

    seq2 = append_ledger(
        memory_db,
        kind="outcome",
        ref_id="out_01",
        payload={"action": "TRASH"},
        created_at="2026-01-01T00:01:00Z",
    )
    assert seq2 == 2

    intact, corrupted_seq = verify_ledger(memory_db)
    assert intact is True
    assert corrupted_seq is None


def test_hands_off_safety() -> None:
    """T-HANDSOFF: Hands-off extension, double extensions, and RLO characters are blocked."""
    assert is_hands_off(filename="invoice.pdf") is None
    assert is_hands_off(filename="malware.exe") is not None
    assert is_hands_off(filename="document.pdf.exe") is not None
    assert is_hands_off(filename="report\u202epdf.exe") is not None


def test_pure_gate_fail_closed() -> None:
    """T-GATE: Pure gate fails closed on budget exhaustion, reader failure, or hands-off."""
    # Budget exhausted -> ASK
    decision = evaluate_gate(
        budget_ok=False,
        reader_ok=True,
        deterministic_ok=True,
        hands_off_reason=None,
        licence_level=3,
        cap=3,
        novel=False,
        p_max=0.99,
    )
    assert decision == GateDecision.ASK

    # Reader failed -> ASK
    decision = evaluate_gate(
        budget_ok=True,
        reader_ok=False,
        deterministic_ok=True,
        hands_off_reason=None,
        licence_level=3,
        cap=3,
        novel=False,
        p_max=0.99,
    )
    assert decision == GateDecision.ASK

    # Hands-off reason -> SHADOW
    decision = evaluate_gate(
        budget_ok=True,
        reader_ok=True,
        deterministic_ok=True,
        hands_off_reason="Blocked executable extension: .exe",
        licence_level=3,
        cap=3,
        novel=False,
        p_max=0.99,
    )
    assert decision == GateDecision.SHADOW


def test_redact_pipeline() -> None:
    """T-REDACT: Redaction replaces emails and phones with local numbered tags."""
    text = "Contact Alice at alice@example.com or call +1 555-123-4567."
    redacted, restore_map, counts = redact(text)

    assert "<EMAIL_1>" in redacted
    assert "<PHONE_1>" in redacted
    assert "alice@example.com" not in redacted
    assert restore_map["<EMAIL_1>"] == "alice@example.com"
    assert counts["email"] == 1
    assert counts["phone"] == 1


def test_query_guard_rules() -> None:
    """T-WEBQ: Query guard rejects dangerous and private patterns."""
    ok, reason = validate_tavily_query("Acme Corporation official website")
    assert ok is True
    assert reason is None

    # Rejects email-like query
    ok, reason = validate_tavily_query("info@example.com domain")
    assert ok is False

    # Rejects URLs
    ok, reason = validate_tavily_query("https://phishing.site review")
    assert ok is False

    # Rejects long digit runs
    ok, reason = validate_tavily_query("Order 123456789 tracking")
    assert ok is False
