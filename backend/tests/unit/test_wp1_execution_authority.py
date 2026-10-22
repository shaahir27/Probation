"""WP1 dispatch repairs must not turn a cached permission into execution authority."""

import sqlite3

from probation.core.enums import GateDecision
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.proposals import persist_proposal
from probation.engine.evidence import aggregate_evidence
from probation.workers.executor import Executor


def test_executor_rederives_instead_of_trusting_an_injected_cache(
    memory_db: sqlite3.Connection,
) -> None:
    memory_db.execute("""INSERT INTO licence_cache(class_key,action,level,lower_bound,reasons_json,
                       computed_at,valid_until) VALUES ('mail|request|known','ARCHIVE',3,0.999,'[]',
                       '2026-01-01T00:00:00Z','2026-12-01T00:00:00Z')""")
    memory_db.commit()
    assert (
        Executor(memory_db)._default_licence_checker(
            "mail|request|known", "ARCHIVE", "2026-06-01T00:00:00Z"
        )
        == 0
    )


def test_execution_evidence_query_has_no_write_or_commit_capability(
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
) -> None:
    persist_proposal(
        RoleAccess(memory_db, Role.BRAIN),
        Proposal(
            id="authority-proposal",
            situation_id=basic_situation.id,
            family="email_action",
            class_key="mail|request|known",
            action="ARCHIVE",
            p_max=0.99,
            novel=False,
            gate=GateDecision.SUGGEST,
            policy_version="wp1",
            features_hash="wp1",
            proposed_at=basic_situation.occurred_at,
        ),
    )
    memory_db.execute(
        """INSERT INTO outcomes(situation_id,observed_action,strength,source,observed_at,known_at,details_json,ledger_seq)
                        VALUES (?,'ARCHIVE','STRONG','footprint','2026-01-02T00:00:00Z','2026-01-02T00:00:00Z','{}',0)""",
        (basic_situation.id,),
    )
    memory_db.commit()
    readonly = RoleAccess(memory_db, Role.EXECUTOR).conn
    stats = aggregate_evidence(readonly, as_of="2026-01-03T00:00:00Z", persist=False)
    assert stats[("mail|request|known", "ARCHIVE")].n_strong == 1
    assert memory_db.execute("SELECT count(*) FROM class_stats").fetchone()[0] == 0
    assert memory_db.in_transaction is False
