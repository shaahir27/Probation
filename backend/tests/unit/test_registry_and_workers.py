"""Tests for PackRegistry, workers (ingestor, brain), and data isolation.

Authority: docs/CONTRACT.md section 2 (Invariants), section 5, and docs/TEST_PLAN.md T-ID, T-PACK.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probation.core.types import ActionSpec, ReaderSpec
from probation.db.connection import get_connection, init_db
from probation.packs.base import PackAdapter
from probation.packs.registry import PackRegistry, registry, validate_pack
from probation.synth.importers import import_mail
from probation.workers.brain import extract_features_for_situations
from probation.workers.ingestor import ingest_situations
from probation.workers.webfacts import vet_situations_batch
from tests.stubs.stub_reader import StubReader


class DummyInvalidPack:
    """Mock pack missing required attributes for validation testing."""

    name = ""
    domain = "mail"

    def __init__(self) -> None:
        self.families: list[str] = []

    def action_catalog(self) -> list[ActionSpec]:
        return []

    def reader_spec(self) -> ReaderSpec:
        return ReaderSpec(
            prompt_id="test",
            prompt_version="v1",
            json_schema={},
            redaction_profile="standard",
        )


def test_registry_lookups() -> None:
    """Test registry lookups for registered mail and calendar packs."""
    assert "mail" in registry.list_packs()
    assert "calendar" in registry.list_packs()

    mail = registry.get("mail")
    assert mail.name == "mail"
    assert "email_action" in mail.families

    cal = registry.get("calendar")
    assert cal.name == "calendar"
    assert "invite_rsvp" in cal.families

    # Family lookups
    assert registry.get_by_family("email_action") == mail
    assert registry.get_by_family("invite_rsvp") == cal
    assert registry.get_by_family("unknown_family") is None


def test_registry_unknown_pack_raises() -> None:
    """Accessing an unregistered pack name raises KeyError."""
    with pytest.raises(KeyError, match="is not registered"):
        registry.get("nonexistent_pack")


def test_registry_validation_failures() -> None:
    """validate_pack enforces non-empty name, families, and valid action specs."""
    reg = PackRegistry()
    invalid_pack = DummyInvalidPack()

    # Empty name
    with pytest.raises(ValueError, match="non-empty name"):
        reg.register(invalid_pack)  # type: ignore[arg-type]

    # Empty families
    valid_name_pack = MagicMock(spec=PackAdapter)
    valid_name_pack.name = "test_pack"
    valid_name_pack.families = []
    with pytest.raises(ValueError, match="at least one family"):
        validate_pack(valid_name_pack)

    # Invalid action cap (> 3)
    valid_name_pack.families = ["test_fam"]
    valid_name_pack.action_catalog.return_value = [
        ActionSpec(type="OP", base_cap=5, loss=1.0, recallable=True)
    ]
    with pytest.raises(ValueError, match="invalid cap"):
        validate_pack(valid_name_pack)


def test_ingestor_empty_db(tmp_path: Any) -> None:
    """Ingest on an empty raw_items table returns 0 situations."""
    db_path = tmp_path / "test_empty.db"
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        count = ingest_situations(conn)
        assert count == 0
    finally:
        conn.close()


def test_ingestor_and_brain_idempotence(tmp_path: Any) -> None:
    """Ingestion and feature extraction are idempotent on successive runs."""
    db_path = tmp_path / "test_idemp.db"
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_synth"
        mbox_path = fixture_dir / "mailbox.mbox"
        import_mail(mbox_path, conn, user_addresses=["meena.k@example.ac.in"])

        # First ingestion
        s_count_1 = ingest_situations(conn)
        assert s_count_1 > 0

        # Second ingestion: raw-1 already has situation; returns 0 new
        s_count_2 = ingest_situations(conn)
        assert s_count_2 == 0

        # First feature extraction
        stub = StubReader(fixture_dir / "truth.json")
        f_count_1 = extract_features_for_situations(conn, reader_callable=stub)
        assert f_count_1 > 0

        # Second feature extraction: returns 0 new
        f_count_2 = extract_features_for_situations(conn, reader_callable=stub)
        assert f_count_2 == 0
    finally:
        conn.close()


def test_vet_situations_batch(tmp_path: Any) -> None:
    """vet_situations_batch vets sender domains for situations into web_facts table."""
    db_path = tmp_path / "test_vet_batch.db"
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        fixture_dir = Path(__file__).resolve().parent.parent / "fixtures" / "tiny_synth"
        mbox_path = fixture_dir / "mailbox.mbox"
        import_mail(mbox_path, conn, user_addresses=["meena.k@example.ac.in"])
        ingest_situations(conn)

        vetted = vet_situations_batch(conn)
        assert vetted > 0

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM web_facts;")
        assert cur.fetchone()[0] > 0
    finally:
        conn.close()
