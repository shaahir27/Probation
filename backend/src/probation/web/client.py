"""Tavily transport with mandatory durable reservations and safe response accounting."""

import re
import sqlite3
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from probation.config import settings
from probation.core.clock import Clock, elapsed_seconds
from probation.links.sanitise import sanitise_url
from probation.llm.budget import BudgetExceeded
from probation.web.accounting import TavilyAccounting, credit_units
from probation.web.query_guard import validate_tavily_query

_PURPOSES = frozenset({"vet_ident", "vet_report", "find_official", "extract_item"})


class TavilyClient:
    """Only transport boundary for paid Search/Extract; absent accounting denies HTTP."""

    def __init__(
        self,
        api_key: str = settings.tavily_api_key,
        base_url: str = settings.tavily_base_url,
        timeout: float = 10.0,
        max_retries: int = 3,
        conn: sqlite3.Connection | None = None,
        clock: Clock | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        accounting_clock: Clock | None = None,
        run_id: str = "d5-nemotron-tavily",
        run_credit_limit: float = 20,
        account_label: str = "primary",
    ) -> None:
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self.timeout, self.max_retries = timeout, min(max(max_retries, 1), 3)
        self.conn, self.clock, self.transport = conn, clock or Clock.live(), transport
        self.accounting = (
            TavilyAccounting(
                conn,
                clock=accounting_clock,
                run_id=run_id,
                run_credit_limit=run_credit_limit,
                account_label=account_label,
            )
            if conn is not None
            else None
        )

    @staticmethod
    def _failure(code: str, **metadata: Any) -> dict[str, Any]:
        return {"results": [], "credits": None, "status": "not_checked", "error": code, **metadata}

    def _reject(self, endpoint: str, purpose: str, code: str) -> dict[str, Any]:
        if self.accounting is not None and purpose in _PURPOSES:
            try:
                self.accounting.reject(endpoint=endpoint, purpose=purpose, safe_code=code)
            except (BudgetExceeded, sqlite3.Error, ValueError):
                return self._failure("accounting_unavailable")
        return self._failure(code, credits=0.0, usage_provenance="not_dispatched")

    def search(
        self,
        query: str,
        purpose: str = "vet_ident",
        max_results: int = 5,
        search_depth: str = "basic",
        situation_id: str | None = None,
        as_of: str | None = None,
        *,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        topic: str = "general",
        time_range: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        user_tokens = [
            token.strip() for token in settings.user_name_tokens.split(",") if token.strip()
        ]
        safe, _ = validate_tavily_query(query, user_name_tokens=user_tokens)
        if not safe:
            return self._reject("search", purpose, "query_rejected")
        if (
            search_depth not in {"basic", "advanced", "fast", "ultra-fast"}
            or not 1 <= max_results <= 5
        ):
            return self._reject("search", purpose, "options_rejected")
        if topic not in {"general", "news", "finance"} or time_range not in {
            None,
            "day",
            "week",
            "month",
            "year",
            "d",
            "w",
            "m",
            "y",
        }:
            return self._reject("search", purpose, "options_rejected")
        params: dict[str, Any] = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_usage": True,
            "auto_parameters": False,
            "topic": topic,
        }
        for key, value in {
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
        }.items():
            if value is not None:
                if len(value) > 20 or any(
                    not validate_tavily_query(domain)[0] or "." not in domain or " " in domain
                    for domain in value
                ):
                    return self._reject("search", purpose, "options_rejected")
                params[key] = value
        for key, option in {
            "time_range": time_range,
            "start_date": start_date,
            "end_date": end_date,
        }.items():
            if option is not None:
                if len(option) > 10 or any(
                    char not in "0123456789-abcdefghijklmnopqrstuvwxyz" for char in option
                ):
                    return self._reject("search", purpose, "options_rejected")
                params[key] = option
        return self._request(
            "search",
            purpose,
            query,
            params,
            2000 if search_depth == "advanced" else 1000,
            situation_id,
        )

    def extract(
        self,
        url: str,
        purpose: str = "extract_item",
        extract_depth: str = "basic",
        situation_id: str | None = None,
        as_of: str | None = None,
        *,
        query: str | None = None,
        chunks_per_source: int = 3,
        format: str = "markdown",
    ) -> dict[str, Any]:
        clean, reason = sanitise_url(url)
        if reason:
            return self._reject("extract", purpose, "url_rejected")
        if (
            extract_depth not in {"basic", "advanced"}
            or format not in {"markdown", "text"}
            or not 1 <= chunks_per_source <= 5
        ):
            return self._reject("extract", purpose, "options_rejected")
        params: dict[str, Any] = {
            "urls": [clean],
            "extract_depth": extract_depth,
            "format": format,
            "include_usage": True,
            "include_images": False,
        }
        if query is not None:
            if not validate_tavily_query(query)[0]:
                return self._reject("extract", purpose, "query_rejected")
            params.update(query=query, chunks_per_source=chunks_per_source)
        # Reserve a whole billing batch even for this single URL.
        return self._request(
            "extract",
            purpose,
            clean,
            params,
            2000 if extract_depth == "advanced" else 1000,
            situation_id,
        )

    def _request(
        self,
        endpoint: str,
        purpose: str,
        query: str,
        params: dict[str, Any],
        maximum_units: int,
        situation_id: str | None,
    ) -> dict[str, Any]:
        if purpose not in _PURPOSES:
            return self._failure("purpose_rejected")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.tavily.com"
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return self._failure("destination_rejected")
        if self.accounting is None:
            return self._failure("accounting_unavailable")
        if not self.api_key:
            return self._failure("credential_unavailable")
        request_id: str | None = None
        for index in range(self.max_retries):
            try:
                attempt = self.accounting.reserve(
                    endpoint=endpoint,
                    purpose=purpose,
                    query=query,
                    params=params,
                    maximum_units=maximum_units,
                    situation_id=situation_id,
                    request_id=request_id,
                )
                request_id = attempt.request_id
                self.accounting.dispatch(attempt)
            except (BudgetExceeded, sqlite3.Error, ValueError):
                return self._failure("accounting_unavailable_or_exhausted")
            start = elapsed_seconds()
            data: dict[str, Any] = {}
            status = 0
            retry_after = 0.25 * (2**index)
            try:
                with httpx.Client(
                    timeout=self.timeout, transport=self.transport, follow_redirects=False
                ) as client:
                    response = client.post(
                        f"{self.base_url}/{endpoint}",
                        json=params,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                status = response.status_code
                if len(response.content) > 2_000_000:
                    raise ValueError("response_too_large")
                parsed_data = response.json()
                if not isinstance(parsed_data, dict):
                    raise ValueError("invalid_response")
                data = parsed_data
                try:
                    retry_after = min(
                        5.0, max(0.0, float(response.headers.get("Retry-After", retry_after)))
                    )
                except (ValueError, OverflowError):
                    pass
            except (httpx.HTTPError, ValueError, TypeError):
                try:
                    metadata = self.accounting.finish(
                        attempt,
                        usage=None,
                        ok=False,
                        latency_ms=int((elapsed_seconds() - start) * 1000),
                        params=params,
                        endpoint=endpoint,
                        error_code="provider_result_unknown",
                    )
                except (BudgetExceeded, sqlite3.Error, ValueError):
                    return self._failure("accounting_reconciliation_failed", attempt_id=attempt.id)
                return self._failure("provider_result_unknown", **metadata)
            results = data.get("results", [])
            valid = isinstance(results, list) and all(isinstance(item, dict) for item in results)
            ok = status == 200 and valid
            audit = dict(params)
            if endpoint == "search" and ok:
                urls: list[str] = []
                sources: list[dict[str, str]] = []
                for item in results[:5]:
                    value = item.get("url")
                    if isinstance(value, str):
                        clean, reason = sanitise_url(value)
                        if not reason:
                            urls.append(clean)
                            title = re.sub(r"<[^>]*>", "", str(item.get("title", "")))
                            title = "".join(char for char in title if char.isprintable())[:300]
                            sources.append({"url": clean, "title": title})
                audit["result_urls"] = urls
                audit["result_sources"] = sources
            usage_data = data.get("usage")
            usage = (
                credit_units(usage_data.get("credits"), exact=True)
                if isinstance(usage_data, dict)
                else None
            )
            try:
                metadata = self.accounting.finish(
                    attempt,
                    usage=usage,
                    ok=ok,
                    latency_ms=int((elapsed_seconds() - start) * 1000),
                    params=audit,
                    endpoint=endpoint,
                    error_code=None if ok else "provider_http_failure",
                )
            except (BudgetExceeded, sqlite3.Error, ValueError):
                return self._failure("accounting_reconciliation_failed", attempt_id=attempt.id)
            if usage is not None and usage > maximum_units:
                return self._failure("provider_usage_exceeds_reservation", **metadata)
            if ok:
                return {"results": results, "status": "ok", **metadata}
            if (
                status in {429, 500, 502, 503, 504}
                and usage is not None
                and index + 1 < self.max_retries
            ):
                time.sleep(retry_after)
                continue
            return self._failure("provider_http_failure", **metadata)
        return self._failure("attempts_exhausted")
