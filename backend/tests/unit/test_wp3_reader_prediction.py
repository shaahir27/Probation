"""P06/P07 fail-closed reader semantics and shared gate status."""

from probation.llm.reader import read_situation
from probation.llm.results import ReaderStatus


def test_missing_required_reader_fails(memory_db, basic_situation) -> None:
    from probation.core.history import HistoryView

    result = read_situation(
        basic_situation, HistoryView(memory_db, basic_situation.occurred_at), {}
    )
    assert result.required and not result.ok and result.status is ReaderStatus.FAILED


def test_invalid_stub_form_is_not_reader_success(memory_db, basic_situation) -> None:
    from probation.core.history import HistoryView

    result = read_situation(
        basic_situation,
        HistoryView(memory_db, basic_situation.occurred_at),
        {},
        reader_callable=lambda _: ({"intent": "invented"}, True),
    )
    assert not result.ok


def test_file_reader_optional_disabled(memory_db, basic_situation, monkeypatch) -> None:
    from probation.config import settings
    from probation.core.history import HistoryView

    monkeypatch.setattr(settings, "files_reader_enabled", False)
    situation = basic_situation.model_copy(update={"pack": "files", "family": "file_destination"})
    result = read_situation(situation, HistoryView(memory_db, situation.occurred_at), {})
    assert result.ok and not result.required and result.status is ReaderStatus.OPTIONAL_DISABLED


def test_current_item_override_is_read_only_and_bounded(memory_db, basic_situation) -> None:
    import json

    import pytest

    from probation.core.history import HistoryView

    history = HistoryView(memory_db, basic_situation.occurred_at)
    edited = history.with_current_payload(basic_situation.raw_item_id, {"body": "edited"})
    assert (
        json.loads(edited.get_raw_item(basic_situation.raw_item_id)["payload_json"])["body"]
        == "edited"
    )
    assert json.loads(history.get_raw_item(basic_situation.raw_item_id)["payload_json"]) == {}
    with pytest.raises(ValueError):
        HistoryView(memory_db, "2025-01-01T00:00:00Z").with_current_payload(
            basic_situation.raw_item_id, {}
        )


def test_real_gateway_reader_redaction_cache_and_semantic_identity(
    memory_db, basic_situation, monkeypatch
) -> None:
    import json
    from decimal import Decimal

    import httpx

    from probation.config import settings
    from probation.core.clock import Clock
    from probation.core.history import HistoryView
    from probation.llm.budget import BudgetGuard
    from probation.llm.client import LLMClient
    from probation.llm.consumers import RegisteredConsumer
    from probation.llm.feature_pipeline import compute_features, semantic_feature_version
    from probation.llm.gateway import JobGateway, transport_authority

    body = {
        "subject": "Hello Alice",
        "from": "Alice <alice@example.test>",
        "to": "Owner <meena@example.test>",
        "body": "Alice, contact owner@example.test.",
    }
    memory_db.execute("UPDATE raw_items SET payload_json=?", (json.dumps(body),))
    memory_db.commit()
    form = {
        "intent": "fyi",
        "asks_me_to_do_something": False,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": False,
        "urgency": 1,
        "formality": "neutral",
        "asks_for_personal_info": False,
        "looks_automated": False,
    }
    requests = []

    def handler(request):
        requests.append(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(form)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40},
            },
        )

    client = LLMClient(
        api_key="synthetic-key",
        transport=httpx.MockTransport(handler),
        budget_guard=BudgetGuard(
            limit_usd="10", price_table={settings.model_reader: (Decimal("1"), Decimal("1"))}
        ),
        clock=Clock.replay(),
    )
    consumer = RegisteredConsumer(JobGateway(client, conn=memory_db), transport_authority(client))
    history = HistoryView(memory_db, basic_situation.occurred_at)
    first = compute_features(basic_situation, history, consumer=consumer)
    from probation.llm.consumers import offline_consumer

    offline = offline_consumer(memory_db)
    assert offline.gateway.client is None
    second = compute_features(basic_situation, history, consumer=offline)
    assert first.reader_ok and second.reader_ok and first.features_hash == second.features_hash
    assert (
        len(requests) == 1
        and "alice@example.test" not in requests[0]
        and "Alice" not in requests[0]
    )
    old = semantic_feature_version()
    monkeypatch.setattr(settings, "model_reader", settings.model_reader + "-changed")
    assert semantic_feature_version() != old


def test_missing_asset_is_stored_as_failure_not_an_exception(
    memory_db, basic_situation, monkeypatch
) -> None:
    from probation.core.history import HistoryView
    from probation.llm import prompt_loader, reader
    from probation.llm.feature_pipeline import compute_features
    from probation.llm.prompt_loader import PromptAssetError
    from probation.llm.results import FailureCode

    def missing(*args):
        raise PromptAssetError("synthetic missing asset", FailureCode.ASSET_MISSING)

    monkeypatch.setattr(reader, "load_prompt", missing)
    monkeypatch.setattr(prompt_loader, "load_prompt", missing)
    result = compute_features(basic_situation, HistoryView(memory_db, basic_situation.occurred_at))
    assert not result.reader_ok and not result.deterministic["__deterministic_ok"]
    assert result.featurizer_version.endswith(":unavailable")


