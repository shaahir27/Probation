"""Fifty seeded cuts exercise trained file vocabularies, calibration and novelty."""

import json
import random
import sqlite3
from datetime import UTC, datetime, timedelta

from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.db.ledger import append_ledger
from probation.engine.novelty import NoveltyDetector
from probation.engine.policy import Policy
from probation.engine.training import build_cohort, fit_cohort
from tests.stubs.embeddings import RecordedEmbeddings


def test_fifty_file_cuts_keep_calibration_vocabulary_novelty_and_explanations(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(300):
        when = (base + timedelta(hours=i)).isoformat()
        known = (base + timedelta(hours=i, minutes=5)).isoformat()
        raw, sid = f"w4-raw-{i}", f"w4-file-{i}"
        payload = json.dumps({"filename": f"CourseLab{i % 11}.pdf", "folder": "Downloads"})
        memory_db.execute(
            "INSERT INTO raw_items VALUES (?,'wp1-source','files','file',?,?,?,?, 'h')",
            (raw, raw, when, when, payload),
        )
        memory_db.execute(
            "INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,sender_key,content_hash,redacted_text,created_at) VALUES (?,?,'files','file_destination',?,'course','h','bounded course lab pdf',?)",
            (sid, raw, when, when),
        )
        det = {
            "extension": "pdf",
            "odd": i % 2,
            "__reader_required": False,
            "__deterministic_ok": True,
            "__budget_ok": True,
            "__novelty_text": f"lab {i % 7} pdf",
        }
        memory_db.execute(
            "INSERT INTO features(situation_id,deterministic_json,reader_ok,featurizer_version,features_hash,created_at) VALUES (?,?,1,'w4-test',?,?)",
            (sid, json.dumps(det), f"hash-{i}", when),
        )
        append_ledger(
            memory_db,
            "outcome",
            sid,
            {
                "situation_id": sid,
                "observed_action": f"MOVE_TO_FOLDER:Course/{'A' if i % 2 else 'B'}",
                "known_at": known,
                "source": "footprint",
                "strength": "STRONG",
            },
            known,
        )

    for cut in random.Random(771).sample(range(200, 280), 50):
        cutoff = (base + timedelta(hours=cut, minutes=30)).isoformat()
        history = HistoryView(memory_db, cutoff)
        before = build_cohort(history, "file_destination", "w4-test")
        policy = fit_cohort(Policy("file_destination"), before, cutoff)
        assert policy.is_fitted and policy.calibration["status"] == "calibrated"
        expected_folders = (
            ("MOVE_TO_FOLDER:Course/B", "MOVE_TO_FOLDER:Course/A")
            if cut % 2 == 0
            else ("MOVE_TO_FOLDER:Course/A", "MOVE_TO_FOLDER:Course/B")
        )
        assert policy.vocabulary.folders == expected_folders
        novelty = NoveltyDetector(k=3, embedder=RecordedEmbeddings()).fit(
            [row.redacted_text for row in before.rows],
            reference_ids=[row.situation_id for row in before.rows],
            family="file_destination",
        )
        query = before.rows[0].features
        prediction, explanation = policy.predict(query), policy.explain(query)
        novelty_result = novelty.score(before.rows[0].redacted_text)
        memory_db.execute("SAVEPOINT future_changes")
        try:
            changed = memory_db.execute(
                "UPDATE raw_items SET payload_json=? WHERE pack='files' AND known_at COLLATE UTC_TIMESTAMP > ?",
                (
                    json.dumps({"filename": "leaked future tokens.pdf", "folder": "Future/Secret"}),
                    cutoff,
                ),
            ).rowcount
            assert changed > 0
            memory_db.execute(
                "UPDATE features SET deterministic_json=? WHERE created_at COLLATE UTC_TIMESTAMP > ?",
                (json.dumps({"odd": 999, "future_label": "LEAVE"}), cutoff),
            )
            after = build_cohort(history, "file_destination", "w4-test")
            assert after == before
            refit = fit_cohort(Policy("file_destination"), after, cutoff)
            assert refit.policy_digest == policy.policy_digest
            assert refit.predict(query) == prediction and refit.explain(query) == explanation
            ref_novelty = NoveltyDetector(k=3, embedder=RecordedEmbeddings()).fit(
                [row.redacted_text for row in after.rows],
                reference_ids=[row.situation_id for row in after.rows],
                family="file_destination",
            )
            assert ref_novelty.threshold == novelty.threshold
            assert ref_novelty.score(after.rows[0].redacted_text) == novelty_result
        finally:
            memory_db.execute("ROLLBACK TO future_changes")
            memory_db.execute("RELEASE future_changes")
