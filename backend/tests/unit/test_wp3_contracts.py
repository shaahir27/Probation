"""WP3 P01: an outcome type cannot state something that did not happen.

Requirements 7.1.1/7.1.2/7.1.3 turn on one property: a status is a claim about this request, not
a label a caller picks. These tests build the shapes that would let a gate act on a read that
never happened — a validated reader with no fields, a required reader calling itself optional, a
cache hit that also paid for an attempt — and assert the type refuses them.
"""

from dataclasses import FrozenInstanceError, replace

import pytest

from probation.llm.results import (
    FailureCode,
    JobOutcome,
    PredictionStatus,
    Provenance,
    ReaderOutcome,
    ReaderStatus,
    WriterOutcome,
    WriterStatus,
)

PROV = Provenance(
    prompt_id="reader.mail",
    prompt_version="v3",
    model_id=None,
    template_hash=None,
    schema_fingerprint=None,
    context_version="wp3-v1",
    encoder_version="wp2-v1",
    redaction_profile="mail",
)


def validated(fields: dict[str, object] | None = None) -> ReaderOutcome:
    return ReaderOutcome(
        status=ReaderStatus.VALIDATED,
        required=True,
        fields={"intent": "request"} if fields is None else fields,
        provenance=PROV,
    )


def writer(status: WriterStatus, **kwargs: object) -> WriterOutcome:
    return WriterOutcome(
        status=status,
        body=kwargs.get("body", "Sure, that works."),
        needs_user_input=kwargs.get("needs_user_input", status is WriterStatus.NEEDS_USER_INPUT),
        recipient=kwargs.get("recipient", None),
        provenance=PROV,
        validation_notes=kwargs.get("validation_notes", ()),
        attempts=kwargs.get("attempts", 1),
        failure=kwargs.get("failure", None),
    )


def test_a_validated_reader_must_actually_carry_fields() -> None:
    with pytest.raises(ValueError):
        ReaderOutcome(status=ReaderStatus.VALIDATED, required=True, fields=None, provenance=PROV)
    with pytest.raises(ValueError):
        replace(validated(), failure=FailureCode.INVALID_OUTPUT)


def test_a_required_reader_cannot_call_itself_optional() -> None:
    """7.1.2: a pack that needs a read and did not get one must surface as unavailable, not disabled."""
    with pytest.raises(ValueError):
        ReaderOutcome(
            status=ReaderStatus.OPTIONAL_DISABLED, required=True, fields=None, provenance=PROV
        )
    disabled = ReaderOutcome(
        status=ReaderStatus.OPTIONAL_DISABLED, required=False, fields=None, provenance=PROV
    )
    assert disabled.ok and disabled.usable_fields is None


def test_a_failed_reader_carries_no_fields_and_exactly_one_typed_reason() -> None:
    with pytest.raises(ValueError):
        ReaderOutcome(
            status=ReaderStatus.FAILED,
            required=True,
            fields={"intent": "request"},
            provenance=PROV,
            failure=FailureCode.TRANSPORT,
        )
    with pytest.raises(ValueError):
        ReaderOutcome(status=ReaderStatus.FAILED, required=True, fields=None, provenance=PROV)
    failed = ReaderOutcome.failed(True, PROV, FailureCode.BUDGET_DENIED, "cap reached")
    assert failed.status is ReaderStatus.FAILED and not failed.ok
    assert failed.usable_fields is None and failed.failure is FailureCode.BUDGET_DENIED


def test_only_a_validated_read_offers_fields_to_the_model_path() -> None:
    assert validated().usable_fields == {"intent": "request"}
    assert validated().ok and not ReaderOutcome.failed(True, PROV, FailureCode.TRANSPORT, "x").ok


def test_no_outcome_can_be_rewritten_after_the_gate_has_read_it() -> None:
    """I-3 with the ledger: a decision is made on the outcome as produced, never as edited later."""
    with pytest.raises(FrozenInstanceError):
        validated().status = ReaderStatus.FAILED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        writer(WriterStatus.DRAFTED).body = None  # type: ignore[misc]


