from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from probation.api import gmail_setup
from probation.api.authority import OwnerContext, require_owner
from probation.api.db import connect_api as get_connection
from probation.api.owner_session import OwnerSessionManager
from probation.api.routes import (
    actions,
    boards,
    controls,
    gmail_connector,
    insights,
    items,
    licences,
    queue,
    readiness,
    replay,
    report,
    responses,
    session,
    webfacts,
)
from probation.config import settings
from probation.core.clock import get_clock, operational_clock, use_clock
from probation.db.ledger import ledger_snapshot

Owner = Annotated[OwnerContext, Depends(require_owner)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    gmail_connector.configure_gmail_api_from_env(
        {
            "PROBATION_GMAIL_OWNER_API_KEY": settings.probation_gmail_owner_api_key,
            "PROBATION_GMAIL_OWNER_ID": settings.probation_gmail_owner_id,
            "PROBATION_GMAIL_STORE": str(settings.probation_gmail_store or ""),
            "PROBATION_GMAIL_BIND_HOST": settings.probation_gmail_bind_host,
        }
    )
    yield


app = FastAPI(
    title="Probation API",
    description="Earned autonomy personal AI backend.",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.clock = get_clock()
# Session lifetime is operational wall time, never a frozen replay scenario clock.
app.state.owner_sessions = OwnerSessionManager(clock=operational_clock())


@app.middleware("http")
async def share_context_clock(request: Request, call_next: Any) -> Any:
    """All handlers in a request observe the application's injected clock."""
    with use_clock(request.app.state.clock):
        return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Format HTTP errors according to CONTRACT.md section 9."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Do not echo submitted bodies, headers, or credentials in validation failures."""
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "422", "message": "request_validation_failed"}},
    )


# Register sub-routers
app.include_router(queue.router)
app.include_router(responses.router)
app.include_router(controls.router)
app.include_router(items.router)
app.include_router(actions.router)
app.include_router(licences.router)
app.include_router(report.router)
app.include_router(insights.router)
app.include_router(boards.router)
app.include_router(webfacts.router)
app.include_router(readiness.router)
app.include_router(replay.router)
app.include_router(gmail_connector.router)
app.include_router(gmail_setup.router)
app.include_router(session.router)


