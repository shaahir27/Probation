"""PackAdapter protocol defining domain pack capabilities.

Authority: docs/PACKS_SPEC.md section 0 and docs/CONTRACT.md section 5.
"""

from typing import Any, Protocol

from probation.core.history import HistoryView


class PackAdapter(Protocol):
    """Protocol for domain-specific packs (mail, calendar, files, chains, radar, reading)."""

    name: str

    def extract_situations(self, raw_item: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract atomic situations from an ingested raw record."""
        ...

    def extract_deterministic_clues(
        self, situation: dict[str, Any], history: HistoryView
    ) -> dict[str, Any]:
        """Compute clues deterministically strictly through HistoryView (no peeking)."""
        ...

    def get_class_key(self, situation: dict[str, Any], clues: dict[str, Any]) -> str:
        """Derive the partition class key for this situation."""
        ...

    def resolve_outcome(
        self, situation: dict[str, Any], history: HistoryView
    ) -> tuple[str, str, str] | None:
        """Resolve observed user action, strength (STRONG/WEAK), and known_at timestamp."""
        ...
