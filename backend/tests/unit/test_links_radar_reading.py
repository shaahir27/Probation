"""Comprehensive test suite for Phase 8b: Link Substrate, Opportunity Radar, Reading Triage.

Authority: docs/TAVILY_AND_NEW_PACKS.md, docs/PACKS_SPEC.md, docs/CONTRACT.md.
"""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from probation.core.types import Action, ActionStatus, EvidenceStrength, Situation
from probation.links.extract import extract_url_content
from probation.links.quarantine import (
    validate_link_fields,
    validate_opportunity_fields,
)
from probation.links.sanitise import (
    is_url_hands_off,
    sanitise_url,
)
from probation.packs.radar import radar_pack
from probation.packs.radar.clues import (
    extract_organiser_domain_class,
    extract_radar_clues,
)
from probation.packs.radar.digest import (
    generate_radar_digest,
    validate_radar_digest,
)
from probation.packs.radar.exam_ops import (
    apply_radar_code_operator,
    validate_radar_operator_result,
)
from probation.packs.radar.executor import execute_radar_action, undo_radar_action
from probation.packs.radar.out_of_band import (
    build_official_search_query,
    verify_opportunity_out_of_band,
)
from probation.packs.reading import reading_pack
from probation.packs.reading.clues import (
    extract_path_kind,
)
from probation.packs.reading.exam_ops import (
    apply_reading_code_operator,
    validate_reading_operator_result,
)
from probation.packs.reading.executor import execute_reading_action, undo_reading_action
from probation.packs.reading.resolver import resolve_reading_outcome
from probation.synth.world import SimWorld

# ==============================================================================
# 1. T-LINK: Link Sanitisation Tests
# ==============================================================================


def test_t_link_sanitisation_allowed_and_stripped() -> None:
    """T-LINK: Allowed HTTPS URLs have tracking parameters cleanly stripped."""
    raw_url = "https://example.com/fellowship?utm_source=twitter&utm_medium=social&utm_campaign=2026&ref=abc#overview"
    clean_url, reason = sanitise_url(raw_url)
    assert reason is None
    assert "utm_source" not in clean_url
    assert "utm_campaign" not in clean_url
    assert clean_url.startswith("https://example.com/fellowship")
    assert "#overview" not in clean_url  # fragment stripped


def test_t_link_sanitisation_schemes_and_hosts() -> None:
    """T-LINK: Rejects non-HTTP(S) schemes, localhost, and private IP spaces."""
    # Invalid schemes
    assert is_url_hands_off("ftp://ftp.example.com/data") is not None
    assert is_url_hands_off("javascript:alert(1)") is not None
    assert is_url_hands_off("file:///etc/passwd") is not None

    # Localhost & IP literal hosts
    assert is_url_hands_off("http://localhost:8000/api") is not None
    assert is_url_hands_off("http://127.0.0.1:8080/test") is not None
    assert is_url_hands_off("http://0.0.0.0/test") is not None
    assert is_url_hands_off("http://192.168.1.50/dashboard") is not None
    assert is_url_hands_off("http://10.0.0.1/doc") is not None


def test_t_link_sanitisation_sensitive_pages_and_tokens() -> None:
    """T-LINK: Rejects auth/login/checkout pages and URLs containing tokens."""
    # Sensitive intent
    assert is_url_hands_off("https://auth.provider.com/login?service=app") is not None
    assert is_url_hands_off("https://shop.com/checkout/step1") is not None
    assert is_url_hands_off("https://univ.edu/account/reset-password") is not None

    # Private tokens in query string
    token_url = "https://example.org/doc?api_key=secret1234567890abcdef"
    assert is_url_hands_off(token_url) is not None

    # Clean URL is allowed
    assert is_url_hands_off("https://huggingface.co/papers/2601.12345") is None


# ==============================================================================
# 2. T-QUAR: Quarantine and Schema Enforcement Tests
# ==============================================================================


