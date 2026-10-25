"""D5 entity regressions: reviewed provenance, temporal bounds and privacy."""

import json
import sqlite3
from pathlib import Path

import pytest

from probation.core.clock import Clock, parse_timestamp
from probation.core.history import HistoryView
from probation.core.types import Features, Situation
from probation.web.catalog import reviewed_entry
from probation.web.client import TavilyClient
from probation.web.derive import (
    check_local_brand_list,
    derive_entity_facts,
    extract_registrable_domain,
)
from probation.web.view import WebFactsView
from probation.workers.webfacts import verify_email_entities, vet_entity


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HTTPS://News.Example.CO.UK/path?q=private", "example.co.uk"),
        ("person@sub.example.co.in", "example.co.in"),
        ("https://sub.iitm.ac.in/", "iitm.ac.in"),
        ("https://127.0.0.1/", ""),
        ("https://user:password@example.com/", ""),
        ("bad host.com", ""),
        ("localhost", ""),
    ],
)
def test_d5_domains(raw: str, expected: str) -> None:
    assert extract_registrable_domain(raw) == expected


def test_d5_catalog_reviews_regional_domains_and_rejects_future() -> None:
    entry = reviewed_entry("Google", as_of="2100-01-01T00:00:00Z")
    assert entry is not None
    assert {"google.com", "google.co.in", "google.co.uk"} <= entry.official_domains
    assert reviewed_entry("Google", as_of="2026-10-24T12:00:00Z") is None
    for domain in ("google.com", "google.co.in", "google.co.uk"):
        facts = check_local_brand_list("google", domain)
        assert facts is not None and facts["status"] == "confirmed_official"
        assert facts["facts"]["catalog_source_url"] == entry.source_url


def test_d5_legacy_catalog_has_no_official_authority(tmp_path: Path) -> None:
    path = tmp_path / "brands.json"
    path.write_text(json.dumps({"unreviewed": "example.com"}), encoding="utf-8")
    assert reviewed_entry("unreviewed", path=path) is None
    assert (
        check_local_brand_list("unreviewed", "example.com", brands={"unreviewed": "example.com"})
        is None
    )


def test_d5_unrelated_brand_does_not_create_lookalike() -> None:
    facts = derive_entity_facts(
        "goods.com",
        {
            "status": "ok",
            "results": [
                {"title": "Goods", "url": "https://goods.com/", "content": "Goods resources"}
            ],
        },
        brand_token="goods",
    )
    assert facts["status"] != "lookalike"


def test_d5_report_hits_require_independent_sources() -> None:
    report = {"title": "jobs.example scam", "content": "jobs.example fraud warning"}
    search = {"status": "ok", "results": [{"title": "Jobs", "url": "https://jobs.example"}]}
    facts = derive_entity_facts(
        "jobs.example",
        search,
        report_results={
            "status": "ok",
            "results": [
                {**report, "url": "https://reports.org/one"},
                {**report, "url": "https://reports.org/two"},
            ],
        },
    )
    assert facts["facts"]["report_hits"] == 1
    assert facts["status"] != "reports_found"
    facts = derive_entity_facts(
        "jobs.example",
        search,
        report_results={
            "status": "ok",
            "results": [
                {**report, "url": "https://reports.org/one"},
                {**report, "url": "https://independent.org/two"},
            ],
        },
    )
    assert facts["facts"]["report_hits"] == 2
    assert facts["status"] == "reports_found"


def test_d5_empty_results_are_unavailable_evidence_not_safety_proof() -> None:
    facts = derive_entity_facts("unknown.example", {"status": "ok", "results": []})
    assert facts["status"] == "no_web_presence"
    assert facts["facts"]["evidence_availability"] == "unavailable_in_this_check"
    failed = derive_entity_facts("unknown.example", {"status": "not_checked", "results": []})
    assert failed["status"] == "not_checked"


def _fact(conn: sqlite3.Connection, *, origin: str = "tavily", present: int = 0) -> None:
    conn.execute(
        "INSERT INTO web_facts VALUES (?,?,?,?,?,?,?,?)",
        (
            "example.com",
            "lookalike",
            "{}",
            "[]",
            origin,
            present,
            "2026-10-25T10:00:00Z",
            "2026-10-26T10:00:00Z",
        ),
    )
    conn.commit()


