"""Registered, bounded, redacted job capability for non-reader consumers.

An ordinary LLMClient is deliberately insufficient: consumers also need the gateway's
durable accounting connection and an explicitly scoped transport authority.
"""

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from probation.llm.catalog import resolve_job
from probation.llm.context import RequestContext, build_request_context
from probation.llm.gateway import JobGateway, TransportAuthority
from probation.llm.results import JobOutcome


def offline_consumer(conn: sqlite3.Connection) -> "RegisteredConsumer":
    """Read genuine validated cached jobs without a credential/client/price-file load."""
    from probation.config import settings

    return RegisteredConsumer(
        JobGateway(None, conn=conn),
        TransportAuthority(False, settings.llm_base_url, "offline cache only"),
    )


@dataclass(frozen=True, slots=True)
class RegisteredConsumer:
    gateway: JobGateway
    authority: TransportAuthority

    def context(
        self,
        prompt_id: str,
        fields: Mapping[str, str],
        *,
        examples: Sequence[tuple[str, str]] = (),
        display_names: Sequence[str] = (),
    ) -> RequestContext:
        return build_request_context(
            resolve_job(prompt_id, "v1"), fields, examples=examples, display_names=display_names
        )

    def run(
        self, context: RequestContext, *, purpose: str, situation_id: str | None = None
    ) -> JobOutcome:
        return self.gateway.dispatch(
            context.spec.prompt_id,
            context.spec.prompt_version,
            values=context.values,
            purpose=purpose,
            authority=self.authority,
            request_limit=context.request_limit,
            redaction_counts=context.counts,
            situation_id=situation_id,
        )

    def call(self, prompt_id: str, fields: Mapping[str, str], *, purpose: str) -> JobOutcome:
        return self.run(self.context(prompt_id, fields), purpose=purpose)