def test_t_quar_opportunity_schema_and_date_presence() -> None:
    """T-QUAR: Opportunity reader extraction requires literal date presence and regex fee detection."""
    # Source page content containing official apply domain stanford.edu literally
    source_html = "Stanford AI Fellowship 2026 (https://stanford.edu). Application deadline is 2026-06-15. Application fee is $50. Eligible: undergraduates."

    # 1. Valid opportunity extraction matching source text
    valid_data = {
        "title": "Stanford AI Fellowship",
        "organiser": "Stanford University",
        "opp_type": "fellowship",
        "deadline_date": "2026-06-15",
        "fee_mentioned": True,
        "eligibility": ["undergraduates"],
        "apply_domain": "stanford.edu",
    }
    fields, ok, _notes = validate_opportunity_fields(valid_data, source_html)
    assert ok is True
    assert fields["deadline_date"] == "2026-06-15"
    assert fields["fee_mentioned"] is True

    # 2. Hallucinated date not in source text must fail date validation
    hallucinated_data = dict(valid_data, deadline_date="2026-12-31")
    fields_h, ok_h, notes_h = validate_opportunity_fields(hallucinated_data, source_html)
    assert ok_h is False
    assert fields_h["deadline_date"] is None
    assert any("deadline_date_unverified" in n for n in notes_h)

    # 3. Fee omission when source text mentions '$50' must be caught and raised by regex
    omitted_fee_data = dict(valid_data, fee_mentioned=False)
    fields_f, ok_f, notes_f = validate_opportunity_fields(omitted_fee_data, source_html)
    assert ok_f is True
    assert fields_f["fee_mentioned"] is True
    assert "fee_flag_raised_by_regex" in notes_f


def test_t_quar_reading_link_schema() -> None:
    """T-QUAR: Reading link quarantine extracts title, topic, content_type, and validates."""
    source_text = "Attention Is All You Need. We introduce the Transformer model for NLP."
    raw_reader_out = {
        "title": "Attention Is All You Need",
        "topic": "ai_ml",
        "content_type": "paper",
        "actionable": False,
    }
    fields, ok, _notes = validate_link_fields(raw_reader_out, source_text)
    assert ok is True
    assert fields["topic"] == "ai_ml"
    assert fields["content_type"] == "paper"


# ==============================================================================
# 3. T-EXTRACT: Extraction Substrate & Invariant I-24 Tests
# ==============================================================================


def test_t_extract_mail_source_strictly_rejected() -> None:
    """Invariant I-24: Never fetch links from mail bodies (fail closed)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        world = SimWorld(str(Path(tmp_dir) / "world.db"))
        try:
            from probation.web.client import TavilyClient

            client = TavilyClient(api_key="fake-test-key")
            # With is_user_saved=False and is_official_search=False (e.g. from mail)
            res = extract_url_content(
                url="https://legitimate-grant.org/apply",
                conn=world.conn,
                client=client,
                is_user_saved=False,
                is_official_search=False,
            )
            assert res["ok"] is False
            assert "Invariant I-24 violation" in res["error"]
        finally:
            world.close()


def test_t_extract_user_saved_truncation_and_cache() -> None:
    """T-EXTRACT: Truncates raw text to 6,000 characters and caches in database."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        world = SimWorld(str(Path(tmp_dir) / "world.db"))
        try:
            from probation.db.connection import apply_schema
            from probation.web.client import TavilyClient

            apply_schema(world.conn)

            test_url = "https://nature.com/articles/s41586-026-test"
            client = TavilyClient(api_key="fake-test-key")

            # Mock Tavily client extract response
            client.extract = lambda *args, **kwargs: {  # type: ignore
                "status": "ok",
                "results": [{"url": test_url, "raw_content": "Word " * 2000}],  # 10,000 chars
            }

            res = extract_url_content(
                url=test_url,
                conn=world.conn,
                client=client,
                is_user_saved=True,
            )
            assert res["ok"] is True
            assert res["content_text"] is not None
            assert len(res["content_text"]) <= 6000

            # Second call hits cache
            res2 = extract_url_content(
                url=test_url,
                conn=world.conn,
                client=client,
                is_user_saved=True,
            )
            assert res2["ok"] is True
            assert res2.get("cached") is True
        finally:
            world.close()


