"""Web grounding package: Tavily client, query guard, and entity facts.

Authority: docs/TAVILY_AND_NEW_PACKS.md and docs/CONTRACT.md invariants I-21 to I-26.
CRITICAL INVARIANT: policy.py, evidence.py, and licence.py MUST NEVER import this package.
"""

from probation.web.client import TavilyClient
from probation.web.query_guard import validate_tavily_query
from probation.web.view import WebFactsView

__all__ = ["TavilyClient", "WebFactsView", "validate_tavily_query"]
