"""All authority consumers see the same cutoff and ignore cached levels."""

from probation.api.routes.licences import get_licences
from probation.config import settings
from probation.core.clock import Clock, parse_timestamp, use_clock
from probation.engine.licence import derive_and_cache_licences, derive_licences
from probation.workers.executor import Executor
from tests.unit.test_wp5_exam_validity import exam
from tests.unit.test_wp5_licence_derivation import cohort


def test_api_examiner_executor_permission_parity(memory_db, tmp_path, monkeypatch):
    from probation.db.connection import get_connection

    cohort(memory_db)
    exam(memory_db)
    memory_db.commit()
    cutoff = "2026-06-01T00:00:00Z"
    pair = ("mail|request|known", "ARCHIVE")
    from probation.workers.drift import review_outcome_events

    review_outcome_events(memory_db, as_of=cutoff)
    memory_db.commit()
    direct = derive_licences(memory_db, cutoff)[pair]
    cached = derive_and_cache_licences(memory_db, cutoff)[pair]
    assert direct == cached
    assert Executor(memory_db)._default_licence_checker(*pair, cutoff) == 2
    path = tmp_path / "parity.db"
    target = get_connection(path)
    memory_db.backup(target)
    target.close()
    monkeypatch.setattr(settings, "db_path", path)
    with use_clock(Clock.replay(parse_timestamp(cutoff))):
        api = get_licences()["licences"][0]
    assert api["level"] == 2 and api["exam_run_id"] == "exam"
    assert api["n_strong"] == direct.n_strong == 70
    assert api["lower_bound"] == direct.lower_bound
    assert api["exam_ok"] is True


def test_gate_remains_restricted_without_a_valid_exam(memory_db):
    from probation.engine.gate import decide_gate

    cohort(memory_db)
    view = derive_licences(memory_db, "2026-06-01T00:00:00Z")[("mail|request|known", "ARCHIVE")]
    assert int(view.level) == 1
    result = decide_gate(
        action="ARCHIVE",
        p=0.999,
        novel=False,
        licence_level=int(view.level),
        cap=3,
        hands_off=None,
        reader_required=True,
        reader_ok=True,
        deterministic_ok=True,
        budget_ok=True,
        loss=5,
        recallable=True,
        attention_cost=1,
        audit_draw=0.5,
        audit_fraction=0.1,
    )
    assert str(result.decision) == "SUGGEST"