# ==============================================================================
# 4. T-RADAR: Opportunity Radar Pack Tests
# ==============================================================================


def test_t_radar_clues_and_class_key() -> None:
    """T-RADAR: Deterministic clues and partition class derivation."""
    assert extract_organiser_domain_class("https://cs.cmu.edu/fellowships") == "edu"
    assert extract_organiser_domain_class("https://nih.gov/grants") == "gov"
    assert extract_organiser_domain_class("https://openai.com/residency") == "corp"
    assert extract_organiser_domain_class("https://devpost.com/hackathons") == "platform"

    raw_opp = {
        "id": "raw-opp-1",
        "pack": "radar",
        "item_kind": "opportunity",
        "occurred_at": "2026-03-01T10:00:00Z",
        "payload_json": json.dumps(
            {
                "title": "Quantum Computing Grant 2026",
                "organizer": "National Science Foundation",
                "opp_type": "grant",
                "deadline_date": "2026-08-01",
                "official_url": "https://nsf.gov/grants/quantum",
                "fee_mentioned": False,
                "requires_personal_docs": True,
            }
        ),
    }
    sits = radar_pack.iter_situations(raw_opp)
    assert len(sits) == 1
    assert sits[0].family == "opportunity_triage"

    with tempfile.TemporaryDirectory() as tmp_dir:
        import sqlite3

        from probation.core.history import HistoryView
        from probation.db.connection import apply_schema

        conn = sqlite3.connect(str(Path(tmp_dir) / "clues.db"))
        try:
            apply_schema(conn)
            hist = HistoryView(conn, as_of="2026-03-01T10:00:00Z")
            payload = json.loads(raw_opp["payload_json"])
            clues = extract_radar_clues(sits[0], hist, payload)
            assert clues["organiser_domain_class"] == "gov"
            assert clues["has_deadline_in_mail"] is True
            assert clues["days_to_deadline_bucket_from_mail"] != "none"
            assert clues["n_prior_from_organiser"] == 0
        finally:
            conn.close()


def test_t_radar_out_of_band_and_query_construction() -> None:
    """T-RADAR: Out-of-band query uses public entity strings only, never mail contents."""
    query = build_official_search_query("Thiel Fellowship", "The Thiel Foundation")
    assert query == "The Thiel Foundation Thiel Fellowship official"
    # Never includes URL or mail parameters
    assert "http" not in query

    with tempfile.TemporaryDirectory() as tmp_dir:
        world = SimWorld(str(Path(tmp_dir) / "world.db"))
        try:
            from probation.web.client import TavilyClient

            client = TavilyClient(api_key="fake-key")

            # Mock search returning thielfellowship.org
            client.search = lambda *args, **kwargs: {  # type: ignore
                "status": "ok",
                "results": [
                    {
                        "title": "Thiel Fellowship Official",
                        "url": "https://thielfellowship.org/apply",
                    }
                ],
            }
            client.extract = lambda *args, **kwargs: {  # type: ignore
                "status": "ok",
                "results": [{"raw_content": "Deadline: 2026-10-01"}],
            }

            # 1. Matching mail domain: link_mismatch is False
            res_match = verify_opportunity_out_of_band(
                organiser_name="The Thiel Foundation",
                opportunity_name="Thiel Fellowship",
                mail_link_domains=["thielfellowship.org"],
                conn=world.conn,
                client=client,
                mail_deadline="2026-10-01",
                official_domains=frozenset({"thielfellowship.org"}),
            )
            assert res_match["verified"] is True
            assert res_match["link_mismatch"] is False
            assert res_match["official_domain"] == "thielfellowship.org"
            assert res_match["discrepancy"] is None

            # 2. Mismatched mail domain (e.g. scam site): link_mismatch is True
            res_mismatch = verify_opportunity_out_of_band(
                organiser_name="The Thiel Foundation",
                opportunity_name="Thiel Fellowship",
                mail_link_domains=["thiel-apply.scam.ru"],
                conn=world.conn,
                client=client,
                mail_deadline="2026-10-01",
                official_domains=frozenset({"thielfellowship.org"}),
            )
            assert res_mismatch["verified"] is True
            assert res_mismatch["link_mismatch"] is True
        finally:
            world.close()


