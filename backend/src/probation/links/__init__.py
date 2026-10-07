"""Links package: URL sanitisation, hands-off rules, and quarantined extractors.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 7 and docs/CONTRACT.md invariants I-22, I-24, I-26.
"""

from probation.links.sanitise import is_url_hands_off, sanitise_url

__all__ = ["is_url_hands_off", "sanitise_url"]
