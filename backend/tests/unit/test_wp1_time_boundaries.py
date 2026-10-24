"""WP1: fractional and offset timestamps cannot advance authority or a hold."""

import sqlite3
from datetime import UTC, datetime

import pytest

from probation.core.clock import parse_timestamp
from probation.core.enums import GateDecision
from probation.core.hashing import canonical_json
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.proposals import persist_proposal
from probation.engine.licence import check_exam_ok
from probation.workers.executor import Executor


def test_future_fractional_exam_is_unavailable_at_whole_second_cut(
    memory_db: sqlite3.Connection,
) -> None:
    memory_db.execute("""INSERT INTO exam_runs(id,class_key,action,level_tested,started_at,finished_at,n_cases,passed,details_json)
                       VALUES ('wp1-time-exam','mail|request|known','ARCHIVE',2,
                       '2026-01-01T10:00:00.500000Z','2026-01-01T10:00:00.500000Z',20,1,'{}')""")
    from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

    complete_validity_exam_fixture(memory_db)
    assert not check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", "2026-01-01T10:00:00Z", 2)
    assert check_exam_ok(
        memory_db, "mail|request|known", "ARCHIVE", "2026-01-01T15:30:00.600000+05:30", 2
    )


def test_hold_keeps_fractional_precision(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    persist_proposal(
        RoleAccess(memory_db, Role.BRAIN),
        Proposal(
            id="time-proposal",
            situation_id=basic_situation.id,
            family=basic_situation.family,
            class_key="mail|request|known",
            action="REPLY",
            p_max=0.99,
            novel=False,
            gate=GateDecision.HOLD_THEN_EXECUTE,
            policy_version="wp1",
            features_hash="wp1",
            proposed_at=basic_situation.occurred_at,
        ),
    )
    memory_db.commit()
    action = Executor(memory_db).create_action(
        "time-proposal",
        "mail",
        "REPLY",
        {"message_id": "synthetic"},
        2,
        False,
        GateDecision.HOLD_THEN_EXECUTE,
        "2026-01-01T10:00:00.500000Z",
    )
    assert action.hold_until == "2026-01-01T10:10:00.500000Z"


def test_new_datetime_hash_material_keeps_precision() -> None:
    time = datetime(2026, 1, 1, 10, 0, 0, 123456, tzinfo=UTC)
    assert canonical_json({"time": time}) == '{"time":"2026-01-01T10:00:00.123456Z"}'


def test_timestamp_precision_beyond_microseconds_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_timestamp("2026-01-01T10:00:00.1234567Z")