def test_provenance_describes_a_request_that_never_left_the_process() -> None:
    """7.1.5: absent components are recorded as absent, not guessed at."""
    assert PROV.transport == "none"
    assert PROV.request_id is None and PROV.attempt_id is None
    assert PROV.model_id is None and PROV.template_hash is None
    assert PROV.redaction_counts == {}
    assert set(PROV.as_dict()) == {
        "prompt_id",
        "prompt_version",
        "model_id",
        "template_hash",
        "schema_fingerprint",
        "context_version",
        "encoder_version",
        "redaction_profile",
        "redaction_counts",
        "transport",
        "request_id",
        "attempt_id",
    }


def test_provenance_hands_out_a_copy_of_its_counts() -> None:
    counts = Provenance(**{**PROV.as_dict(), "redaction_counts": {"PERSON": 2, "PHONE": 1}})
    snapshot = counts.as_dict()
    snapshot["redaction_counts"]["PERSON"] = 99
    assert counts.redaction_counts["PERSON"] == 2


def test_a_draft_is_persistable_only_in_the_two_draft_shapes() -> None:
    assert writer(WriterStatus.DRAFTED).persistable
    assert writer(WriterStatus.NEEDS_USER_INPUT, body=None).persistable
    for refused in (WriterStatus.INVALID, WriterStatus.UNAVAILABLE, WriterStatus.FAILED):
        assert not writer(refused, needs_user_input=False, body="plausible text").persistable


def test_writer_flags_cannot_disagree_with_their_own_status() -> None:
    with pytest.raises(ValueError):
        writer(WriterStatus.DRAFTED, needs_user_input=True)
    with pytest.raises(ValueError):
        writer(WriterStatus.NEEDS_USER_INPUT, needs_user_input=False)
    with pytest.raises(ValueError):
        writer(WriterStatus.DRAFTED, body=None)
    with pytest.raises(ValueError):
        writer(WriterStatus.NEEDS_USER_INPUT, attempts=-1, needs_user_input=True, body=None)


def test_job_accounting_is_internally_true_or_refused() -> None:
    """A cache hit dispatches nothing; a dispatch pays for something in exact units."""

    def outcome(**kwargs: object) -> JobOutcome:
        return JobOutcome(
            data={"intent": "request"},
            provenance=PROV,
            cache_hit=kwargs.get("cache_hit", False),
            physical_attempts=kwargs.get("physical_attempts", 1),
            cost_units=kwargs.get("cost_units", 1860),
        )

    assert outcome().cost_units == 1860
    assert outcome(cache_hit=True, physical_attempts=0, cost_units=0).cache_hit
    with pytest.raises(ValueError):
        outcome(cache_hit=True, physical_attempts=1)
    with pytest.raises(ValueError):
        outcome(physical_attempts=0, cost_units=0)
    with pytest.raises(ValueError):
        outcome(cost_units=-1)


def test_prediction_reports_computation_and_never_authority() -> None:
    """7.1.3/I-2: licences are derived elsewhere, so no prediction value may claim one."""
    assert {status.value for status in PredictionStatus} == {
        "computed",
        "cold_start",
        "abstain",
    }


def test_no_contract_can_express_an_action_or_a_licence() -> None:
    forbidden = ("act", "execute", "send", "licence", "license", "autonom", "approve")
    names = (
        {s.name.lower() for s in ReaderStatus}
        | {s.name.lower() for s in WriterStatus}
        | {s.name.lower() for s in PredictionStatus}
    )
    assert [name for name in names for word in forbidden if word in name] == []


def test_failure_codes_are_unique_machine_readable_tokens() -> None:
    values = [code.value for code in FailureCode]
    assert len(values) == len(set(values))
    assert all(v == v.lower() and " " not in v and "<" not in v for v in values)
    for required in ("BUDGET_DENIED", "ASSET_MISMATCH", "CONTEXT_TOO_LARGE", "REASONING_ONLY"):
        assert FailureCode[required].value.replace("_", "").isalnum()
