"""Unit and integration test for ingestor worker and brain featurization step on tiny_synth.

Authority: docs/IMPLEMENTATION_PLAN.md Phase 3 deliverables.
Verifies:
1. Ingesting tiny_synth mbox and ics into raw_items.
2. Ingestor worker extracts situations idempotently into situations table.
3. Brain worker extracts deterministic clues and reader fields into features table.
"""

import json
import sqlite3
from pathlib import Path

from probation.db.connection import apply_schema
from probation.synth.importers import import_calendar, import_mail
from probation.workers.brain import extract_features_for_situations
from probation.workers.ingestor import ingest_situations
from tests.stubs.stub_reader import StubReader


def test_ingestion_and_featurization_on_tiny_synth() -> None:
    """Verify end-to-end ingestion and featurization pipeline on synthetic baseline fixture."""
    fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_synth"
    mbox_path = fixture_dir / "mailbox.mbox"
    ics_path = fixture_dir / "calendar.ics"
    truth_path = fixture_dir / "truth.json"

    assert mbox_path.exists(), f"Missing fixture: {mbox_path}"
    assert ics_path.exists(), f"Missing fixture: {ics_path}"
    assert truth_path.exists(), f"Missing fixture: {truth_path}"

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)

    # 1. Import raw items
    user_addrs = ["meena.k@example.ac.in"]
    res_mail = import_mail(mbox_path, conn, user_addresses=user_addrs)
    res_cal = import_calendar(ics_path, conn, user_addresses=user_addrs)

    assert res_mail.items_imported > 0
    assert res_cal.items_imported > 0

    # 2. Run Ingestor Worker
    sit_count_1 = ingest_situations(conn)
    assert sit_count_1 > 0, "No situations extracted by ingestor!"

    # Idempotency check: re-running should extract 0 new situations
    sit_count_2 = ingest_situations(conn)
    assert sit_count_2 == 0, "Ingestor extracted duplicate situations on re-run!"

    # Inspect situations in DB
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM situations;")
    situations = cursor.fetchall()
    assert len(situations) == sit_count_1

    for s in situations:
        assert s["id"]
        assert s["pack"] in ("mail", "calendar")
        assert s["family"] in ("email_action", "invite_rsvp")
        assert s["occurred_at"]
        assert s["content_hash"]
        assert s["redacted_text"]

    # 3. Run Brain Featurizer with StubReader
    stub_reader = StubReader(truth_path)
    feat_count_1 = extract_features_for_situations(conn, reader_callable=stub_reader)
    assert feat_count_1 == sit_count_1, "Mismatch in featurized situations count!"

    # Idempotency check: re-running should extract 0 new features
    feat_count_2 = extract_features_for_situations(conn, reader_callable=stub_reader)
    assert feat_count_2 == 0, "Brain worker featurized duplicates on re-run!"

    # Inspect features in DB
    cursor.execute("SELECT * FROM features;")
    features = cursor.fetchall()
    assert len(features) == feat_count_1

    for f in features:
        assert f["situation_id"]
        det_data = json.loads(f["deterministic_json"])
        assert isinstance(det_data, dict)
        assert len(det_data) >= 10, "Deterministic clues dictionary incomplete!"

        assert f["reader_ok"] in (0, 1)
        assert f["features_hash"]
        assert len(f["features_hash"]) == 64