def test_current_adapter_cold_start_and_cutoff(memory_db, basic_situation) -> None:
    import pytest

    from probation.config import settings
    from probation.core.history import HistoryView
    from probation.engine.policy import Policy
    from probation.engine.prediction import PredictionSnapshot
    from probation.workers.prediction import predict_current

    class NotNovel:
        def score(self, text):
            return False, 0.0

    def form(_):
        return {
            "intent": "fyi",
            "asks_me_to_do_something": False,
            "has_deadline": False,
            "deadline_text": None,
            "money_involved": False,
            "urgency": 1,
            "formality": "neutral",
            "asks_for_personal_info": False,
            "looks_automated": False,
        }, True

    history = HistoryView(memory_db, basic_situation.occurred_at)
    snapshot = PredictionSnapshot(
        Policy("email_action"), NotNovel(), settings.audit_seed, settings.audit_fraction
    )
    features, prediction = predict_current(
        basic_situation,
        history,
        snapshot,
        as_of=basic_situation.occurred_at,
        licence_level=0,
        reader_callable=form,
    )
    assert features.reader_ok and prediction.gate.value == "SHADOW"
    with pytest.raises(ValueError, match="cutoff"):
        predict_current(
            basic_situation, history, snapshot, as_of="2027-01-01T00:00:00Z", licence_level=0
        )


def test_reading_and_chains_require_their_own_readiness(memory_db, basic_situation) -> None:
    """P06 #1 / W3-T03: quarantine and trigger absence is never fabricated reader success."""
    from probation.core.history import HistoryView
    from probation.llm.reader import reader_required
    from probation.llm.results import FailureCode

    assert reader_required("reading")
    assert reader_required("chains")

    reading_sit = basic_situation.model_copy(update={"pack": "reading", "family": "reading_triage"})
    res_reading = read_situation(reading_sit, HistoryView(memory_db, reading_sit.occurred_at), {})
    assert res_reading.required
    assert not res_reading.ok and res_reading.status is ReaderStatus.FAILED
    assert res_reading.failure is FailureCode.CLUES_INVALID
    assert res_reading.reason == "quarantine_unavailable"

    ready = read_situation(
        reading_sit,
        HistoryView(memory_db, reading_sit.occurred_at),
        {"quarantine_ready": True, "quarantine_fields": {"topic": "research"}},
    )
    assert ready.ok and ready.status is ReaderStatus.VALIDATED
    assert dict(ready.fields or {}) == {"topic": "research"}
    # A readiness flag with no validated extractor fields is still an absent read.
    flagged = read_situation(
        reading_sit, HistoryView(memory_db, reading_sit.occurred_at), {"quarantine_ready": True}
    )
    assert not flagged.ok

    chains_sit = basic_situation.model_copy(update={"pack": "chains", "family": "action_chain"})
    res_chains = read_situation(chains_sit, HistoryView(memory_db, chains_sit.occurred_at), {})
    assert res_chains.required
    assert not res_chains.ok and res_chains.status is ReaderStatus.FAILED
    assert res_chains.failure is FailureCode.CLUES_INVALID
    assert res_chains.reason == "inherited_unavailable"

    inherited = read_situation(
        chains_sit,
        HistoryView(memory_db, chains_sit.occurred_at),
        {"inherited_reader_context": {"intent": "request", "has_deadline": True}},
    )
    assert inherited.ok and inherited.status is ReaderStatus.VALIDATED
    assert dict(inherited.fields or {}) == {"intent": "request", "has_deadline": True}


def test_header_conflict_fails_closed_with_specific_reason(memory_db, basic_situation) -> None:
    from probation.config import settings
    from probation.core.history import HistoryView
    from probation.engine.policy import Policy
    from probation.engine.prediction import PredictionSnapshot
    from probation.llm.results import FailureCode
    from probation.workers.prediction import predict_current

    class NotNovel:
        def score(self, text):
            return False, 0.0

    # Sender tier is automated, but reader claims looks_automated is False -> Header Conflict
    def conflicting_form(_):
        return {
            "intent": "fyi",
            "asks_me_to_do_something": False,
            "has_deadline": False,
            "deadline_text": None,
            "money_involved": False,
            "urgency": 1,
            "formality": "neutral",
            "asks_for_personal_info": False,
            "looks_automated": False,
        }, True

    history = HistoryView(memory_db, basic_situation.occurred_at)
    res = read_situation(
        basic_situation,
        history,
        {"sender_tier": "automated", "sender_domain_class": "other"},
        reader_callable=conflicting_form,
    )
    assert not res.ok
    assert res.failure is FailureCode.HEADER_CONFLICT
    assert res.reason == "reader_header_conflict"

    import json

    memory_db.execute(
        "UPDATE raw_items SET payload_json = ? WHERE id = ?",
        (
            json.dumps({"from": "newsletter@domain.com", "has_unsubscribe": True}),
            basic_situation.raw_item_id,
        ),
    )

    snapshot = PredictionSnapshot(
        Policy("email_action"), NotNovel(), settings.audit_seed, settings.audit_fraction
    )
    features, prediction = predict_current(
        basic_situation,
        history,
        snapshot,
        as_of=basic_situation.occurred_at,
        licence_level=2,
        reader_callable=conflicting_form,
    )
    assert not features.reader_ok
    assert prediction.gate.value == "ASK"
    assert "reader_header_conflict" in prediction.reasons


