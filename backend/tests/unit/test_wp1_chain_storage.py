"""WP1: a chain situation, immutable proposal and ledger form one storage unit."""

import sqlite3

import pytest

from probation.core.types import Situation
from probation.packs.chains.proposer import create_chain_situations_and_proposals


def _seed(conn: sqlite3.Connection) -> None:
    conn.execute("""INSERT INTO chains(id,trigger_class_key,follow_action,k,n,base_rate,lift,status,created_at)
                 VALUES ('wp1-chain','mail|request|known','CREATE_TASK',20,25,0.1,8,'active','2026-01-01T00:00:00Z')""")
    conn.commit()


def test_chain_storage_failure_rolls_back_situation_and_ledger(
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
) -> None:
    _seed(memory_db)
    memory_db.execute(
        "CREATE TRIGGER reject_chain_proposal BEFORE INSERT ON proposals BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
    )
    memory_db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        create_chain_situations_and_proposals(
            memory_db, basic_situation, "mail|request|known", basic_situation.occurred_at
        )
    assert (
        memory_db.execute("SELECT count(*) FROM situations WHERE pack='chains'").fetchone()[0] == 0
    )
    assert memory_db.execute("SELECT count(*) FROM ledger WHERE kind='proposal'").fetchone()[0] == 0


def test_chain_storage_preserves_parent_transaction(
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
) -> None:
    _seed(memory_db)
    memory_db.execute("BEGIN")
    result = create_chain_situations_and_proposals(
        memory_db, basic_situation, "mail|request|known", basic_situation.occurred_at
    )
    assert len(result) == 1
    memory_db.rollback()
    assert (
        memory_db.execute("SELECT count(*) FROM situations WHERE pack='chains'").fetchone()[0] == 0
    )
    assert memory_db.execute("SELECT count(*) FROM proposals").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0
