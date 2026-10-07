"""Tavily HTTP client for search and extraction.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 3 and docs/CONTRACT.md section 6.
"""

from typing import Any

from probation.config import settings


class TavilyClient:
    """HTTP client communicating with Tavily API for entity vetting and page extraction."""

    def __init__(
        self,
        api_key: str = settings.tavily_api_key,
        base_url: str = settings.tavily_base_url,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        """Perform search query via Tavily API."""
        if not self.api_key:
            return {"results": [], "credits": 0, "status": "no_api_key"}
        # Full implementation in Phase 6b
        return {"results": [], "credits": 1, "status": "ok"}

    def extract(self, url: str) -> dict[str, Any]:
        """Extract markdown content from sanitized URL via Tavily API."""
        if not self.api_key:
            return {"results": [], "credits": 0, "status": "no_api_key"}
        # Full implementation in Phase 6b
        return {"results": [], "credits": 1, "status": "ok"}
