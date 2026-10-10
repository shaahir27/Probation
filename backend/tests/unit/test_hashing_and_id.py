"""Unit tests for deterministic IDs, canonical JSON, and ledger hashing.

Authority: docs/TEST_PLAN.md (T-ID, T-LEDGER) and docs/DATA_MODEL.md sections 2, 4.
"""

from datetime import UTC, datetime

from probation.core.hashing import GENESIS, canonical_json, det_id, ledger_hash


def test_t_id_deterministic_and_length() -> None:
    """T-ID: det_id produces deterministic 32-character hex digests."""
    id1 = det_id("mail", "message-id-12345", "situation")
    id2 = det_id("mail", "message-id-12345", "situation")
    id3 = det_id("mail", "message-id-67890", "situation")

    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 32
    assert all(c in "0123456789abcdef" for c in id1)


def test_t_id_multiple_components() -> None:
    """T-ID: Handles multiple components correctly with unit separator."""
    id_a = det_id("source", "ref", "2026-01-01T00:00:00Z", "family", "")
    id_b = det_id("source", "ref", "2026-01-01T00:00:00Z", "family", "")
    assert id_a == id_b
    assert len(id_a) == 32


def test_t_ledger_canonical_json_key_invariance() -> None:
    """T-LEDGER: Canonical JSON is invariant to dictionary key order."""
    dict1 = {"b": 2, "a": 1, "nested": {"y": 20, "x": 10}}
    dict2 = {"nested": {"x": 10, "y": 20}, "a": 1, "b": 2}
    assert canonical_json(dict1) == canonical_json(dict2)
    assert canonical_json(dict1) == '{"a":1,"b":2,"nested":{"x":10,"y":20}}'


def test_t_ledger_canonical_json_float_rounding() -> None:
    """T-LEDGER: Canonical JSON rounds floats to 6 decimal places."""
    dict1 = {"p": 0.123456789, "q": 0.987654321}
    dict2 = {"p": 0.123457, "q": 0.987654}
    assert canonical_json(dict1) == canonical_json(dict2)


def test_t_ledger_canonical_json_datetime_formatting() -> None:
    """T-LEDGER: Canonical JSON formats datetimes as ISO-8601 UTC 'Z'."""
    dt = datetime(2026, 3, 14, 9, 30, 0, tzinfo=UTC)
    res = canonical_json({"time": dt})
    assert res == '{"time":"2026-03-14T09:30:00Z"}'


def test_t_ledger_hash_material_structure() -> None:
    """T-LEDGER: Ledger hash computes sha256 of prev_hash, kind, ref_id, and canonical payload."""
    prev = GENESIS
    kind = "proposal"
    ref_id = "prop_123"
    payload = {"action": "ARCHIVE", "p_max": 0.95}

    h1 = ledger_hash(prev, kind, ref_id, payload)
    h2 = ledger_hash(prev, kind, ref_id, payload)

    assert h1 == h2
    assert len(h1) == 64

    # Differentiates changes in payload
    h3 = ledger_hash(prev, kind, ref_id, {"action": "TRASH", "p_max": 0.95})
    assert h1 != h3
