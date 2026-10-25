"""Unit and isolation tests for Tavily grounding, Query Guard, EntityFacts derivation, and WebFactsView.

Authority: docs/TEST_PLAN.md (T-WEBQ, T-WEBISO, T-VET) and docs/CONTRACT.md invariants I-21 to I-26.
"""

import ast
import sqlite3
from pathlib import Path

from probation.core.enums import GateDecision
from probation.db.tavily_migration import migrate_tavily_accounting
from probation.engine.caps import ACTION_CATALOG
from probation.engine.gate import decide_gate
from probation.web.client import TavilyClient
from probation.web.derive import (
    check_local_brand_list,
    derive_entity_facts,
    extract_domain_label,
    extract_registrable_domain,
    is_lookalike,
    levenshtein_distance,
)
from probation.web.fixtures import load_web_facts_fixtures
from probation.web.query_guard import validate_tavily_query
from probation.web.view import RestrictionOnly, WebFactsView
from probation.workers.webfacts import is_freemail_domain

# ==============================================================================
# T-WEBQ: Query Guard and Privacy Tests (Invariant I-23 & PROMPTS Section 15)
# ==============================================================================


def test_t_webq_allowed_queries() -> None:
    """T-WEBQ: Valid public entity search queries pass the query guard."""
    safe_queries = [
        "google official website",
        "iitm.ac.in official website",
        "atlassian official website",
        "nebius & partners official",
        "st. john's college official",
        "amazon-aws official website",
    ]
    for q in safe_queries:
        ok, reason = validate_tavily_query(q)
        assert ok is True, f"Expected safe query '{q}' to pass, but got: {reason}"
        assert reason is None


def test_t_webq_disallowed_characters() -> None:
    """T-WEBQ: Queries with @, <, >, http, or URLs are immediately rejected."""
    bad_queries = [
        "meena@example.test official website",
        "<script>alert(1)</script>",
        "find me > you",
        "https://google.com official website",
        "http://malicious.example",
        "search for http details",
    ]
    for q in bad_queries:
        ok, reason = validate_tavily_query(q)
        assert ok is False, f"Expected '{q}' to be rejected"
        assert reason is not None


def test_t_webq_numeric_run_rejection() -> None:
    """T-WEBQ: Run of 6 or more digits (potential private ID / phone / account) is rejected."""
    bad_queries = [
        "account 123456 official website",
        "phone 9876543210 support",
        "ref 000000 query",
    ]
    for q in bad_queries:
        ok, reason = validate_tavily_query(q)
        assert ok is False, f"Expected digit run in '{q}' to be rejected"
        assert "6 or more digits" in (reason or "")


def test_t_webq_person_token_rejection() -> None:
    """T-WEBQ: Redacted person token placeholders (<PERSON_n>) are rejected."""
    bad_queries = [
        "<PERSON_1> official website",
        "contact <person_42> email",
    ]
    for q in bad_queries:
        ok, reason = validate_tavily_query(q)
        assert ok is False, f"Expected person tag in '{q}' to be rejected"
        assert "redacted person token" in (reason or "").lower()


def test_t_webq_length_and_token_limits() -> None:
    """T-WEBQ: Queries exceeding 80 characters or 12 tokens are rejected."""
    # 81 characters
    long_char_q = "a" * 81
    ok, reason = validate_tavily_query(long_char_q)
    assert ok is False
    assert "80 characters" in (reason or "")

    # 13 tokens
    thirteen_tokens = "one two three four five six seven eight nine ten eleven twelve thirteen"
    ok, reason = validate_tavily_query(thirteen_tokens)
    assert ok is False
    assert "12" in (reason or "")


def test_t_webq_user_name_tokens_blocked() -> None:
    """T-WEBQ: User name tokens from settings are rejected if present in query."""
    user_tokens = ["Meena", "Krishnamurthy"]
    bad_q = "meena official website"
    ok, reason = validate_tavily_query(bad_q, user_name_tokens=user_tokens)
    assert ok is False
    assert "blocked user name token" in (reason or "")

    # Non-matching user tokens should pass
    good_q = "google official website"
    ok, reason = validate_tavily_query(good_q, user_name_tokens=user_tokens)
    assert ok is True