def test_t_radar_conditional_caps() -> None:
    """T-RADAR: Fee or personal docs limits autonomy to Level 1 (Recommend only)."""
    sit = Situation(
        id="sit-radar-fee",
        raw_item_id="raw-1",
        pack="radar",
        family="opportunity_triage",
        variant="",
        occurred_at="2026-03-01T10:00:00Z",
        sender_key="academic",
        content_hash="h1",
        redacted_text="",
        hands_off_reason=None,
        created_at="2026-03-01T10:00:00Z",
    )
    from probation.core.types import Features

    # Without fee or personal docs: TRACK cap is 3
    f_clean = Features(
        situation_id=sit.id,
        deterministic={},
        reader={"fee_mentioned": False, "requires_personal_docs": False},
        reader_ok=True,
        featurizer_version="v1",
        features_hash="h1",
    )
    assert radar_pack.level_cap("TRACK", sit, f_clean) == 3

    # With fee mentioned: cap must drop to 1
    f_fee = Features(
        situation_id=sit.id,
        deterministic={},
        reader={"fee_mentioned": True, "requires_personal_docs": False},
        reader_ok=True,
        featurizer_version="v1",
        features_hash="h2",
    )
    assert radar_pack.level_cap("TRACK", sit, f_fee) == 1

    # With personal docs: cap must drop to 1
    f_docs = Features(
        situation_id=sit.id,
        deterministic={},
        reader={"fee_mentioned": False, "requires_personal_docs": True},
        reader_ok=True,
        featurizer_version="v1",
        features_hash="h3",
    )
    assert radar_pack.level_cap("TRACK", sit, f_docs) == 1


