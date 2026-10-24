"""Actual pack edit dispatch and code validators; unsupported edits stay invalid."""

from collections.abc import Callable
from typing import Any

from probation.core.types import ExamOperator
from probation.llm.consumers import RegisteredConsumer
from probation.packs.calendar.exam_ops import (
    apply_calendar_operator,
    validate_calendar_operator_result,
)
from probation.packs.files.exam_ops import apply_files_code_operator, validate_files_operator_result
from probation.packs.mail.exam_ops import apply_mail_operator


def mutate_case(
    pack_name: str,
    op: ExamOperator,
    base_text: str,
    raw_payload: dict[str, Any],
    llm_client: RegisteredConsumer | None,
    model_id: str | None,
    mail_validator: Callable[..., bool],
) -> tuple[str, dict[str, Any], bool]:
    mut_text, mut_payload, edit_valid = base_text, dict(raw_payload), False
    # Apply perturbation & run validator
    if pack_name in ("mail", "email"):
        mut_text, mut_payload = apply_mail_operator(
            op.name,
            base_text,
            raw_payload,
            llm_client=llm_client,
            model=model_id,
        )
        edit_valid = mail_validator(
            op.name,
            base_text,
            mut_text,
            original_payload=raw_payload,
            mutated_payload=mut_payload,
        )
    elif pack_name in ("cal", "calendar"):
        mut_payload = apply_calendar_operator(
            op.name,
            raw_payload,
            llm_client=llm_client,
            model=model_id,
        )
        edit_valid = validate_calendar_operator_result(op.name, raw_payload, mut_payload)
        mut_text = str(mut_payload.get("description") or mut_payload.get("title") or "")
        if op.name == "introduce_conflict":
            # A payload counter is not an accepted-event history overlay.
            edit_valid = False
    elif pack_name in ("file", "files"):
        raw_payload = dict(raw_payload)
        raw_payload.setdefault("name", raw_payload.get("filename", ""))
        raw_payload.setdefault("size", raw_payload.get("size_bytes", 0))
        mut_payload = apply_files_code_operator(op.name, raw_payload)
        edit_valid = validate_files_operator_result(op.name, raw_payload, mut_payload)
        mut_text = str(mut_payload.get("name") or "")

    elif pack_name in {"radar", "reading", "link"}:
        from probation.engine.exam_other_ops import apply_other_operator

        mut_text, mut_payload, edit_valid = apply_other_operator(
            pack_name,
            op,
            raw_payload,
            llm_client if isinstance(llm_client, RegisteredConsumer) else None,
        )

    return mut_text, mut_payload, edit_valid