def test_t_webq_rejected_query_logs_audit_and_makes_no_network(
    memory_db: sqlite3.Connection,
) -> None:
    """T-WEBQ: Rejections are audited without persisting the private query."""
    migrate_tavily_accounting(memory_db)
    client = TavilyClient(api_key="tvly-mock", conn=memory_db)
    bad_q = "query with <PERSON_1> tag"

    res = client.search(bad_q)
    assert res["status"] == "not_checked"
    assert res["credits"] == 0.0

    cur = memory_db.cursor()
    assert (
        cur.execute("SELECT COUNT(*) FROM tavily_calls WHERE query_text = ?", (bad_q,)).fetchone()[
            0
        ]
        == 0
    )
    row = cur.execute("SELECT * FROM tavily_calls WHERE state='rejected'").fetchone()
    assert row is not None and row["query_text"] == "" and row["params_json"] == "{}"
    assert row["ok"] == 0 and row["credits"] == 0.0
    assert row["error_code"] == "query_rejected"


# ==============================================================================
# T-WEBISO: Isolation and Asymmetric Veto Invariants (Invariant I-21)
# ==============================================================================


def test_t_webiso_static_import_graph_check() -> None:
    """T-WEBISO: policy.py, evidence.py, licence.py, features.py must NEVER import web/."""
    engine_dir = Path(__file__).resolve().parent.parent.parent / "src" / "probation" / "engine"
    forbidden_files = [
        engine_dir / "policy.py",
        engine_dir / "evidence.py",
        engine_dir / "licence.py",
        engine_dir / "features.py",
    ]

    violations: list[str] = []
    for py_file in forbidden_files:
        if not py_file.exists():
            continue
        with open(py_file, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "probation.web" in alias.name or alias.name == "web":
                        violations.append(f"{py_file.name}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and ("probation.web" in node.module or node.module == "web"):
                    violations.append(f"{py_file.name}:{node.lineno} imports from {node.module}")

    assert violations == [], (
        f"CONTRACT Invariant I-21 violated! Forbidden web/ imports found in engine: {violations}"
    )


def test_t_webiso_restriction_only_type_has_no_prob_or_evidence_fields() -> None:
    """T-WEBISO: RestrictionOnly schema contains zero probability or evidence fields."""
    forbidden_terms = ["prob", "probability", "weight", "evidence", "licence", "beta", "prior"]
    for field_name in RestrictionOnly.model_fields:
        for term in forbidden_terms:
            assert term not in field_name.lower(), (
                f"RestrictionOnly type contains unauthorized field '{field_name}'"
            )


def test_t_webiso_exhaustive_gate_autonomy_rank_never_increases() -> None:
    """T-WEBISO: For all inputs, web_cap = 1 autonomy rank is <= web_cap = 3 autonomy rank."""
    # Autonomy ranking per ENGINE_SPEC 15.2:
    # ASK/SUGGEST share rank1; HOLD/EXECUTE_UNDO share rank2. All cases remain exhaustive.
    rank_map = {
        GateDecision.SHADOW: 0,
        GateDecision.SUGGEST: 1,
        GateDecision.ASK: 1,
        GateDecision.HOLD_THEN_EXECUTE: 2,
        GateDecision.EXECUTE_UNDO: 2,
        GateDecision.EXECUTE_SILENT: 3,
    }

    test_actions = list(ACTION_CATALOG.keys())
    test_probs = [0.1, 0.6, 0.98]
    test_novels = [False, True]
    test_licence_levels = [0, 1, 2, 3]
    test_base_caps = [0, 1, 2, 3]
    test_hands_off = [None, "executable"]

    for act in test_actions:
        spec = ACTION_CATALOG[act]
        for p in test_probs:
            for nov in test_novels:
                for lic in test_licence_levels:
                    for base_cap in test_base_caps:
                        for h_off in test_hands_off:
                            # Decide gate with web_cap = 3 (no web veto)
                            res_no_veto = decide_gate(
                                action=act,
                                p=p,
                                novel=nov,
                                licence_level=lic,
                                cap=min(base_cap, 3),
                                hands_off=h_off,
                                reader_required=False,
                                reader_ok=True,
                                deterministic_ok=True,
                                loss=spec.loss,
                                attention_cost=1.0,
                                recallable=spec.recallable,
                                audit_draw=0.5,
                                audit_fraction=0.10,
                                budget_ok=True,
                            )

                            # Decide gate with web_cap = 1 (web veto applied)
                            res_veto = decide_gate(
                                action=act,
                                p=p,
                                novel=nov,
                                licence_level=lic,
                                cap=min(base_cap, 1),
                                hands_off=h_off,
                                reader_required=False,
                                reader_ok=True,
                                deterministic_ok=True,
                                loss=spec.loss,
                                attention_cost=1.0,
                                recallable=spec.recallable,
                                audit_draw=0.5,
                                audit_fraction=0.10,
                                budget_ok=True,
                            )

                            rank_no_veto = rank_map[res_no_veto.decision]
                            rank_veto = rank_map[res_veto.decision]

                            # Critical assertion: Web veto can NEVER increase autonomy rank
                            assert rank_veto <= rank_no_veto, (
                                f"Invariant I-21 failure: web veto raised autonomy from {res_no_veto.decision} "
                                f"(rank {rank_no_veto}) to {res_veto.decision} (rank {rank_veto}) for {act}"
                            )


# ==============================================================================
# T-VET: EntityFacts Derivation & Vetting Rules (TAVILY_AND_NEW_PACKS Section 5)
# ==============================================================================


def test_t_vet_domain_extraction_and_levenshtein() -> None:
    """T-VET: Test domain and label extraction and string edit distances."""
    assert extract_registrable_domain("https://mail.google.com/mail/u/0") == "google.com"
    assert extract_registrable_domain("sub.cse.iitm.ac.in") == "iitm.ac.in"
    assert extract_domain_label("google.com") == "google"
    assert extract_domain_label("iitm.ac.in") == "iitm"

    assert levenshtein_distance("google", "g00gle") == 2
    assert levenshtein_distance("paypal", "paypa1") == 1
    assert levenshtein_distance("brand", "brand") == 0


def test_t_vet_homoglyph_and_hyphen_lookalike() -> None:
    """T-VET: Identify homoglyph substitutions and hyphen variations as lookalikes."""
    # Homoglyphs
    assert is_lookalike("g00gle", "google", "g00gle.com", "google.com") is True
    assert is_lookalike("m1crosoft", "microsoft", "m1crosoft.com", "microsoft.com") is True
    assert is_lookalike("paypa1", "paypal", "paypa1.com", "paypal.com") is True

    # Hyphen / separator label containment
    assert (
        is_lookalike("paypal-login-security", "paypal", "paypal-login-security.com", "paypal.com")
        is True
    )

    # Identical domains are not lookalikes of themselves
    assert is_lookalike("google", "google", "google.com", "google.com") is False


def _reviewed_google_fixture() -> dict[str, object]:
    return {
        "google": {
            "active": True,
            "official_domains": ["google.com", "google.co.in", "google.co.uk"],
            "source_url": "https://www.google.com/supported_domains",
            "verified_at": "2026-10-25T00:00:00Z",
        }
    }


def test_t_vet_local_brand_list_pre_check() -> None:
    """T-VET: Local brand list produces immediate status without network calls."""
    brands = _reviewed_google_fixture()

    # Official match
    res_official = check_local_brand_list("google", "google.com", brands=brands)
    assert res_official is not None
    assert res_official["status"] == "confirmed_official"
    assert res_official["origin"] == "local_brand_list"

    # Mismatch with brand token -> immediate lookalike
    res_lookalike = check_local_brand_list("google", "g00gle.com", brands=brands)
    assert res_lookalike is not None
    assert res_lookalike["status"] == "lookalike"
    assert res_lookalike["facts"]["lookalike_of"] == "google.com"


def test_t_vet_derivation_status_precedence_on_fixtures() -> None:
    """T-VET: Verify status precedence: lookalike > reports_found >= 2 > confirmed_official > no_web_presence."""
    # 1. Lookalike beats report hits
    search_mock_lookalike = {
        "status": "ok",
        "results": [
            {"title": "Google Official", "url": "https://google.com", "content": "Search engine."}
        ],
    }
    report_mock = {
        "status": "ok",
        "results": [
            {
                "title": "g00gle.com scam",
                "url": "https://alerts.org/1",
                "content": "g00gle.com phishing fake.",
            },
            {
                "title": "g00gle.com fraud",
                "url": "https://alerts.org/2",
                "content": "g00gle.com warning beware.",
            },
        ],
    }
    facts_la = derive_entity_facts(
        domain="g00gle.com",
        search_results=search_mock_lookalike,
        brand_token="google",
        report_results=report_mock,
        brands=_reviewed_google_fixture(),
    )
    assert facts_la["status"] == "lookalike"
    unrelated = derive_entity_facts(
        "g00gle.com", search_mock_lookalike, brand_token="g00gle", brands=_reviewed_google_fixture()
    )
    assert unrelated["status"] != "lookalike"

    # 2. Reports found (>= 2 hits)
    search_mock_scam = {
        "status": "ok",
        "results": [
            {
                "title": "Jobs Portal",
                "url": "https://fake-jobs.example",
                "content": "fake-jobs.example info",
            }
        ],
    }
    report_mock_scam = {
        "status": "ok",
        "results": [
            {
                "title": "fake-jobs.example scam",
                "url": "https://rep.org/1",
                "content": "fake-jobs.example phishing alert",
            },
            {
                "title": "fake-jobs.example fake",
                "url": "https://independent-report.org/2",
                "content": "fake-jobs.example fraud complaint",
            },
        ],
    }
    facts_rep = derive_entity_facts(
        domain="fake-jobs.example",
        search_results=search_mock_scam,
        report_results=report_mock_scam,
        brands={},
    )
    assert facts_rep["status"] == "reports_found"
    assert facts_rep["facts"]["report_hits"] >= 2

    # 3. Rank/title alone cannot establish reviewed official provenance.
    search_mock_official = {
        "status": "ok",
        "results": [
            {
                "title": "IIT Madras Official Site",
                "url": "https://iitm.ac.in",
                "content": "IIT Madras technical university.",
            }
        ],
    }
    facts_off = derive_entity_facts(
        domain="iitm.ac.in",
        search_results=search_mock_official,
        brand_token="iitm",
        brands={},
    )
    assert facts_off["status"] == "unverified"
    assert facts_off["facts"]["official_candidates"] == []

    # 4. No web presence (empty results)
    facts_none = derive_entity_facts(
        domain="unknown-corp.example",
        search_results={"status": "ok", "results": []},
        brands={},
    )
    assert facts_none["status"] == "no_web_presence"


def test_t_vet_freemail_domain_handling() -> None:
    """T-VET: Personal freemail providers are recognized and not treated as corporate brands."""
    assert is_freemail_domain("user@gmail.com") is True
    assert is_freemail_domain("outlook.com") is True
    assert is_freemail_domain("yahoo.co.in") is True
    assert is_freemail_domain("google.com") is False
    assert is_freemail_domain("iitm.ac.in") is False


def test_t_vet_load_fixtures_and_web_facts_view(memory_db: sqlite3.Connection) -> None:
    """T-VET: Load recorded fixtures and verify WebFactsView restriction caps and reasons."""
    count = load_web_facts_fixtures(memory_db)
    assert count > 0, "Expected to load recorded fixtures into web_facts table"

    view = WebFactsView(memory_db)

    # 1. Confirmed official entity -> web_cap = 3 (no restriction)
    google_facts = view.get_entity_facts("google.com")
    assert google_facts is not None
    assert google_facts.status == "confirmed_official"
    assert google_facts.web_cap == 3
    assert google_facts.reasons == []

    # 2. Lookalike entity -> web_cap = 1 (veto applied)
    g00gle_facts = view.get_entity_facts("g00gle.com")
    assert g00gle_facts is not None
    assert g00gle_facts.status == "lookalike"
    assert g00gle_facts.web_cap == 1
    assert "web_veto:lookalike" in g00gle_facts.reasons

    # 3. Reports found entity -> web_cap = 1 (veto applied)
    scam_facts = view.get_entity_facts("fake-jobs-portal.example")
    assert scam_facts is not None
    assert scam_facts.status == "reports_found"
    assert scam_facts.web_cap == 1
    assert "web_veto:reports_found" in scam_facts.reasons

    # 4. No web presence entity -> web_cap = 1 (veto applied)
    ghost_facts = view.get_entity_facts("unknown-ghost-corp.example")
    assert ghost_facts is not None
    assert ghost_facts.status == "no_web_presence"
    assert ghost_facts.web_cap == 1
    assert "web_veto:no_web_presence" in ghost_facts.reasons
