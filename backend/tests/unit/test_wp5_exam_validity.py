"""Exact pair, level, expiry and historical alarm validity regressions."""

import pytest

from probation.core.enums import LedgerKind
from probation.db.access import Role, RoleAccess
from probation.engine.licence import check_exam_ok, get_latest_passing_exam_id

T = "2026-06-01T00:00:00Z"
FINISH = "2026-05-31T00:00:00Z"


def exam(conn, ck="mail|request|known", finish=FINISH, level=2, passed=1, provenance=True):
    conn.execute(
        """INSERT INTO exam_runs(id,class_key,action,level_tested,started_at,finished_at,
        n_cases,passed,details_json) VALUES ('exam',?,'ARCHIVE',?,?,?,?,?,'{}')""",
        (ck, level, FINISH, finish, 20, passed),
    )
    if provenance and finish is not None:
        from tests.unit.wp5_fixture_ledger import complete_validity_exam_fixture

        complete_validity_exam_fixture(conn)


def test_a_bare_legacy_pass_is_not_proof_of_a_meaningful_exam(memory_db):
    exam(memory_db, provenance=False)
    assert not check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", T, 2)


@pytest.mark.parametrize("finish", ["2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z", None])
def test_latest_exam_id_obeys_same_validity_as_boolean(memory_db, finish):
    exam(memory_db, finish=finish)
    assert not check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", T, 2)
    assert get_latest_passing_exam_id(memory_db, "mail|request|known", "ARCHIVE", T, 2) is None


@pytest.mark.parametrize(
    "prefix,family",
    [
        ("mail", "email_action"),
        ("cal", "invite_rsvp"),
        ("file", "file_destination"),
        ("radar", "opportunity_triage"),
        ("reading", "link_triage"),
        ("chain", "chain_followup"),
    ],
)
def test_family_alarm_applies_to_every_alias(memory_db, prefix, family):
    ck = f"{prefix}|request|known"
    exam(memory_db, ck)
    memory_db.execute("INSERT INTO family_shift VALUES (?,?,'{}',1)", (family, FINISH))
    assert not check_exam_ok(memory_db, ck, "ARCHIVE", T, 2)


@pytest.mark.parametrize("stored_alias", ["calendar", "cal", "invite_rsvp"])
def test_cross_spelling_family_alarms_are_equivalent(memory_db, stored_alias):
    ck = "cal|request|known"
    exam(memory_db, ck)
    memory_db.execute("INSERT INTO family_shift VALUES (?,?,'{}',1)", (stored_alias, FINISH))
    assert not check_exam_ok(memory_db, ck, "ARCHIVE", T, 2)


def test_future_state_cannot_demote_past_but_earlier_ledger_alarm_still_applies(memory_db):
    ck = "mail|request|known"
    exam(memory_db)
    memory_db.execute(
        "INSERT INTO drift_state VALUES (?,'ARCHIVE',0,.03,'2026-07-01T00:00:00Z')", (ck,)
    )
    assert check_exam_ok(memory_db, ck, "ARCHIVE", T, 2)
    RoleAccess(memory_db, Role.EXAMINER).append_ledger(
        LedgerKind.DRIFT_ALARM,
        "a",
        {"class_key": ck, "action": "ARCHIVE", "kind": "cusum"},
        created_at=FINISH,
    )
    assert not check_exam_ok(memory_db, ck, "ARCHIVE", T, 2)


def test_tested_level_and_pair_are_exact(memory_db):
    exam(memory_db, level=3)
    assert check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", T, 2)
    assert check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", T, 3)
    assert not check_exam_ok(memory_db, "mail|fyi|known", "ARCHIVE", T, 2)
    assert not check_exam_ok(memory_db, "mail|request|known", "TRASH", T, 2)


@pytest.mark.parametrize(
    "field,value",
    [
        ("feature_version", "obsolete-version"),
        ("model_cutoff", "2026-07-01T00:00:00Z"),
        ("configured_models", ["obsolete", "obsolete"]),
    ],
)
def test_incompatible_or_future_snapshot_is_not_authority(memory_db, field, value):
    import json

    exam(memory_db)
    details = json.loads(memory_db.execute("SELECT details_json FROM exam_runs").fetchone()[0])
    details["snapshot"][field] = value
    memory_db.execute("UPDATE exam_runs SET details_json=?", (json.dumps(details),))
    assert not check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", T, 2)


@pytest.mark.parametrize("mutation", ["unknown", "missing", "inflated", "noninteger"])
def test_operator_proof_must_match_actual_catalogue_and_distinct_bases(memory_db, mutation):
    import json

    exam(memory_db)
    details = json.loads(memory_db.execute("SELECT details_json FROM exam_runs").fetchone()[0])
    if mutation == "unknown":
        details["required_operators"] = ["nonexistent_operator"]
        details["operator_coverage"] = {"nonexistent_operator": 20}
    elif mutation == "missing":
        removed = details["required_operators"].pop()
        del details["operator_coverage"][removed]
    else:
        name = details["required_operators"][0]
        details["operator_coverage"][name] = 21 if mutation == "inflated" else 20.0
    memory_db.execute("UPDATE exam_runs SET details_json=?", (json.dumps(details),))
    assert not check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", T, 2)


@pytest.mark.parametrize("field", ["model_cutoff", "history_cutoff"])
def test_frozen_snapshot_must_exist_before_exam_started(memory_db, field):
    import json

    exam(memory_db, finish=T)
    details = json.loads(memory_db.execute("SELECT details_json FROM exam_runs").fetchone()[0])
    details["snapshot"]["model_cutoff"] = FINISH
    details["snapshot"]["history_cutoff"] = FINISH
    details["snapshot"][field] = "2026-05-31T12:00:00Z"
    if field == "model_cutoff":
        details["snapshot"]["history_cutoff"] = T
    memory_db.execute("UPDATE exam_runs SET details_json=?", (json.dumps(details),))
    assert not check_exam_ok(memory_db, "mail|request|known", "ARCHIVE", T, 2)
