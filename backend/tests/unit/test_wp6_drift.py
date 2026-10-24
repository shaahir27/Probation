"""D3 drift consumes eligible decisions once and uses configured posterior baselines."""

import pytest

from probation.config import settings
from probation.core.enums import GateDecision
from probation.core.types import Proposal
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger
from probation.engine.licence import derive_and_cache_licences
from probation.workers.drift import review_outcome_events


def proposal(conn, situation):
    from probation.db.proposals import persist_proposal

    persist_proposal(
        RoleAccess(conn, Role.BRAIN),
        Proposal(
            id="drift-p",
            situation_id=situation.id,
            family=situation.family,
            class_key="mail|request|known",
            action="ARCHIVE",
            p_max=0.99,
            gate=GateDecision.SHADOW,
            novel=False,
            proposed_at=situation.occurred_at,
            policy_version="test",
            features_hash="test",
        ),
    )
    conn.commit()


def decision(conn, situation, key, *, actor="human", strength="STRONG", day=2):
    timestamp = f"2026-01-{day:02d}T00:00:00Z"
    append_ledger(
        conn,
        "outcome",
        key,
        {
            "situation_id": situation.id,
            "proposal_id": "drift-p",
            "observed_action": "TRASH",
            "source": "footprint",
            "strength": strength,
            "actor": actor,
            "known_at": timestamp,
        },
        timestamp,
    )
    conn.commit()


def test_configured_alarm_threshold_applies_to_actual_worker(
    memory_db, basic_situation, monkeypatch
):
    proposal(memory_db, basic_situation)
    decision(memory_db, basic_situation, "error")
    monkeypatch.setattr(settings, "cusum_threshold", 0.5)
    review_outcome_events(memory_db, as_of="2026-01-02T00:00:00Z")
    assert (
        memory_db.execute("SELECT count(*) FROM ledger WHERE kind='drift_alarm'").fetchone()[0] == 1
    )


def test_automation_and_duplicate_decisions_cannot_drive_cusum(memory_db, basic_situation):
    proposal(memory_db, basic_situation)
    decision(memory_db, basic_situation, "automation", actor="probation")
    review_outcome_events(memory_db, as_of="2026-01-02T00:00:00Z")
    assert memory_db.execute("SELECT count(*) FROM drift_state").fetchone()[0] == 0
    decision(memory_db, basic_situation, "actual", day=3)
    decision(memory_db, basic_situation, "duplicate", day=4)
    review_outcome_events(memory_db, as_of="2026-01-04T00:00:00Z")
    assert memory_db.execute("SELECT cusum FROM drift_state").fetchone()[0] == pytest.approx(0.95)
    assert memory_db.execute("SELECT count(*) FROM drift_receipts").fetchone()[0] == 3


def test_eligible_weak_disagreement_is_monitored_but_not_relabelled(memory_db, basic_situation):
    proposal(memory_db, basic_situation)
    decision(memory_db, basic_situation, "weak", strength="WEAK")
    review_outcome_events(memory_db, as_of="2026-01-02T00:00:00Z")
    assert memory_db.execute("SELECT cusum FROM drift_state").fetchone()[0] == pytest.approx(0.95)


def test_actual_licence_change_refreshes_posterior_baseline(memory_db):
    from tests.unit.test_wp5_licence_derivation import cohort

    cohort(memory_db)
    views = derive_and_cache_licences(memory_db, "2026-06-01T00:00:00Z")
    assert int(views[("mail|request|known", "ARCHIVE")].level) == 1
    row = memory_db.execute(
        "SELECT baseline_err FROM drift_state WHERE class_key='mail|request|known'"
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(1 - 71 / 72)
