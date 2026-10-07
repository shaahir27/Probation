"""Entity facts derivation rules.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 5.
"""

from typing import Any


def derive_entity_facts(domain: str, search_results: dict[str, Any]) -> dict[str, Any]:
    """Derive entity facts (status, lookalike detection, official candidates)."""
    return {
        "status": "unverified",
        "official_candidates": [],
        "lookalike_of": None,
        "report_hits": 0,
    }
