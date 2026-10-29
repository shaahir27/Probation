"""Live demo analysis for the synthetic workspace.

One pasted email goes through the same registered reader job, gateway, durable spend
authority and response cache as production. A judge sees a real Token Factory call with
its model, token counts, latency and cost; nothing here is precomputed.

Synthetic profile only. The private API has no route that spends money, so this module
opens a Webfacts-scoped connection solely to record the attempt and its exposure row.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from probation.api.authority import OwnerContext, optional_owner
from probation.config import settings
from probation.core.clock import configure_clock_collation, elapsed_seconds, operational_clock
from probation.db.access import Role
from probation.db.connection import get_role_connection
from probation.db.demo_reset import ensure_resettable
from probation.db.spend import SpendStore
from probation.db.spend_types import default_lease_owner
from probation.llm.budget import BudgetExceeded, units_to_usd
from probation.llm.client import LLMClient
from probation.llm.consumers import RegisteredConsumer
from probation.llm.gateway import JobFailure, JobGateway, transport_authority

router = APIRouter(prefix="/api", tags=["demo"])

PROMPT_ID = "reader.mail"
PROMPT_VERSION = "v4"
SNAPSHOT_DIR = Path(__file__).resolve().parents[5] / "demo" / "seed"
RESET_COOLDOWN_S = 5.0
_last_reset_at = 0.0


class DemoAnalyzeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=4000)


def demo_profile() -> None:
    """404 outside the synthetic profile, before any credential is considered."""
    if settings.app_profile != "synthetic":
        raise HTTPException(status_code=404, detail="not_found")


def demo_owner(
    _profile: Annotated[None, Depends(demo_profile)],
    owner: Annotated[OwnerContext | None, Depends(optional_owner)],
) -> OwnerContext:
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
            if isinstance(exc.__cause__, BudgetExceeded):
                raise HTTPException(status_code=503, detail=exc.__cause__.code) from exc
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
            "redaction_counts": dict(outcome.provenance.redaction_counts),
            "cached": outcome.cache_hit,
        }
    finally:
        conn.close()


_snapshot_rows: tuple[int, int] | None = None


def _snapshot_rows_count() -> tuple[int, int] | None:
    """Ledger and response row counts of the shipped snapshot, read once, for drift detection.

    Decisions land in ``user_responses`` at once while ledger rows arrive only when a
    resolver settles them, and the demo container runs no resolver, so both are compared.
    """
    global _snapshot_rows
    if _snapshot_rows is not None:
        return _snapshot_rows
    source = SNAPSHOT_DIR / "engine.db"
    if not source.is_file():
        return None
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        configure_clock_collation(conn)
        ledger = int(conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0])
        responses = int(conn.execute("SELECT COUNT(*) FROM user_responses").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    _snapshot_rows = (ledger, responses)
    return _snapshot_rows


@router.get("/demo/state")
def demo_state(_profile: Annotated[None, Depends(demo_profile)]) -> dict[str, bool]:
    """True once the workspace differs from the shipped snapshot, so the UI can offer a reset."""
    baseline = _snapshot_rows_count()
    if baseline is None:
        return {"drift": True}
    conn = get_role_connection(settings.db_path, Role.EXAMINER)
    try:
        ledger = int(conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0])
        responses = int(conn.execute("SELECT COUNT(*) FROM user_responses").fetchone()[0])
    finally:
        conn.close()
    return {"drift": (ledger, responses) != baseline}


def _restore(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.reset-{os.getpid()}")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)
    for suffix in ("-wal", "-shm"):
        target.with_name(f"{target.name}{suffix}").unlink(missing_ok=True)


@router.post("/demo/reset")
def demo_reset(owner: Owner) -> dict[str, Any]:
    """Restore the shipped synthetic snapshot. Never available in the private profile."""
    del owner
    global _last_reset_at
    now = elapsed_seconds()
    if now - _last_reset_at < RESET_COOLDOWN_S:
        raise HTTPException(status_code=429, detail="reset_too_soon")
    _last_reset_at = now
    store = settings.probation_gmail_store or (
        Path(settings.db_path).parent.parent / "private" / "connectors" / "gmail_metadata.db"
    )
    sources = {
        SNAPSHOT_DIR / "engine.db": Path(settings.db_path),
        SNAPSHOT_DIR / "connector_store.db": Path(store),
    }
    if not all(source.is_file() for source in sources):
        raise HTTPException(status_code=503, detail="demo_snapshot_unavailable")
    try:
        ensure_resettable(Path(settings.db_path))
    except BudgetExceeded as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    try:
        for source, target in sources.items():
            _restore(source, target)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="demo_reset_failed") from exc
    return {"ok": True, "restored": [source.name for source in sources]}