def test_missing_mandatory_context_clues_fails_closed(memory_db, basic_situation) -> None:
    from probation.core.history import HistoryView
    from probation.llm.results import FailureCode

    cal_sit = basic_situation.model_copy(update={"pack": "calendar", "family": "calendar_rsvp"})
    # Omit duration_min
    clues = {"organizer_domain_class": "internal", "start_hour_bucket": "morning"}
    res = read_situation(cal_sit, HistoryView(memory_db, cal_sit.occurred_at), clues)
    assert not res.ok
    assert res.failure is FailureCode.CLUES_INVALID
    assert res.reason == "missing_calendar_context"


def test_features_table_provenance_json_persisted(memory_db, basic_situation) -> None:
    import json

    from probation.core.history import HistoryView
    from probation.llm.feature_pipeline import compute_features
    from probation.workers.brain import extract_features_for_situations

    def dummy_reader(_):
        return {
            "intent": "fyi",
            "asks_me_to_do_something": False,
            "has_deadline": False,
            "deadline_text": None,
            "money_involved": False,
            "urgency": 1,
            "formality": "neutral",
            "asks_for_personal_info": False,
            "looks_automated": False,
        }, True

    hist = HistoryView(memory_db, basic_situation.occurred_at)
    features = compute_features(basic_situation, hist, reader_callable=dummy_reader)
    assert features.provenance_json is not None
    prov = json.loads(features.provenance_json)
    assert prov.get("cutoff") == basic_situation.occurred_at
    assert prov.get("prompt_id") == "reader.mail"

    # Verify insertion in brain worker
    extract_features_for_situations(
        memory_db, situation_id=basic_situation.id, reader_callable=dummy_reader
    )
    row = memory_db.execute(
        "SELECT provenance_json FROM features WHERE situation_id = ?", (basic_situation.id,)
    ).fetchone()
    assert row is not None and row[0] is not None
    db_prov = json.loads(row[0])
    assert db_prov.get("cutoff") == basic_situation.occurred_at


def test_chain_proposal_without_inherited_context_asks(memory_db, basic_situation) -> None:
    """P06 #1: a chain proposal may not claim the trigger's read it was never given."""
    from probation.core.enums import GateDecision
    from probation.packs.chains.proposer import create_chain_situations_and_proposals

    memory_db.execute(
        """INSERT INTO chains(id,trigger_class_key,follow_action,k,n,base_rate,lift,status,created_at)
           VALUES ('wp3-chain','mail|request|known','CREATE_TASK',20,25,0.1,8,'active',
                   '2026-01-01T00:00:00Z'),
                  ('wp3-chain-2','mail|request|known','BLOCK_TIME',20,25,0.1,8,'active',
                   '2026-01-01T00:00:00Z')"""
    )
    memory_db.commit()

    bare = create_chain_situations_and_proposals(
        memory_db, basic_situation, "mail|request|known", basic_situation.occurred_at
    )
    assert len(bare) == 1
    assert bare[0][0].variant == "CREATE_TASK"
    assert bare[0][1].gate is GateDecision.ASK
    assert "inherited_unavailable" in bare[0][1].reasons

    inherited = create_chain_situations_and_proposals(
        memory_db,
        basic_situation,
        "mail|request|known",
        basic_situation.occurred_at,
        reader_features={
            "subject": "Synthetic trigger",
            "has_deadline": True,
            "deadline": "2026-05-03T17:00:00Z",
        },
    )
    assert [s.variant for s, _ in inherited] == ["BLOCK_TIME"]
    assert inherited[0][1].gate is not GateDecision.ASK
    assert "inherited_unavailable" not in inherited[0][1].reasons


def test_pack_catalog_version_and_profile_alignment() -> None:
    from probation.llm.catalog import resolve_job
    from probation.llm.reader import READER_JOBS
    from probation.packs.calendar import calendar_pack
    from probation.packs.mail import mail_pack
    from probation.packs.radar import radar_pack

    assert mail_pack.reader_spec().prompt_version == "v3"
    assert calendar_pack.reader_spec().prompt_version == "v2"
    assert radar_pack.reader_spec().redaction_profile == "mail"

    # P06 #1/#4: a version string is not alignment. Each pack descriptor must name the same
    # job, version, redaction profile and output schema the immutable catalog actually holds.
    for pack in (mail_pack, calendar_pack, radar_pack):
        spec = pack.reader_spec()
        assert spec is not None
        key = READER_JOBS.get(pack.name)
        assert key == (spec.prompt_id, spec.prompt_version)
        job = resolve_job(*key)
        assert job.redaction_profile == spec.redaction_profile
        assert job.output_model().model_json_schema() == spec.json_schema