def test_t_radar_executor_and_undo() -> None:
    """T-RADAR: Tracks and dismisses opportunities in SimWorld tracker table with undo."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        world = SimWorld(str(Path(tmp_dir) / "world.db"))
        try:
            act_track = Action(
                id="act-rad-1",
                proposal_id="prop-rad-1",
                pack="radar",
                type="TRACK",
                params={
                    "entry_id": "opp-nsf-1",
                    "title": "NSF Graduate Research Fellowship",
                    "organizer": "NSF",
                    "opp_type": "fellowship",
                    "deadline_date": "2026-10-15",
                    "official_url": "https://nsfgrfp.org",
                },
                level_required=2,
                recallable=True,
                status=ActionStatus.PENDING,
                hold_until=None,
                undo=None,
                created_at="2026-03-01T12:00:00Z",
                updated_at="2026-03-01T12:00:00Z",
            )

            # 1. Execute TRACK
            res = execute_radar_action(act_track, world)
            assert res.success is True
            entries = world.get_tracker_entries()
            assert len(entries) == 1
            assert entries[0]["id"] == "opp-nsf-1"
            assert entries[0]["status"] == "TRACKED"

            # 2. Undo TRACK
            act_track_with_undo = act_track.model_copy(update={"undo": res.undo_data})
            undo_res = undo_radar_action(act_track_with_undo, world)
            assert undo_res.success is True
            assert len(world.get_tracker_entries()) == 0

            # 3. Execute DISMISS
            act_dismiss = Action(
                id="act-rad-2",
                proposal_id="prop-rad-2",
                pack="radar",
                type="DISMISS",
                params={"entry_id": "opp-nsf-1", "title": "NSF GRFP", "organizer": "NSF"},
                level_required=2,
                recallable=True,
                status=ActionStatus.PENDING,
                hold_until=None,
                undo=None,
                created_at="2026-03-01T12:05:00Z",
                updated_at="2026-03-01T12:05:00Z",
            )
            res_dis = execute_radar_action(act_dismiss, world)
            assert res_dis.success is True
            entries = world.get_tracker_entries(status="DISMISSED")
            assert len(entries) == 1
            assert entries[0]["status"] == "DISMISSED"
        finally:
            world.close()


def test_t_radar_digest_generation() -> None:
    """T-RADAR: Periodic digest generation validates all citations against actual tracker records."""
    entries = [
        {
            "n": 1,
            "title": "NASA Space Tech Fellowship",
            "organiser": "NASA",
            "deadline_date": "2026-09-01",
            "official_url": "https://nasa.gov/fellowship",
            "fee_flag": False,
        }
    ]
    # Code fallback generation
    fallback = generate_radar_digest(entries)
    assert "[1] NASA Space Tech Fellowship by NASA" in fallback
    assert "2026-09-01" in fallback

    # Validation: valid digest citing [1] and valid date
    valid_text = "Check out [1] with deadline 2026-09-01 at https://nasa.gov/fellowship."
    is_valid, err = validate_radar_digest(valid_text, entries)
    assert is_valid is True
    assert err == "ok"

    # Validation failure: hallucinated date or uncited [2]
    invalid_text = "Check out [2] with deadline 2026-12-31."
    is_valid_bad, err_bad = validate_radar_digest(invalid_text, entries)
    assert is_valid_bad is False
    assert "Invalid citation" in err_bad or "Uncited" in err_bad


def test_t_radar_exam_operators() -> None:
    """T-RADAR: Perturbation operators run and validate correctly."""
    base = {
        "title": "Gates Cambridge Scholarship",
        "organizer": "Gates Cambridge Trust",
        "deadline_date": "2026-10-10",
        "fee_mentioned": False,
        "official_url": "https://gatescambridge.org",
    }
    p_fee = apply_radar_code_operator("inject_fee", base)
    assert validate_radar_operator_result("inject_fee", base, p_fee)

    p_jit = apply_radar_code_operator("deadline_jitter", base)
    assert validate_radar_operator_result("deadline_jitter", base, p_jit)


# ==============================================================================
# 5. T-READING: Reading Triage Pack Tests
# ==============================================================================


def test_t_reading_clues_and_class_key() -> None:
    """T-READING: Extracts path kind, content_type, and derives class key."""
    assert extract_path_kind("https://arxiv.org/abs/2601.9999.pdf") == "pdf"
    assert extract_path_kind("https://youtube.com/watch?v=123") == "video"
    assert extract_path_kind("https://github.com/torvalds/linux") == "repo"
    assert extract_path_kind("https://docs.python.org/3/") == "doc"

    raw_reading = {
        "id": "raw-read-1",
        "pack": "reading",
        "item_kind": "link",
        "occurred_at": "2026-03-01T10:00:00Z",
        "payload_json": json.dumps(
            {
                "url": "https://arxiv.org/abs/2601.12345",
                "title": "Scalable RL for Robotics",
                "topic": "ai_ml",
                "content_type": "paper",
                "estimated_reading_minutes": 15,
            }
        ),
    }
    sits = reading_pack.iter_situations(raw_reading)
    assert len(sits) == 1
    assert sits[0].family == "link_triage"


def test_t_reading_executor_and_undo() -> None:
    """T-READING: Files and archives reading items in SimWorld library with clean undo."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        world = SimWorld(str(Path(tmp_dir) / "world.db"))
        try:
            act_file = Action(
                id="act-read-1",
                proposal_id="prop-read-1",
                pack="reading",
                type="FILE_TO_COLLECTION:AI_Research",
                params={
                    "url": "https://arxiv.org/abs/2601.12345",
                    "title": "Scalable RL",
                    "collection": "AI_Research",
                },
                level_required=2,
                recallable=True,
                status=ActionStatus.PENDING,
                hold_until=None,
                undo=None,
                created_at="2026-03-01T12:00:00Z",
                updated_at="2026-03-01T12:00:00Z",
            )

            # 1. Execute FILE_TO_COLLECTION
            res = execute_reading_action(act_file, world)
            assert res.success is True
            entry = world.get_library_entry("https://arxiv.org/abs/2601.12345")
            assert entry is not None
            assert entry["collection"] == "AI_Research"

            # 2. Undo FILE_TO_COLLECTION
            act_file_with_undo = act_file.model_copy(update={"undo": res.undo_data})
            undo_res = undo_reading_action(act_file_with_undo, world)
            assert undo_res.success is True
            entry_after_undo = world.get_library_entry("https://arxiv.org/abs/2601.12345")
            assert entry_after_undo is not None
            assert entry_after_undo["collection"] == "inbox"

            # 3. Execute ARCHIVE_LINK
            act_archive = Action(
                id="act-read-2",
                proposal_id="prop-read-2",
                pack="reading",
                type="ARCHIVE_LINK",
                params={"url": "https://arxiv.org/abs/2601.12345", "title": "Scalable RL"},
                level_required=2,
                recallable=True,
                status=ActionStatus.PENDING,
                hold_until=None,
                undo=None,
                created_at="2026-03-01T12:10:00Z",
                updated_at="2026-03-01T12:10:00Z",
            )
            res_arch = execute_reading_action(act_archive, world)
            assert res_arch.success is True
            entry_arch = world.get_library_entry("https://arxiv.org/abs/2601.12345")
            assert entry_arch is not None
            assert entry_arch["collection"] == "archive"
        finally:
            world.close()


