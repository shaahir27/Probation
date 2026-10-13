from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from probation.config import settings
from probation.db.connection import get_connection
from probation.db.ledger import verify_ledger

app = FastAPI(
    title="Probation API",
    description="Earned autonomy personal AI backend.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Format HTTP errors according to CONTRACT.md section 9."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
    )


@app.get("/health")
@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "probation", "mode": settings.clock_mode}


@app.get("/api/ledger/verify")
def api_ledger_verify() -> dict[str, Any]:
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
        intact, corrupted_seq = verify_ledger(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt, hash FROM ledger ORDER BY seq DESC LIMIT 1;")
        row = cursor.fetchone()
        count = row[0] if row else 0
        head_hash = row[1] if row and count > 0 else "0" * 64
        return {
            "ok": intact,
            "seq": corrupted_seq,
            "length": count,
            "head_hash": head_hash,
        }
    finally:
        conn.close()


@app.get("/api/settings")
def api_settings() -> dict[str, Any]:
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
def api_exposure() -> dict[str, Any]:
    """Return text sent to LLMs per item and aggregate counts per CONTRACT.md section 9."""
    if not settings.db_path.exists():
        return {"calls": 0, "total_cost_usd": 0.0, "breakdown": []}

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
        }
    finally:
        conn.close()
