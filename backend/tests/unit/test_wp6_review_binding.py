"""D3 exact approved mail operations, with synthetic explicit source grants."""

import json

import pytest

from probation.core.enums import GateDecision
from probation.core.review_binding import SourceGrant, build_review_binding, validate_review_binding
from probation.core.types import Proposal
from probation.db.access import Role, RoleAccess
from probation.db.proposals import DraftRecord, persist_proposal
from probation.llm.draft_validation import DraftInvalid, body_hash

T = "2026-01-01T10:00:01Z"
GRANT = SourceGrant("wp1-source", "connection", "account", "owner@test.invalid")


def _review_request(request) -> tuple[str, bool]:
    """Either the reviewed action alone, or that action plus execution authority."""
    param = getattr(request, "param", ("REPLY", False))
    return (param, False) if isinstance(param, str) else param


def _executable_gate(action: str) -> GateDecision:
    """A send holds before it fires; a label change is undone instead of recalled."""
    return (
        GateDecision.HOLD_THEN_EXECUTE
        if action in {"REPLY", "FORWARD"}
        else GateDecision.EXECUTE_UNDO
    )


@pytest.fixture
def review_source(memory_db, basic_situation, request):
    action, autonomous = _review_request(request)
    payload = {
        "from": "sender@test.invalid",
        "body": "Please review the document.",
        "subject": "Review",
        "message_id": "<original@test.invalid>",
        "thread_id": "thread",
    }
    memory_db.execute("UPDATE raw_items SET payload_json=?", (json.dumps(payload),))
    persist_proposal(
        RoleAccess(memory_db, Role.BRAIN),
        Proposal(
            id="review-proposal",
            situation_id=basic_situation.id,
            family="email_action",
            class_key="mail|request|known",
            action=action,
            p_max=0.99,
            novel=False,
            gate=_executable_gate(action) if autonomous else GateDecision.SUGGEST,
            licence_level=2 if autonomous else 1,
            cap=2,
            policy_version="test",
            features_hash="test",
            proposed_at=basic_situation.occurred_at,
            params={
                "draft_proposal_id": "review-proposal",
                "to_addr": "sender@test.invalid",
                "draft_body_hash": body_hash("Thank you for the document."),
            },
        ),
        draft=DraftRecord(
            body_text="Thank you for the document.",
            needs_user_input=False,
            validator_ok=True,
            model_id="fake",
            prompt_version="test",
            created_at=T,
        ),
    )
    memory_db.commit()
    return memory_db


def build(conn, **kwargs):
    return build_review_binding(
        conn,
        "review-proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=T,
        response="edit",
        **kwargs,
    )


def test_archive_approval_has_exact_source_and_grant(review_source):
    binding = build(review_source, edited_action="ARCHIVE")
    assert binding.resource_id == "synthetic-ref"
    assert binding.connection_id == "connection"
    assert binding.account_id == "account"
    assert binding.body_text is None
    validate_review_binding(review_source, "review-proposal", binding, grant=GRANT, as_of=T)
    review_source.execute("UPDATE raw_items SET payload_json='{}'")
    with pytest.raises((DraftInvalid, ValueError)):
        validate_review_binding(review_source, "review-proposal", binding, grant=GRANT, as_of=T)


def test_body_only_edit_stays_reply_and_does_not_mutate_original(review_source):
    binding = build(review_source, edited_body="Thank you for sending this.")
    assert binding.action == "REPLY"
    assert binding.body_text == "Thank you for sending this."
    assert (
        review_source.execute("SELECT body_text FROM drafts").fetchone()[0]
        == "Thank you for the document."
    )


@pytest.mark.parametrize(
    "body", ["Pay 500 USD immediately.", "See https://attacker.invalid", "Hello [NAME]"]
)
def test_edited_draft_uses_real_validators(review_source, body):
    with pytest.raises(DraftInvalid):
        build(review_source, edited_body=body)


def test_missing_or_wrong_grant_does_not_authorize(review_source):
    with pytest.raises((DraftInvalid, ValueError)):
        build_review_binding(
            review_source,
            "review-proposal",
            grant=SourceGrant("other", "connection", "account", "owner@test.invalid"),
            owner_id="owner",
            restriction_revision="0",
            as_of=T,
            response="accept",
        )


def test_forward_is_exact_quoted_source_and_controlled_recipient(review_source):
    with pytest.raises(DraftInvalid):
        build(review_source, edited_action="FORWARD", forward_recipient="friend@test.invalid")
    binding = build(
        review_source,
        edited_action="FORWARD",
        forward_recipient="friend@test.invalid",
        allowed_forward_recipients=("friend@test.invalid",),
        edited_body="For your review.",
    )
    assert binding.recipient == "friend@test.invalid"
    assert binding.body_text.endswith("Please review the document.")
    assert binding.params["from_addr"] == GRANT.from_addr
    validate_review_binding(
        review_source,
        "review-proposal",
        binding,
        grant=GRANT,
        as_of=T,
        allowed_forward_recipients=("friend@test.invalid",),
    )


def test_opaque_resource_cannot_be_used_as_reply_header(review_source):
    review_source.execute(
        "UPDATE raw_items SET payload_json=json_set(payload_json,'$.message_id','opaque')"
    )
    with pytest.raises(DraftInvalid):
        build(review_source)


@pytest.mark.parametrize(
    "mutation", ["attachment", "singular_attachment", "oversize", "recipient_list"]
)
def test_forward_policy_blocks_unsupported_payloads(review_source, mutation):
    payload = json.loads(review_source.execute("SELECT payload_json FROM raw_items").fetchone()[0])
    if mutation == "attachment":
        payload["attachments"] = ["file.pdf"]
    elif mutation == "singular_attachment":
        payload["has_attachment"] = True
    elif mutation == "oversize":
        payload["body"] = "x" * 4800
    review_source.execute("UPDATE raw_items SET payload_json=?", (json.dumps(payload),))
    recipient = (
        "friend@test.invalid, other@test.invalid"
        if mutation == "recipient_list"
        else "friend@test.invalid"
    )
    with pytest.raises(DraftInvalid):
        build(
            review_source,
            edited_action="FORWARD",
            forward_recipient=recipient,
            allowed_forward_recipients=("friend@test.invalid",),
        )


def test_forward_without_intro_roundtrips_exact_binding(review_source):
    binding = build(
        review_source,
        edited_action="FORWARD",
        forward_recipient="friend@test.invalid",
        allowed_forward_recipients=("friend@test.invalid",),
    )
    validate_review_binding(
        review_source,
        "review-proposal",
        binding,
        grant=GRANT,
        as_of=T,
        allowed_forward_recipients=("friend@test.invalid",),
    )
