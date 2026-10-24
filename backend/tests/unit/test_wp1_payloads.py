"""WP1: compact, canonical new ledger payloads retain operational table details."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from probation.core.types import Outcome, Situation
from probation.db.ledger import ledger_snapshot
from probation.engine.drift import check_family_shift
from probation.engine.policy import Policy
from probation.workers.resolver import resolve_outcomes


def _seed_situations(
    memory_db: sqlite3.Connection, *, tier: str, count: int, timestamp: str, offset: int
) -> None:
    """Insert `count` mail situations carrying one deterministic feature value."""
    for index in range(offset, offset + count):
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
            (situation, json.dumps({"sender_tier": tier}), timestamp),
        )


def _seed_shift_week(memory_db: sqlite3.Connection) -> None:
    """Seed a 20-item reference window and a 10-item current window that drifted."""
    _seed_situations(memory_db, tier="known", count=20, timestamp="2026-01-01T10:00:00Z", offset=0)
    _seed_situations(memory_db, tier="new", count=10, timestamp="2026-03-15T10:00:00Z", offset=20)


def _seed_more_current_situations(memory_db: sqlite3.Connection, *, tier: str, count: int) -> None:
    """Add to the current window only, so a recheck recomputes a different PSI."""
    _seed_situations(memory_db, tier=tier, count=count, timestamp="2026-03-16T10:00:00Z", offset=30)


def _shift_policy() -> Policy:
    """A shift check measures populations through the features a fitted policy selected.

    Without a policy it reports no alarm rather than inventing one, so these payload tests carry
    the same authority the scheduler builds for every weekly tick (docs/ENGINE_SPEC.md 11.2).
    """
    policy = Policy("email_action", cold_start_min=20)
    policy.fit(
        [{"sender_tier": "known"}] * 20 + [{"sender_tier": "new"}] * 20,
        ["ARCHIVE"] * 20 + ["LEAVE"] * 20,
        ["2026-01-01T10:00:00Z"] * 20 + ["2026-03-15T10:00:00Z"] * 20,
        "2026-04-01T00:00:00Z",
    )
    return policy


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
    _seed_shift_week(memory_db)
    assert check_family_shift(
        memory_db, "email_action", "2026-04-01T00:00:00Z", policy=_shift_policy()
    )
    payload = json.loads(memory_db.execute("SELECT payload_json FROM ledger").fetchone()[0])
    assert payload["kind"] == "family_shift"
    assert payload["family"] == "email_action"
    assert payload["max_psi"] > 0.25
    assert "alarm_type" not in payload


def test_rechecking_an_unchanged_week_does_not_duplicate_the_alarm(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    """A resumed replay re-runs every weekly tick, so rechecks must not re-append.

    Authority: docs/CONTRACT.md I-8 (append-only ledger) and docs/ENGINE_SPEC.md section 11.2.
    Duplicated drift_alarm rows inflate the alarm counts that eval/metrics.py and the
    insights route report, so a week whose PSI is unchanged is recorded exactly once.
    """
    _seed_shift_week(memory_db)
    as_of = "2026-04-01T00:00:00Z"
    policy = _shift_policy()
    assert check_family_shift(memory_db, "email_action", as_of, policy=policy)
    assert check_family_shift(memory_db, "email_action", as_of, policy=policy)
    assert check_family_shift(memory_db, "email_action", as_of, policy=policy)

    rows = memory_db.execute(
        "SELECT seq, ref_id FROM ledger WHERE kind='drift_alarm' ORDER BY seq"
    ).fetchall()
    assert len(rows) == 1, f"unchanged recheck re-appended the alarm: {[r[1] for r in rows]}"
    assert memory_db.execute("SELECT COUNT(*) FROM family_shift").fetchone()[0] == 1
    assert ledger_snapshot(memory_db).ok


def test_a_changed_recheck_still_reaches_the_audit_trail(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    """The idempotency guard must not swallow a genuinely new alarm.

    Failing closed means the drift signal is never suppressed: if the week recomputes
    differently, that is new information and it must be appended.
    """
    _seed_shift_week(memory_db)
    as_of = "2026-04-01T00:00:00Z"
    policy = _shift_policy()
    assert check_family_shift(memory_db, "email_action", as_of, policy=policy)
    before = memory_db.execute(
        "SELECT psi_json FROM family_shift WHERE week_start=?", (as_of,)
    ).fetchone()[0]

    _seed_more_current_situations(memory_db, tier="known", count=15)
    assert check_family_shift(memory_db, "email_action", as_of, policy=policy)

    rows = memory_db.execute(
        "SELECT seq, ref_id FROM ledger WHERE kind='drift_alarm' ORDER BY seq"
    ).fetchall()
    after = memory_db.execute(
        "SELECT psi_json FROM family_shift WHERE week_start=?", (as_of,)
    ).fetchone()[0]
    assert after != before, "the recheck must have recomputed a different PSI"
    assert len(rows) == 2, f"changed recheck was suppressed: {[r[1] for r in rows]}"
    assert rows[0][1] == rows[1][1], "both entries describe the same family and week"
    assert ledger_snapshot(memory_db).ok