def test_t_reading_resolve_outcomes() -> None:
    """T-READING: Strong resolution on explicit collection filing; Weak leave on window expiration."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        world = SimWorld(str(Path(tmp_dir) / "world.db"))
        try:
            sit = Situation(
                id="sit-read-res-1",
                raw_item_id="raw-read-1",
                pack="reading",
                family="reading_triage",
                variant="",
                occurred_at="2026-03-01T10:00:00Z",
                sender_key="arxiv.org",
                content_hash="h1",
                redacted_text="",
                hands_off_reason=None,
                created_at="2026-03-01T10:00:00Z",
            )

            now_during = datetime(2026, 3, 5, 10, 0, 0, tzinfo=UTC)
            now_after = datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC)

            # Explicit filing observed
            res_file = resolve_reading_outcome(
                sit,
                world,
                now_during,
                raw_payload={"observed_action": "FILE_TO_COLLECTION:Robotics"},
            )
            assert res_file is not None
            assert res_file.observed_action.upper() == "FILE_TO_COLLECTION:ROBOTICS"
            assert res_file.strength == EvidenceStrength.STRONG

            # Unacted before window expires -> unresolved
            res_unacted = resolve_reading_outcome(
                sit,
                world,
                now_during,
                raw_payload={"observed_action": "LEAVE"},
            )
            assert res_unacted is None

            # Unacted after window expires -> LEAVE (WEAK)
            res_weak = resolve_reading_outcome(
                sit,
                world,
                now_after,
                raw_payload={"observed_action": "LEAVE"},
            )
            assert res_weak is not None
            assert res_weak.observed_action == "LEAVE"
            assert res_weak.strength == EvidenceStrength.WEAK
        finally:
            world.close()


def test_t_reading_exam_operators() -> None:
    """T-READING: Perturbation operators run and validate correctly."""
    base = {
        "url": "https://techcrunch.com/2026/03/01/startup-funding",
        "title": "AI Startup Raises Seed",
        "topic": "career",
        "content_type": "article",
    }
    p_topic = apply_reading_code_operator("topic_flip", base)
    assert validate_reading_operator_result("topic_flip", base, p_topic)

    p_ct = apply_reading_code_operator("content_type_swap", base)
    assert validate_reading_operator_result("content_type_swap", base, p_ct)
