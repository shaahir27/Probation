"""Test-only construction of genuine immutable commitments for legacy SQL fixtures."""

from probation.core.enums import LedgerKind
from probation.db.access import Role, RoleAccess


def valid_exam_details(finished, class_key="mail|request|known"):
    """Explicit proof fixture for validity tests; never used as integration evidence."""
    from probation.config import settings
    from probation.engine.exam_catalogue import operators_for_class
    from probation.llm.feature_identity import semantic_feature_version

    operators = operators_for_class(class_key)

    return {
        "snapshot_version": "wp5-frozen-v1",
        "snapshot": {
            "policy_digest": "validity-fixture",
            "history_digest": "validity-fixture",
            "feature_version": semantic_feature_version(stub=True),
            "configured_models": [settings.model_reader, settings.model_exam_edits],
            "model_cutoff": finished,
            "history_cutoff": finished,
        },
        "required_operators": [op.name for op in operators],
        "operator_coverage": {op.name: 20 for op in operators},
        "base_ids": [f"fixture-{i}" for i in range(20)],
        "valid_base_cases": 20,
        "pipeline_failures": 0,
        "missing_operators": [],
    }


def complete_validity_exam_fixture(conn):
    import json

    for row in conn.execute("SELECT id,class_key,started_at FROM exam_runs").fetchall():
        conn.execute(
            """UPDATE exam_runs SET details_json=?,invariance_flip_rate=0,
            directional_violations_critical=0,directional_violation_rate_other=0 WHERE id=?""",
            (json.dumps(valid_exam_details(row["started_at"], row["class_key"])), row["id"]),
        )
    conn.commit()


def commit_fixture_decisions(conn):
    for row in conn.execute("SELECT * FROM proposals ORDER BY proposed_at,id").fetchall():
        outcome = conn.execute(
            "SELECT * FROM outcomes WHERE situation_id=?", (row["situation_id"],)
        ).fetchone()
        seq = RoleAccess(conn, Role.BRAIN).append_ledger(
            LedgerKind.PROPOSAL,
            row["id"],
            {
                "situation_id": row["situation_id"],
                "class_key": row["class_key"],
                "action": row["action"],
                "gate": row["gate"],
            },
            created_at=row["proposed_at"],
        )
        conn.execute("UPDATE proposals SET ledger_seq=? WHERE id=?", (seq, row["id"]))
        if outcome:
            seq = RoleAccess(conn, Role.RESOLVER).append_ledger(
                LedgerKind.OUTCOME,
                row["situation_id"],
                {
                    "situation_id": row["situation_id"],
                    "observed_action": outcome["observed_action"],
                    "strength": outcome["strength"],
                    "source": outcome["source"],
                    "known_at": outcome["known_at"],
                },
                created_at=outcome["known_at"],
            )
            conn.execute(
                "UPDATE outcomes SET ledger_seq=? WHERE situation_id=?", (seq, row["situation_id"])
            )
    conn.commit()
