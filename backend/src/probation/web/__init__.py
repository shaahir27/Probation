"""Web grounding package: Tavily client, query guard, and entity facts.

Authority: docs/TAVILY_AND_NEW_PACKS.md and docs/CONTRACT.md invariants I-21 to I-26.
CRITICAL INVARIANT: policy.py, evidence.py, and licence.py MUST NEVER import this package.
"""

from probation.web.client import TavilyClient
from probation.web.derive import (
    check_local_brand_list,
    derive_entity_facts,
    extract_domain_label,
    extract_registrable_domain,
)
from probation.web.fixtures import load_web_facts_fixtures
from probation.web.query_guard import validate_tavily_query
from probation.web.view import RestrictionOnly, WebFactsView

__all__ = [
    "RestrictionOnly",
    "TavilyClient",
    "WebFactsView",
    "check_local_brand_list",
    "derive_entity_facts",
    "extract_domain_label",
    "extract_registrable_domain",
    "load_web_facts_fixtures",
    "validate_tavily_query",
]
