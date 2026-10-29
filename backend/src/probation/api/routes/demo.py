"""Live demo analysis for the synthetic workspace.

One pasted email goes through the same registered reader job, gateway, durable spend
authority and response cache as production. A judge sees a real Token Factory call with
its model, token counts, latency and cost; nothing here is precomputed.

Synthetic profile only. The private API has no route that spends money, so this module
opens a Webfacts-scoped connection solely to record the attempt and its exposure row.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from probation.api.authority import OwnerContext, optional_owner
from probation.config import settings
from probation.core.clock import elapsed_seconds, operational_clock
from probation.db.access import Role
from probation.db.connection import get_role_connection
from probation.db.spend import SpendStore
from probation.db.spend_types import default_lease_owner
from probation.llm.budget import BudgetExceeded, units_to_usd
from probation.llm.client import LLMClient
from probation.llm.consumers import RegisteredConsumer
from probation.llm.gateway import JobFailure, JobGateway, transport_authority

router = APIRouter(prefix="/api", tags=["demo"])

PROMPT_ID = "reader.mail"
PROMPT_VERSION = "v4"


class DemoAnalyzeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=4000)


def demo_owner(request: Request) -> OwnerContext:
    """404 outside the synthetic profile; otherwise the normal owner boundary applies."""
    if settings.app_profile != "synthetic":
        raise HTTPException(status_code=404, detail="not_found")
    owner = optional_owner(request)
    if owner is None or not owner.owner_id:
        raise HTTPException(status_code=403, detail="authenticated_owner_required")
    return owner


Owner = Annotated[OwnerContext, Depends(demo_owner)]


def _reader_fields(text: str) -> dict[str, str]:
    lines = text.replace("\r\n", "\n").strip().split("\n")
    head = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    if head.lower().startswith("subject:"):
        subject = head[8:].strip()
    else:
        subject, body = head, body or head
    return {
        "subject": subject[:200] or "Untitled",
        "sender_domain_class": "unknown",
        "body": body,
    }


@router.post("/demo/analyze")
def demo_analyze(body: DemoAnalyzeBody, owner: Owner) -> dict[str, Any]:
    """Run one registered reader job and return the accounting it actually bought."""
    del owner
    if not settings.llm_api_key:
        raise HTTPException(status_code=503, detail="model_not_configured")
    if not settings.db_path.is_file():
        raise HTTPException(status_code=503, detail="accounting_store_unavailable")

    conn = get_role_connection(settings.db_path, Role.WEBFACTS)
    try:
        try:
            store = SpendStore(
                conn,
                role=Role.WEBFACTS.value,
                lease_owner=default_lease_owner(Role.WEBFACTS.value),
            )
            client = LLMClient(
                api_key=settings.llm_api_key,
                clock=operational_clock(),
                spend_store=store,
            )
            consumer = RegisteredConsumer(
                JobGateway(client, conn=conn),
                transport_authority(client, allow_live_dispatch=True),
            )
            context = consumer.context(
                PROMPT_ID, _reader_fields(body.text), prompt_version=PROMPT_VERSION
            )
            started = elapsed_seconds()
            outcome = consumer.run(context, purpose="demo.analyze")
        except BudgetExceeded as exc:
            raise HTTPException(status_code=503, detail=exc.code) from exc
        except JobFailure as exc:
            raise HTTPException(status_code=503, detail=exc.code.value) from exc
        except httpx.HTTPError as exc:
            # A durable reservation already exists, so the attempt is held as ambiguous by
            # the client; the caller is told the provider was unreachable, never that it was free.
            raise HTTPException(status_code=503, detail="provider_unreachable") from exc
        latency_ms = int((elapsed_seconds() - started) * 1000)
        return {
            "model": outcome.provenance.model_id,
            "tokens_in": outcome.tokens_in,
            "tokens_out": outcome.tokens_out,
            "latency_ms": latency_ms,
            "usd": float(units_to_usd(outcome.cost_units)),
            "result": dict(outcome.data),
            "cached": outcome.cache_hit,
        }
    finally:
        conn.close()
