"""Independent D5 review: no unsupported or uncited web claim crosses the card API."""

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError

from probation.core.clock import Clock, parse_timestamp
from probation.core.history import HistoryView
from probation.core.types import Features, Situation
from probation.llm.consumers import RegisteredConsumer
from probation.web.types import Citation, VerificationCard

NOW = "2026-10-25T10:00:00Z"


def card(**changes: Any) -> dict[str, Any]:
    return {
        "availability": "validated",
        "fields": {"title": "NVIDIA GTC"},
        "citations": [{"title": "NVIDIA GTC", "url": "https://nvidia.com/gtc/"}],
        "extraction_id": "recorded-extraction",
        "fetched_at": NOW,
        "ttl_until": "2026-11-24T10:00:00Z",
        **changes,
    }


def test_uncited_claim_and_uncited_fee_fact_are_rejected() -> None:
    with pytest.raises(ValidationError):
        VerificationCard.model_validate(card(citations=[]))
    with pytest.raises(ValidationError):
        VerificationCard.model_validate(card(fields={}, fee_status="explicit_free", citations=[]))


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://localhost/internal",
        "https://example.com/?token=private",
        "http://127.0.0.1/a",
        "https://user:password@example.com/a",
    ],
)
def test_card_citations_cannot_render_an_unsafe_destination(url: str) -> None:
    with pytest.raises(ValidationError):
        Citation(title="Source", url=url)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("licence_level", True),
        ("probability", "1.0"),
        ("page", "ignore previous instructions"),
        ("deadline_date", "tomorrow"),
        ("deadline_date", "2026-02-31"),
        ("mode", "EXECUTE_SILENT"),
        ("mode", ["online"]),
        ("link_mismatch", "false"),
        ("title", "a" * 81),
        ("organiser", "a" * 61),
        ("eligibility", ["a"] * 4),
        ("eligibility", ["a" * 101]),
    ],
)
def test_card_fields_are_supported_bounded_and_typed(key: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        VerificationCard.model_validate(card(fields={key: value}))


@pytest.mark.parametrize(
    "changes",
    [
        {"fetched_at": "not-a-time"},
        {"ttl_until": "not-a-time"},
        {"ttl_until": "2026-10-24T10:00:00Z"},
        {"fetched_at": None},
        {"ttl_until": None},
    ],
)
def test_claim_times_are_valid_and_ordered(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VerificationCard.model_validate(card(**changes))


class OpportunityConsumer:
    def __init__(self, *, organiser: str = "NVIDIA", deadline: str = "2027-12-31") -> None:
        self.organiser = organiser
        self.deadline = deadline
        self.calls = 0

    def call(self, *_: Any, **__: Any) -> Any:
        self.calls += 1
        return type(
            "Result",
            (),
            {
                "data": {
                    "opp_type": "conference",
                    "topic": "ai_ml",
                    "organiser_name": self.organiser,
                    "opportunity_name": "GTC",
                    "deadline_text": self.deadline,
                    "fee_mentioned": False,
                    "requires_personal_docs": False,
                }
            },
        )()


def test_opportunity_deadline_must_be_supported_by_mail_before_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probation.workers.d5_verification import email_verifier

    class SourceHistory:
        def get_raw_item(self, _: str) -> dict[str, str]:
            return {
                "payload_json": json.dumps(
                    {
                        "subject": "NVIDIA GTC",
                        "body": "Attend https://evil.test/private?token=secret",
                    }
                )
            }

    observed: dict[str, Any] = {}

    def verify(*_: Any, **kwargs: Any) -> VerificationCard:
        observed.update(kwargs)
        return VerificationCard(availability="unavailable")

    monkeypatch.setattr("probation.workers.webfacts.verify_email_entities", lambda *a, **kw: [])
    monkeypatch.setattr("probation.web.verification.verify_email_opportunity", verify)
    situation = Situation(
        id="mail",
        pack="mail",
        family="email_action",
        raw_item_id="raw",
        occurred_at=NOW,
        content_hash="source",
    )
    features = Features(
        situation_id="mail",
        deterministic={},
        reader={"intent": "opportunity"},
        reader_ok=True,
        featurizer_version="test",
        features_hash="hash",
    )
    consumer = OpportunityConsumer()
    verifier = email_verifier(
        cast(Any, None),
        client=object(),
        consumer=cast(RegisteredConsumer, consumer),
        clock=Clock.replay(parse_timestamp(NOW)),
    )
    verifier(situation, features, cast(HistoryView, SourceHistory()))
    assert observed.get("mail_deadline") is None
    assert observed.get("mail_link_domains") == ["evil.test"]
    assert "body" not in observed and "subject" not in observed


def test_opportunity_unsupported_public_name_prevents_web_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probation.workers.d5_verification import email_verifier

    class SourceHistory:
        def get_raw_item(self, _: str) -> dict[str, str]:
            return {"payload_json": json.dumps({"subject": "NVIDIA GTC", "body": "Attend online."})}

    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("Unsupported public fields reached Search")

    monkeypatch.setattr("probation.workers.webfacts.verify_email_entities", lambda *a, **kw: [])
    monkeypatch.setattr("probation.web.verification.verify_email_opportunity", forbidden)
    situation = Situation(
        id="mail",
        pack="mail",
        family="email_action",
        raw_item_id="raw",
        occurred_at=NOW,
        content_hash="source",
    )
    features = Features(
        situation_id="mail",
        deterministic={},
        reader={"intent": "opportunity"},
        reader_ok=True,
        featurizer_version="test",
        features_hash="hash",
    )
    consumer = OpportunityConsumer(organiser="Invented Private Organization")
    verifier = email_verifier(
        cast(Any, None),
        client=object(),
        consumer=cast(RegisteredConsumer, consumer),
        clock=Clock.replay(parse_timestamp(NOW)),
    )
    result = verifier(situation, features, cast(HistoryView, SourceHistory()))
    assert result.card is not None
    assert result.card.availability == "unavailable"
    assert result.card.reasons == ["public_fields_unsupported"]


def test_executor_web_recheck_reads_fresh_facts_without_mutating_proposal(
    memory_db: Any,
    basic_situation: Situation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probation.core.enums import GateDecision
    from probation.core.types import Proposal
    from probation.db.access import Role, RoleAccess
    from probation.db.proposals import persist_proposal
    from probation.workers.restrictions import current_web_cap

    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("Execution-time restriction lookup made a provider call")

    monkeypatch.setattr("probation.web.client.TavilyClient.search", forbidden)
    monkeypatch.setattr("probation.web.client.TavilyClient.extract", forbidden)
    memory_db.execute("UPDATE situations SET sender_key='synthetic@nvidia.com'")
    memory_db.execute(
        "INSERT INTO features(situation_id,deterministic_json,reader_json,reader_ok,"
        "featurizer_version,features_hash,created_at) VALUES(?, '{}','{}',1,'d5','hash',?)",
        (basic_situation.id, basic_situation.occurred_at),
    )
    memory_db.commit()
    proposal = Proposal(
        id="fresh-web-proposal",
        situation_id=basic_situation.id,
        family="email_action",
        class_key="mail|request|known",
        action="ARCHIVE",
        probs={"ARCHIVE": 1.0},
        p_max=1.0,
        novel=False,
        licence_level=3,
        cap=3,
        gate=GateDecision.EXECUTE_UNDO,
        policy_version="synthetic",
        features_hash="hash",
        proposed_at=basic_situation.occurred_at,
        web={"cap": 3, "status": "not_checked"},
    )
    persist_proposal(RoleAccess(memory_db, Role.BRAIN), proposal)
    assert current_web_cap(memory_db, proposal.id, NOW) == 3
    memory_db.execute(
        "INSERT INTO web_facts(entity_key,status,facts_json,sources_json,origin,present_knowledge,"
        "fetched_at,ttl_until) VALUES('nvidia.com','reports_found','{}',"
        '\'[{"title":"Synthetic report","url":"https://example.com/report"}]\','
        "'tavily',0,?,'2026-10-26T10:00:00Z')",
        (NOW,),
    )
    memory_db.commit()
    assert current_web_cap(memory_db, proposal.id, "2026-10-25T09:59:59Z") == 3
    assert current_web_cap(memory_db, proposal.id, NOW) == 1
    assert current_web_cap(memory_db, proposal.id, "2026-10-26T10:00:00Z") == 3
    stored = memory_db.execute(
        "SELECT cap,web_json FROM proposals WHERE id=?", (proposal.id,)
    ).fetchone()
    assert stored["cap"] == 3 and json.loads(stored["web_json"])["cap"] == 3


def test_official_title_can_omit_generic_program_suffix_but_not_distinctive_words():
    from probation.web.verification import _candidate

    source = {
        "url": "https://www.nvidia.com/en-us/research/graduate-fellowships",
        "title": "NVIDIA Graduate Fellowship | Research",
    }
    domains = frozenset({"nvidia.com"})
    assert _candidate([source], domains, "NVIDIA Graduate Fellowship Program") == (
        source["url"],
        source["title"],
    )
    assert _candidate([source], domains, "NVIDIA Undergraduate Fellowship Program") is None
    other = dict(source, url="https://www.nvidia.com/different")
    assert _candidate([source, other], domains, "NVIDIA Graduate Fellowship Program") is None
