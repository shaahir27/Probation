"""WP1: compact, canonical new ledger payloads retain operational table details."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from probation.core.types import Outcome, Situation
from probation.engine.drift import check_family_shift
from probation.workers.resolver import resolve_outcomes


def test_resolver_keeps_details_out_of_ledger(
    memory_db: sqlite3.Connection, basic_situation: Situation, monkeypatch: pytest.MonkeyPatch
) -> None:
    import probation.workers.resolver as resolver

    outcome = Outcome(
        situation_id=basic_situation.id,
        observed_action="ARCHIVE",
        observed_at="2026-01-02T10:00:00Z",
        known_at="2026-01-02T10:00:00Z",
        details={"synthetic_internal_detail": "retained only in outcome storage"},
    )
    monkeypatch.setattr(resolver, "resolve_mail_outcome", lambda *args, **kwargs: outcome)
    world = SimpleNamespace(get_messages=lambda: [])
    assert (
        resolve_outcomes(memory_db, world, as_of=outcome.known_at, user_addresses="me@example.test")
        == 1
    )
    payload = json.loads(memory_db.execute("SELECT payload_json FROM ledger").fetchone()[0])
    assert set(payload) == {"situation_id", "observed_action", "strength", "source", "known_at"}
    assert (
        json.loads(memory_db.execute("SELECT details_json FROM outcomes").fetchone()[0])
        == outcome.details
    )


def test_family_shift_records_distinct_canonical_alarm(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    for index in range(30):
        timestamp = "2026-01-01T10:00:00Z" if index < 20 else "2026-03-15T10:00:00Z"
        situation = f"shift-{index}"
        raw_id = f"shift-raw-{index}"
        memory_db.execute(
            """INSERT INTO raw_items(id, source_id, pack, item_kind, source_ref, occurred_at,
               known_at, payload_json, content_hash)
               VALUES (?, 'wp1-source', 'mail', 'mail_in', ?, ?, ?, '{}', 'synthetic-shift')""",
            (raw_id, raw_id, timestamp, timestamp),
        )
        memory_db.execute(
            """INSERT INTO situations(id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
               VALUES (?, ?, 'mail', 'email_action', ?, 'synthetic-shift', ?)""",
            (situation, raw_id, timestamp, timestamp),
        )
        memory_db.execute(
            """INSERT INTO features(situation_id, deterministic_json, reader_ok,
               featurizer_version, features_hash, created_at) VALUES (?, ?, 1, 'wp1', 'shift', ?)""",
            (situation, json.dumps({"sender_tier": "known" if index < 20 else "new"}), timestamp),
        )
    assert check_family_shift(memory_db, "email_action", "2026-04-01T00:00:00Z")
    payload = json.loads(memory_db.execute("SELECT payload_json FROM ledger").fetchone()[0])
    assert payload["kind"] == "family_shift"
    assert payload["family"] == "email_action"
    assert payload["max_psi"] > 0.25
    assert "alarm_type" not in payload