@app.get("/health")
@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Liveness only: the process answers, and a read probe proves the database handle opens."""
    if not settings.db_path.exists():
        return {"status": "ok", "service": "probation", "mode": settings.clock_mode}
    conn = get_connection(settings.db_path)
    try:
        return {"status": "ok", "service": "probation", "mode": settings.clock_mode}
    except OSError:
        return {"status": "degraded", "service": "probation", "mode": settings.clock_mode}
    finally:
        conn.close()


@app.get("/api/bootstrap")
def api_bootstrap() -> dict[str, Any]:
    """Return safe UI bootstrap metadata; profile selection remains server-owned."""
    return {
        "version": "d6.v1",
        "profile": settings.app_profile,
        # The selected synthetic profile is a server-owned workspace and needs no owner key.
        "auth_required": settings.app_profile == "private",
    }


@app.get("/api/ledger/verify")
def api_ledger_verify(
    owner: Owner,
) -> dict[str, Any]:
    """Verify hash chain integrity per CONTRACT.md section 9."""
    if not settings.db_path.exists():
        return {
            "ok": True,
            "seq": None,
            "length": 0,
            "head_hash": "0" * 64,
        }

    conn = get_connection(settings.db_path)
    try:
        snapshot = ledger_snapshot(conn)
        return {
            "ok": snapshot.ok,
            "seq": snapshot.first_broken_seq,
            "length": snapshot.length,
            "head_hash": snapshot.head_hash,
        }
    finally:
        conn.close()


@app.get("/api/settings")
def api_settings(owner: Owner) -> dict[str, Any]:
    """Read-only view of effective tunables per CONTRACT.md section 9 and 11."""
    # Exclude secret keys per CONTRACT.md
    safe_settings = {
        "clock_mode": settings.clock_mode,
        "budget_hard_limit_usd": settings.budget_hard_limit_usd,
        "audit_fraction": settings.audit_fraction,
        "l1_min_n": settings.l1_min_n,
        "l1_min_lb": settings.l1_min_lb,
        "l2_min_n": settings.l2_min_n,
        "l2_min_lb": settings.l2_min_lb,
        "l3_min_n": settings.l3_min_n,
        "l3_min_lb": settings.l3_min_lb,
        "cusum_threshold": settings.cusum_threshold,
        "psi_threshold": settings.psi_threshold,
        "exam_valid_days": settings.exam_valid_days,
        "exam_max_per_day": settings.exam_max_per_day,
        "user_tz": settings.user_tz,
    }
    return safe_settings


@app.get("/api/exposure")
def api_exposure(owner: Owner) -> dict[str, Any]:
    """Return text sent to LLMs per item and aggregate counts per CONTRACT.md section 9."""
    if not settings.db_path.exists():
        return {"calls": 0, "total_cost_usd": 0.0, "breakdown": [], "budget": _budget_absent()}

    conn = get_connection(settings.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT call_kind, model_id, COUNT(*) AS calls,
                   SUM(tokens_in) AS total_in, SUM(tokens_out) AS total_out,
                   SUM(cost_usd) AS total_cost
            FROM exposure_log
            GROUP BY call_kind, model_id;
            """
        )
        rows = cursor.fetchall()
        breakdown = []
        total_cost = 0.0
        total_calls = 0
        for r in rows:
            c = float(r["total_cost"] or 0.0)
            cnt = int(r["calls"] or 0)
            total_cost += c
            total_calls += cnt
            breakdown.append(
                {
                    "call_kind": r["call_kind"],
                    "model_id": r["model_id"],
                    "calls": cnt,
                    "tokens_in": int(r["total_in"] or 0),
                    "tokens_out": int(r["total_out"] or 0),
                    "cost_usd": c,
                }
            )

        return {
            "calls": total_calls,
            "total_cost_usd": round(total_cost, 4),
            "breakdown": breakdown,
            "budget": _budget_summary(conn),
        }
    finally:
        conn.close()


def _budget_absent() -> dict[str, Any]:
    return {"available": False, "reason": "database_not_initialized"}


def _budget_summary(conn: Any) -> dict[str, Any]:
    """Separate confirmed charges from estimates and unresolved holds, per CONTRACT.md section 6.

    ``exposure_log`` is reported usage; the durable attempt rows are the money audit. An
    ambiguous attempt is a hold that may already have been charged, so it is never counted as
    free and never counted as confirmed.
    """
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if not {"llm_attempts", "llm_requests"}.issubset(tables):
        return {"available": False, "reason": "spend_records_unavailable"}
    units = 1e8
    confirmed = int(
        conn.execute(
            "SELECT COALESCE(SUM(charged_units),0) FROM llm_attempts WHERE state='reconciled'"
        ).fetchone()[0]
        or 0
    )
    held = conn.execute(
        """SELECT state, COUNT(*) AS attempts, COALESCE(SUM(estimate_units),0) AS estimate
           FROM llm_attempts WHERE state IN ('reserved','dispatched','ambiguous')
           GROUP BY state"""
    ).fetchall()
    estimates = {
        str(row["state"]): {
            "attempts": int(row["attempts"]),
            "usd_estimate": round(int(row["estimate"]) / units, 6),
        }
        for row in held
    }
    unresolved = sum(entry["attempts"] for state, entry in estimates.items() if state != "reserved")
    priced = conn.execute(
        """SELECT COUNT(*) FROM llm_attempts a JOIN llm_requests q ON q.request_id=a.request_id
           WHERE q.result_state='unavailable' AND a.state='never_dispatched'"""
    ).fetchone()[0]
    return {
        "available": True,
        "confirmed_usd": round(confirmed / units, 6),
        "estimated_usd": round(
            sum(int(row["estimate"]) for row in held if row["state"] == "reserved") / units, 6
        ),
        "unresolved_holds": unresolved,
        "holds_by_state": estimates,
        "never_dispatched": int(priced or 0),
        "unit": "usd",
    }
