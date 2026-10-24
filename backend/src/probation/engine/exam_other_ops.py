"""Invoke registered Radar/Reading edits without granting missing suppliers."""

from typing import Any

from probation.core.types import ExamOperator
from probation.llm.consumers import RegisteredConsumer


def apply_other_operator(
    pack: str, op: ExamOperator, payload: dict[str, Any], consumer: RegisteredConsumer | None
) -> tuple[str, dict[str, Any], bool]:
    if pack == "radar":
        from probation.packs.mail.exam_ops import apply_mail_operator, validate_mail_operator_result
        from probation.packs.radar.exam_ops import (
            apply_radar_code_operator,
            validate_radar_operator_result,
        )

        original = str(payload.get("body", ""))
        if op.name == "paraphrase_body":
            text, changed = apply_mail_operator(op.name, original, payload, llm_client=consumer)
            changed = {**changed, "body": text}
            valid = validate_mail_operator_result(op.name, original, text, payload, changed)
        else:
            changed = apply_radar_code_operator(op.name, payload)
            text = str(changed.get("body", ""))
            valid = changed != payload and validate_radar_operator_result(op.name, payload, changed)
        return text, changed, valid
    if pack in {"link", "reading"}:
        from probation.llm.gateway import JobFailure
        from probation.llm.prompt_loader import PromptAssetError
        from probation.packs.reading.exam_ops import (
            apply_reading_code_operator,
            validate_reading_operator_result,
        )

        if op.name == "paraphrase_snippet":
            original = str(payload.get("content_text", ""))
            if consumer is None:
                return original, payload, False
            try:
                result = consumer.call("exam.paraphrase", {"text": original}, purpose="exam_edit")
                text = str(result.data["edited_text"])
            except (JobFailure, PromptAssetError):
                return original, payload, False
            valid = text != original and abs(len(text) - len(original)) <= 0.4 * max(
                1, len(original)
            )
            return text, {**payload, "content_text": text}, valid
        changed = apply_reading_code_operator(op.name, payload)
        return (
            str(changed.get("content_text", "")),
            changed,
            changed != payload and validate_reading_operator_result(op.name, payload, changed),
        )
    return "", payload, False
