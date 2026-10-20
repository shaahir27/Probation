"""Tavily HTTP client for search and extraction.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 3, docs/CONTRACT.md section 6, and Invariant I-23/I-25.
Tracks credit usage, enforces query guards, retries on 429/5xx, and writes audit log to tavily_calls.
"""

import sqlite3
import time
from typing import Any

import httpx

from probation.config import settings
from probation.core.clock import Clock
from probation.core.hashing import canonical_json, det_id
from probation.db.access import Role, RoleAccess
from probation.web.query_guard import validate_tavily_query


class TavilyClient:
    """HTTP client communicating with Tavily API for entity vetting and extraction."""

    def __init__(
        self,
        api_key: str = settings.tavily_api_key,
        base_url: str = settings.tavily_base_url,
        timeout: float = 10.0,
        max_retries: int = 3,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.conn = conn

    def _check_budget(self) -> tuple[bool, str | None]:
        """Check if daily or monthly Tavily credit/call budget has been reached (Invariant I-25)."""
        if self.conn is None:
            return True, None

        try:
            cur = self.conn.cursor()
            today_prefix = Clock().now().strftime("%Y-%m-%d")
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(credits), 0) FROM tavily_calls WHERE created_at LIKE ?;",
                (f"{today_prefix}%",),
            )
            row = cur.fetchone()
            daily_calls = row[0] if row else 0
            if daily_calls >= settings.tavily_max_calls_per_day:
                return (
                    False,
                    f"Daily call limit reached ({daily_calls}/{settings.tavily_max_calls_per_day})",
                )

            month_prefix = Clock().now().strftime("%Y-%m")
            cur.execute(
                "SELECT COALESCE(SUM(credits), 0) FROM tavily_calls WHERE created_at LIKE ?;",
                (f"{month_prefix}%",),
            )
            row_month = cur.fetchone()
            monthly_credits = float(row_month[0]) if row_month else 0.0
            if monthly_credits >= settings.tavily_monthly_credit_budget:
                return (
                    False,
                    f"Monthly credit budget reached ({monthly_credits:.1f}/{settings.tavily_monthly_credit_budget})",
                )

            return True, None
        except Exception:
            return True, None

    def _log_call(
        self,
        endpoint: str,
        purpose: str,
        query_text: str,
        params: dict[str, Any],
        credits: float,
        ok: bool,
        latency_ms: int,
        situation_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Record outbound Tavily call in tavily_calls audit log (Invariant I-23)."""
        if self.conn is None:
            return

        now_iso = created_at or Clock().now_iso()
        call_id = det_id("tavily_call", endpoint, purpose, query_text, now_iso)
        params_json = canonical_json(params)

        try:
            access = RoleAccess(self.conn, Role.WEBFACTS)
            access.execute_write(
                "tavily_calls",
                """
                INSERT OR IGNORE INTO tavily_calls
                (id, endpoint, purpose, query_text, params_json, credits, ok, latency_ms, situation_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    call_id,
                    endpoint,
                    purpose,
                    query_text,
                    params_json,
                    credits,
                    1 if ok else 0,
                    latency_ms,
                    situation_id,
                    now_iso,
                ),
            )
            access.commit()
        except Exception:
            pass

    def search(
        self,
        query: str,
        purpose: str = "vet_ident",
        max_results: int = 5,
        search_depth: str = "basic",
        situation_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Perform guarded search query via Tavily API."""
        user_tokens = [t.strip() for t in settings.user_name_tokens.split(",") if t.strip()]
        is_safe, reject_reason = validate_tavily_query(query, user_name_tokens=user_tokens)

        params: dict[str, Any] = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }

        if not is_safe:
            self._log_call(
                endpoint="search",
                purpose=purpose,
                query_text=query,
                params=params,
                credits=0.0,
                ok=False,
                latency_ms=0,
                situation_id=situation_id,
                created_at=as_of,
            )
            return {
                "results": [],
                "credits": 0.0,
                "status": "not_checked",
                "error": reject_reason,
            }

        budget_ok, budget_reason = self._check_budget()
        if not budget_ok:
            self._log_call(
                endpoint="search",
                purpose=purpose,
                query_text=query,
                params=params,
                credits=0.0,
                ok=False,
                latency_ms=0,
                situation_id=situation_id,
                created_at=as_of,
            )
            return {
                "results": [],
                "credits": 0.0,
                "status": "not_checked",
                "error": budget_reason,
            }

        if not self.api_key:
            return {
                "results": [],
                "credits": 0.0,
                "status": "not_checked",
                "error": "TAVILY_API_KEY not configured",
            }

        start_time = time.perf_counter()
        req_body = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(f"{self.base_url}/search", json=req_body)
                    latency_ms = int((time.perf_counter() - start_time) * 1000)

                    if resp.status_code == 200:
                        data = resp.json()
                        credits = float(data.get("usage", {}).get("credits", 1.0))
                        results = data.get("results", [])
                        self._log_call(
                            endpoint="search",
                            purpose=purpose,
                            query_text=query,
                            params=params,
                            credits=credits,
                            ok=True,
                            latency_ms=latency_ms,
                            situation_id=situation_id,
                            created_at=as_of,
                        )
                        return {
                            "results": results,
                            "credits": credits,
                            "status": "ok",
                        }

                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < self.max_retries - 1:
                            time.sleep(0.5 * (2**attempt))
                            continue

                    self._log_call(
                        endpoint="search",
                        purpose=purpose,
                        query_text=query,
                        params=params,
                        credits=0.0,
                        ok=False,
                        latency_ms=latency_ms,
                        situation_id=situation_id,
                        created_at=as_of,
                    )
                    return {
                        "results": [],
                        "credits": 0.0,
                        "status": "not_checked",
                        "error": f"HTTP {resp.status_code}: {resp.text}",
                    }
            except Exception as exc:
                if attempt < self.max_retries - 1:
                    time.sleep(0.5 * (2**attempt))
                    continue
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                self._log_call(
                    endpoint="search",
                    purpose=purpose,
                    query_text=query,
                    params=params,
                    credits=0.0,
                    ok=False,
                    latency_ms=latency_ms,
                    situation_id=situation_id,
                    created_at=as_of,
                )
                return {
                    "results": [],
                    "credits": 0.0,
                    "status": "not_checked",
                    "error": str(exc),
                }

        return {
            "results": [],
            "credits": 0.0,
            "status": "not_checked",
            "error": "Max retries exceeded",
        }

    def extract(
        self,
        url: str,
        purpose: str = "extract_item",
        extract_depth: str = "basic",
        situation_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Extract markdown content from sanitized URL via Tavily API."""
        if not self.api_key:
            return {
                "results": [],
                "credits": 0.0,
                "status": "not_checked",
                "error": "TAVILY_API_KEY not configured",
            }

        params = {"urls": [url], "extract_depth": extract_depth}
        start_time = time.perf_counter()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/extract",
                    json={"api_key": self.api_key, "urls": [url]},
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    credits = float(data.get("usage", {}).get("credits", 1.0))
                    self._log_call(
                        endpoint="extract",
                        purpose=purpose,
                        query_text=url,
                        params=params,
                        credits=credits,
                        ok=True,
                        latency_ms=latency_ms,
                        situation_id=situation_id,
                        created_at=as_of,
                    )
                    return {
                        "results": data.get("results", []),
                        "credits": credits,
                        "status": "ok",
                    }
                else:
                    self._log_call(
                        endpoint="extract",
                        purpose=purpose,
                        query_text=url,
                        params=params,
                        credits=0.0,
                        ok=False,
                        latency_ms=latency_ms,
                        situation_id=situation_id,
                        created_at=as_of,
                    )
                    return {
                        "results": [],
                        "credits": 0.0,
                        "status": "not_checked",
                        "error": f"HTTP {resp.status_code}",
                    }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_call(
                endpoint="extract",
                purpose=purpose,
                query_text=url,
                params=params,
                credits=0.0,
                ok=False,
                latency_ms=latency_ms,
                situation_id=situation_id,
                created_at=as_of,
            )
            return {
                "results": [],
                "credits": 0.0,
                "status": "not_checked",
                "error": str(exc),
            }
