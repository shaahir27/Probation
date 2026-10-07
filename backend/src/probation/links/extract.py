"""Quarantined web page text extraction.

Authority: docs/CONTRACT.md invariants I-22, I-26 and docs/TAVILY_AND_NEW_PACKS.md section 7.
Raw web text is untrusted: only a quarantined extractor reads it, and the writer never sees it.
"""

from typing import Any


def extract_quarantined_fields(raw_html_or_markdown: str) -> dict[str, Any]:
    """Parse untrusted page content into validated typed fields."""
    return {}
