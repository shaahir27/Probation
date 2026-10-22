"""WP1: helpers cannot commit unrelated work owned by their caller."""

import sqlite3
from typing import Any

import pytest

from probation.engine.licence import derive_and_cache_licences
from probation.workers.brain import extract_features_for_situations
from probation.workers.ingestor import ingest_situations
from probation.workers.resolver import resolve_outcomes


class EmptyWorld:
    def get_messages(self) -> list[Any]:
        return []


@pytest.mark.parametrize("helper", ["licences", "features", "ingestion", "resolution"])
def test_helper_never_commits_unrelated_parent_work(
    memory_db: sqlite3.Connection, helper: str
) -> None:
    with pytest.raises(RuntimeError), memory_db:
        memory_db.execute("INSERT INTO meta(key,value) VALUES ('parent-work','synthetic')")
        if helper == "licences":
            derive_and_cache_licences(memory_db, as_of="2026-01-01T00:00:00Z", stats={})
        elif helper == "features":
            extract_features_for_situations(memory_db)
        elif helper == "ingestion":
            ingest_situations(memory_db)
        else:
            resolve_outcomes(
                memory_db,
                EmptyWorld(),
                as_of="2026-01-01T00:00:00Z",
                user_addresses="synthetic@example.test",
            )
        raise RuntimeError("caller failed after helper returned")
    assert memory_db.execute("SELECT count(*) FROM meta WHERE key='parent-work'").fetchone()[0] == 0
