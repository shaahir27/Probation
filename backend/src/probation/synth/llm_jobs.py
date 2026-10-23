"""Opt-in fictional body pool jobs; never invoked by fixture generation implicitly."""

import re
from typing import Any, Literal

from probation.llm.consumers import RegisteredConsumer


def generate_fictional_text(
    consumer: RegisteredConsumer,
    *,
    kind: Literal["mail_body", "invite"],
    spec: str,
) -> dict[str, Any]:
    # A bounded public fictional specification, not a private mail or persona export.
    if re.search(r"https?://|[\w.+-]+@|\b(?:api[_ -]?key|password|secret|token)\b", spec, re.I):
        raise ValueError("synthetic_spec_not_fictional_public_fields")
    result = consumer.call(f"synth.{kind}", {"spec": spec}, purpose="fictional_pool")
    return dict(result.data)
