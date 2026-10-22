"""WP1/WP2 integration: bounded queries retain read-only access and UTC ordering."""

import sqlite3

import pytest

from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger


def test_wp2_queries_preserve_wp1_read_only_temporal_boundary(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    sender = "synthetic@example.org"
    memory_db.execute("UPDATE situations SET sender_key=?", (sender,))
    memory_db.execute(
        """INSERT INTO raw_items
        SELECT 'future-raw',source_id,pack,item_kind,'future-ref',
               '2026-01-01T10:00:00.750000Z','2026-01-01T10:00:00.750000Z',
               payload_json,content_hash FROM raw_items WHERE id='wp1-raw'"""
    )
    memory_db.execute(
        """INSERT INTO situations
        (id,raw_item_id,pack,family,occurred_at,sender_key,content_hash,created_at)
        VALUES ('future','future-raw','mail','email_action',?,?, 'synthetic',?)""",
        ("2026-01-01T10:00:00.750000Z", sender, basic_situation.created_at),
    )
    for situation_id, known_at in [
        (basic_situation.id, "2026-01-01T10:00:00.500000+00:00"),
        ("future", "2026-01-01T10:00:01Z"),
    ]:
        seq = append_ledger(
            memory_db, "outcome", situation_id, {"situation_id": situation_id}, known_at
        )
        memory_db.execute(
            """INSERT INTO outcomes
            (situation_id,observed_action,strength,source,observed_at,known_at,details_json,ledger_seq)
            VALUES (?, 'REPLY','STRONG','footprint',?,?,'{}',?)""",
            (situation_id, known_at, known_at, seq),
        )
    memory_db.commit()

    history = HistoryView(RoleAccess(memory_db, Role.BRAIN).conn, "2026-01-01T10:00:00.600000Z")
    assert history.count_prior_sender_messages(sender) == 1
    assert history.count_prior_sender_messages(sender, basic_situation.id) == 0
    assert history.count_prior_sender_replies(sender) == 1
    assert history.get_prior_sender_reply_deltas(sender) == pytest.approx([0.5 / 3600])
    assert [row["situation_id"] for row in history.get_prior_outcomes("email_action")] == [
        basic_situation.id
    ]
    assert history.count_prior_sent_to_recipient(sender) == 0
    assert history.get_prior_thread_stats("synthetic", "", [sender]) == (0, False)
    assert history.get_prior_files_in_folder("synthetic") == 0
    assert history.get_unreviewed_outcome_events() == []