def test_d5_web_view_excludes_future_and_expired_facts(memory_db: sqlite3.Connection) -> None:
    _fact(memory_db)
    view = WebFactsView(memory_db)
    assert view.get_entity_facts("example.com", as_of="2026-10-25T09:59:59Z") is None
    assert view.get_entity_facts("example.com", as_of="2026-10-25T10:00:00Z") is not None
    assert view.get_entity_facts("example.com", as_of="2026-10-26T10:00:00Z") is None
    memory_db.execute("UPDATE web_facts SET fetched_at='2026-10-25T11:00:00+01:00'")
    assert view.get_entity_facts("example.com", as_of="2026-10-25T10:00:00Z") is not None


def test_d5_only_explicit_present_fixture_has_temporal_exception(
    memory_db: sqlite3.Connection,
) -> None:
    _fact(memory_db, origin="fixture", present=1)
    facts = WebFactsView(memory_db).get_entity_facts("example.com", as_of="2020-01-01T00:00:00Z")
    assert facts is not None and facts.web_cap == 1 and facts.present_knowledge
    memory_db.execute("UPDATE web_facts SET origin='tavily'")
    assert (
        WebFactsView(memory_db).get_entity_facts("example.com", as_of="2020-01-01T00:00:00Z")
        is None
    )


class _Client(TavilyClient):
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, **kwargs: object) -> dict[str, object]:
        self.queries.append(query)
        return {"status": "ok", "results": []}


def _email(
    conn: sqlite3.Connection, *, sender: str = "sender@unknown.example"
) -> tuple[Situation, Features]:
    at = "2026-10-25T10:00:00Z"
    conn.execute("INSERT INTO sources VALUES ('source','mail','synthetic','synthetic',?)", (at,))
    payload = json.dumps(
        {
            "from": sender,
            "subject": "Private salary request",
            "body_text": "Private Person needs https://other.example/private/person?token=private-secret",
        }
    )
    conn.execute(
        "INSERT INTO raw_items VALUES ('raw','source','mail','mail_in','native',?,?,?,?)",
        (at, at, payload, "hash"),
    )
    conn.commit()
    situation = Situation(
        id="sit",
        pack="mail",
        family="email_action",
        raw_item_id="raw",
        occurred_at=at,
        sender_key=sender,
        content_hash="hash",
    )
    reader = {
        "intent": "request",
        "asks_me_to_do_something": True,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": False,
        "urgency": 0,
        "formality": "neutral",
        "asks_for_personal_info": False,
        "looks_automated": False,
    }
    features = Features(
        situation_id="sit",
        deterministic={"sender_tier": "unknown"},
        reader=reader,
        reader_ok=True,
        featurizer_version="test",
        features_hash="hash",
    )
    return situation, features


def test_d5_email_requires_validated_reader_and_known_source(memory_db: sqlite3.Connection) -> None:
    situation, features = _email(memory_db)
    clock = Clock.replay(parse_timestamp("2026-10-25T10:00:00Z"))
    client = _Client()
    history = HistoryView(memory_db, clock.now_iso())
    for invalid in (
        features.model_copy(update={"reader_ok": False}),
        features.model_copy(update={"reader": {"intent": "request"}}),
    ):
        result = verify_email_entities(
            memory_db, situation, invalid, history, client=client, clock=clock
        )
        assert result[0].status == "not_checked" and result[0].web_cap == 3
    memory_db.execute("UPDATE raw_items SET known_at='2026-10-25T11:00:00Z'")
    memory_db.commit()
    assert (
        verify_email_entities(memory_db, situation, features, history, client=client, clock=clock)[
            0
        ].status
        == "not_checked"
    )
    assert client.queries == []


