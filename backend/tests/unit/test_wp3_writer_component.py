"""P08/P10: an unvalidated or differently approved reply must never become ready."""

import pytest

from probation.llm.draft_validation import DraftInvalid, approval_payload, validate_draft


def consumer_for(outputs):
    from dataclasses import replace

    from probation.llm.consumers import RegisteredConsumer
    from probation.llm.gateway import TransportAuthority
    from probation.llm.results import JobOutcome
    from probation.llm.writer import unavailable_provenance

    class FakeGateway:
        def __init__(self):
            self.calls = []

        def dispatch(self, prompt_id, version, **kwargs):
            self.calls.append(kwargs)
            data = outputs[min(len(self.calls) - 1, len(outputs) - 1)]
            return JobOutcome(
                data, replace(unavailable_provenance(), model_id="synthetic-writer"), True, 0, 0
            )

    gateway = FakeGateway()
    return RegisteredConsumer(
        gateway, TransportAuthority(False, "https://offline.invalid")
    ), gateway


@pytest.mark.parametrize(
    "body",
    [
        "Visit https://new.example.test now.",
        "Contact stranger@example.test please.",
        "Please see the attached file.",
        "I will transfer $999 today.",
        "Hello <EMAIL_1>, thank you.",
        "See you on 2027-01-30.",
        "I promise to finish everything.",
        "I'll call you tomorrow.",
        "See you next Tuesday.",
    ],
)
def test_unsafe_reply_is_rejected(body: str) -> None:
    with pytest.raises(DraftInvalid):
        validate_draft(body, "Thank you for reading this update.")


def test_source_supported_data_and_harmless_acknowledgement() -> None:
    validate_draft("Thanks for the update.", "Here is an update.")
    validate_draft("The fee is $25.", "The fee is $25.")
    with pytest.raises(DraftInvalid):
        validate_draft("The fee is $250.", "The fee is $25.")


def test_person_restoration_must_be_authorized() -> None:
    validate_draft("Hello <PERSON_1>, thanks.", "An update", allow_person_tokens=True)
    with pytest.raises(DraftInvalid):
        validate_draft("Hello <PERSON_1>, thanks.", "An update")


def test_review_hash_binds_every_operation_field() -> None:
    base = {
        "proposal_id": "p",
        "draft_hash": "d",
        "connection_id": "c",
        "resource_id": "r",
        "recipient": "sender@example.test",
        "body": "Thanks for your update.",
        "incoming": "Here is an update.",
    }
    first = approval_payload(**base)
    assert first == approval_payload(**base)
    for field in ("proposal_id", "draft_hash", "connection_id", "resource_id", "recipient"):
        changed = dict(base)
        changed[field] += "changed"
        assert approval_payload(**changed).reviewed_hash != first.reviewed_hash
    assert (
        approval_payload(**dict(base, body="Thank you for the update.")).reviewed_hash
        != first.reviewed_hash
    )


def test_editor_rejects_unbound_and_unsafe_body() -> None:
    with pytest.raises(DraftInvalid):
        approval_payload(
            proposal_id="",
            draft_hash="d",
            connection_id="c",
            resource_id="r",
            recipient="a@example.test",
            body="Thanks for the update.",
            incoming="Update",
        )


def test_actual_writer_redacts_and_keeps_plus_recipient() -> None:
    from probation.llm.writer import generate_reply

    consumer, gateway = consumer_for(
        [{"body": "Thanks for the update.", "needs_user_input": False}]
    )
    result = generate_reply(
        consumer,
        incoming="Contact owner@example.test about the update.",
        original_sender="Sender <sender+tag@example.test>",
        situation_id="s",
        preview_warrants_reply=True,
    )
    assert result.persistable and result.recipient == "sender+tag@example.test"
    assert "owner@example.test" not in str(gateway.calls)
    assert result.attempts == 1


def test_writer_regenerates_once_and_drops_invalid_text() -> None:
    from probation.llm.writer import generate_reply

    consumer, gateway = consumer_for(
        [{"body": "Here is https://evil.invalid", "needs_user_input": False}]
    )
    result = generate_reply(
        consumer,
        incoming="An update",
        original_sender="sender@example.test",
        situation_id="s",
        preview_warrants_reply=True,
    )
    assert not result.persistable and result.body is None and len(gateway.calls) == 2
    assert gateway.calls[0]["values"] != gateway.calls[1]["values"]


def test_needs_input_stays_non_autonomous() -> None:
    from probation.llm.results import WriterStatus
    from probation.llm.writer import generate_reply

    consumer, _ = consumer_for([{"body": "Thanks, I will review this.", "needs_user_input": True}])
    result = generate_reply(
        consumer,
        incoming="An update",
        original_sender="sender@example.test",
        situation_id="s",
        preview_warrants_reply=True,
    )
    assert result.status is WriterStatus.NEEDS_USER_INPUT


def test_example_person_cannot_be_restored_into_current_reply() -> None:
    from probation.llm.writer import generate_reply

    consumer, _ = consumer_for([{"body": "Hello <PERSON_2>, thanks.", "needs_user_input": False}])
    result = generate_reply(
        consumer,
        incoming="Hello Alice, here is an update.",
        original_sender="Alice <alice@example.test>",
        situation_id="s",
        display_names=["Alice", "Bob"],
        examples=[("Hello Bob", "Thanks Bob")],
        preview_warrants_reply=True,
    )
    assert not result.persistable and result.body is None


def test_generated_draft_atomic_storage_and_executor_binding(memory_db, basic_situation) -> None:
    import json

    from probation.core.enums import GateDecision
    from probation.core.history import HistoryView
    from probation.core.types import Proposal
    from probation.db.access import Role, RoleAccess
    from probation.db.proposals import persist_proposal
    from probation.db.reply_payload import load_reply_params
    from probation.llm.draft_persistence import prepare_reply_persistence
    from probation.llm.writer import generate_reply

    payload = {"from": "sender@example.test", "body": "An update", "message_id": "m"}
    memory_db.execute("UPDATE raw_items SET payload_json=?", (json.dumps(payload),))
    memory_db.commit()
    consumer, _ = consumer_for([{"body": "Thanks for the update.", "needs_user_input": False}])
    writer = generate_reply(
        consumer,
        incoming=payload["body"],
        original_sender=payload["from"],
        situation_id=basic_situation.id,
        preview_warrants_reply=True,
    )
    proposal = Proposal(
        id="writer-p",
        situation_id=basic_situation.id,
        family="email_action",
        class_key="mail|other|unknown",
        action="REPLY",
        p_max=0.9,
        novel=False,
        gate=GateDecision.SUGGEST,
        policy_version="test",
        features_hash="test",
        params={"message_id": "m"},
        proposed_at=basic_situation.occurred_at,
    )
    prepared, draft = prepare_reply_persistence(
        proposal, basic_situation, HistoryView(memory_db, basic_situation.occurred_at), writer
    )
    brain = RoleAccess(memory_db, Role.BRAIN)
    persist_proposal(brain, prepared, draft=draft)
    ready = load_reply_params(
        RoleAccess(memory_db, Role.EXECUTOR), prepared.id, as_of=basic_situation.occurred_at
    )
    assert ready["body"] == writer.body and ready["to_addr"] == payload["from"]
    assert "Thanks for" not in memory_db.execute("SELECT payload_json FROM ledger").fetchone()[0]
    with pytest.raises(ValueError, match="presence"):
        persist_proposal(brain, prepared)