def test_d5_email_sends_only_public_domains_and_skips_known_and_freemail(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    situation, features = _email(memory_db)
    clock = Clock.replay(parse_timestamp("2026-10-25T10:00:00Z"))
    client = _Client()
    monkeypatch.setattr(
        HistoryView, "known_entity_senders", lambda self: {"person@unknown.example"}
    )
    result = verify_email_entities(
        memory_db,
        situation,
        features,
        HistoryView(memory_db, clock.now_iso()),
        client=client,
        clock=clock,
    )
    assert result[0].reasons == ["known_domain_excluded"]
    assert client.queries == ["other official website"]
    assert all(
        "private" not in query.casefold()
        and "person" not in query.casefold()
        and "token" not in query.casefold()
        for query in client.queries
    )
    client.queries.clear()
    memory_db.execute(
        "UPDATE raw_items SET payload_json=?", (json.dumps({"body_text": "no links"}),)
    )
    memory_db.commit()
    result = verify_email_entities(
        memory_db,
        situation.model_copy(update={"sender_key": "sender@gmail.com"}),
        features,
        HistoryView(memory_db, clock.now_iso()),
        client=client,
        clock=clock,
    )
    assert result[0].reasons == ["freemail_excluded"]
    assert client.queries == []


def test_d5_live_fact_is_never_backdated_and_cache_does_not_refresh_it(
    memory_db: sqlite3.Connection,
) -> None:
    clock = Clock.replay(parse_timestamp("2026-10-25T10:00:00Z"))
    client = _Client()
    first = vet_entity(
        memory_db,
        "unknown.example",
        as_of="2020-01-01T00:00:00Z",
        tavily_client=client,
        clock=clock,
    )
    assert first["fetched_at"] == "2026-10-25T10:00:00Z"
    assert not memory_db.in_transaction
    clock.advance_seconds(1)
    second = vet_entity(memory_db, "unknown.example", tavily_client=client, clock=clock)
    assert second["cached"] and second["fetched_at"] == first["fetched_at"]
    assert len(client.queries) == 1
    assert (
        WebFactsView(memory_db).get_entity_facts("unknown.example", "2020-01-01T00:00:00Z") is None
    )


def test_d5_unreviewed_legacy_local_cache_has_no_authority(memory_db: sqlite3.Connection) -> None:
    _fact(memory_db, origin="local_brand_list")
    assert WebFactsView(memory_db).get_entity_facts("example.com", "2026-10-25T10:00:00Z") is None
    client = _Client()
    clock = Clock.replay(parse_timestamp("2026-10-25T10:00:00Z"))
    result = vet_entity(memory_db, "example.com", tavily_client=client, clock=clock)
    assert not result["cached"] and result["origin"] == "tavily"
    assert client.queries == ["example official website"]


def test_d5_no_trigger_and_other_pack_never_dispatch(memory_db: sqlite3.Connection) -> None:
    situation, features = _email(memory_db)
    memory_db.execute(
        "UPDATE raw_items SET payload_json=?", (json.dumps({"body_text": "no links"}),)
    )
    memory_db.commit()
    features = features.model_copy(update={"deterministic": {"sender_tier": "known"}})
    clock = Clock.replay(parse_timestamp("2026-10-25T10:00:00Z"))
    client = _Client()
    history = HistoryView(memory_db, clock.now_iso())
    results = verify_email_entities(
        memory_db, situation, features, history, client=client, clock=clock
    )
    assert results[0].status == "not_checked" and results[0].reasons == ["no_trigger"]
    assert (
        verify_email_entities(
            memory_db,
            situation.model_copy(update={"pack": "calendar"}),
            features,
            history,
            client=client,
            clock=clock,
        )
        == []
    )
    assert client.queries == []


def test_d5_guard_rejection_has_no_private_text_in_fact_store(
    memory_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probation.config import settings

    monkeypatch.setattr(settings, "user_name_tokens", "private")
    client = _Client()
    result = vet_entity(
        memory_db,
        "private.example",
        tavily_client=client,
        clock=Clock.replay(parse_timestamp("2026-10-25T10:00:00Z")),
    )
    assert result["status"] == "not_checked" and result["facts"] == {"reason": "query_rejected"}
    assert client.queries == []
    assert memory_db.execute("SELECT COUNT(*) FROM web_facts").fetchone()[0] == 0
