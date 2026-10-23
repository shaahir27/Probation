"""Reading Triage domain pack adapter.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 9, docs/PACKS_SPEC.md section 5b, and docs/CONTRACT.md section 5.
"""

import json
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import publicsuffix2

from probation.config import settings
from probation.core.hashing import det_id
from probation.core.history import HistoryView
from probation.core.types import (
    Action,
    ActionSpec,
    ExamOperator,
    ExecResult,
    Features,
    Outcome,
    RawItem,
    ReaderSpec,
    Situation,
)
from probation.links.sanitise import sanitise_url
from probation.packs.base import ExecutorIO, PackAdapter, WorldView
from probation.packs.reading.clues import extract_reading_clues
from probation.packs.reading.exam_ops import READING_EXAM_OPERATORS
from probation.packs.reading.resolver import (
    DEFAULT_READING_WINDOW_DAYS,
    resolve_reading_outcome,
)

READING_ACTION_CATALOG = [
    ActionSpec(type="FILE_TO_COLLECTION", recallable=True, base_cap=3, loss=3.0),
    ActionSpec(type="ARCHIVE_LINK", recallable=True, base_cap=2, loss=6.0),
    ActionSpec(type="LEAVE", recallable=False, base_cap=0, loss=0.0),
]


class ReadingPack(PackAdapter):
    """Reading Triage domain pack adapter."""

    name: str = "reading"
    families: tuple[str, ...] = ("link_triage",)

    def iter_situations(self, raw_item: RawItem | dict[str, Any]) -> list[Situation]:
        """Extract situations from saved links."""
        if isinstance(raw_item, dict):
            raw_id = raw_item["id"]
            pack_name = raw_item.get("pack", "")
            item_kind = raw_item.get("item_kind", "")
            occurred_at = raw_item["occurred_at"]
            payload_str = raw_item.get("payload_json", "{}")
            content_hash = raw_item.get("content_hash", "")
        else:
            raw_id = raw_item.id
            pack_name = raw_item.pack
            item_kind = raw_item.item_kind
            occurred_at = raw_item.occurred_at
            payload_str = raw_item.payload_json
            content_hash = raw_item.content_hash

        if item_kind != "link_saved" and pack_name not in ("reading", "links"):
            return []

        try:
            payload = json.loads(payload_str)
        except Exception:
            payload = {}

        url = str(payload.get("url", "")).strip()
        if not url:
            return []

        clean_url, hands_off_reason = sanitise_url(url)
        hostname = (urlparse(clean_url).hostname or "").lower()
        sld = publicsuffix2.get_sld(hostname)
        sender_key = str(sld).lower() if sld else hostname

        situation_id = det_id("sit", raw_id, "link_triage", "")
        title = payload.get("title") or "Saved Link"
        redacted_text = f"Title: {title}\nURL: {clean_url}"

        sit = Situation(
            id=situation_id,
            pack=self.name,
            family="link_triage",
            raw_item_id=raw_id,
            occurred_at=occurred_at,
            sender_key=sender_key,
            content_hash=content_hash,
            redacted_text=redacted_text,
            hands_off_reason=hands_off_reason,
            variant="",
            created_at=occurred_at,
        )
        return [sit]

    def deterministic_clues(self, s: Situation, hist: HistoryView) -> dict[str, float | str | bool]:
        """Compute clues strictly through HistoryView (Invariant I-6)."""
        raw_items = hist.get_raw_items()
        payload: dict[str, Any] = {}
        for row in raw_items:
            if row["id"] == s.raw_item_id:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    pass
                break
        return extract_reading_clues(s, hist, payload)

    def reader_spec(self) -> ReaderSpec | None:
        """Reading triage relies on quarantined link extractor, not standard reader."""
        return None

    def class_key(self, s: Situation, f: Features) -> str:
        """Derive class key: link|{topic}|{content_type} per TAVILY_AND_NEW_PACKS section 9.1."""
        topic = str(f.deterministic.get("topic", "other"))
        content_type = str(f.deterministic.get("content_type", "article"))
        return f"link|{topic}|{content_type}"

    def action_catalog(self) -> list[ActionSpec]:
        """Return action catalog for Reading Triage."""
        return READING_ACTION_CATALOG

    def level_cap(self, action: str, s: Situation, f: Features | None = None) -> int:
        """Autonomy caps for reading triage actions."""
        if s.hands_off_reason or self.hands_off(s):
            return 0
        act_upper = action.upper()
        if act_upper.startswith("FILE_TO_COLLECTION"):
            return 3
        if act_upper == "ARCHIVE_LINK":
            return 2
        return 0

    def hands_off(self, s: Situation) -> str | None:
        """Return hands-off reason if applicable."""
        return s.hands_off_reason

    def execute(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Execute Reading Triage side-effect into SimWorld library."""
        from probation.packs.reading.executor import execute_reading_action

        return execute_reading_action(a, io)

    def undo(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Undo executed Reading Triage action."""
        from probation.packs.reading.executor import undo_reading_action

        return undo_reading_action(a, io)

    def window(self, s: Situation) -> timedelta:
        """Observation window duration."""
        days = getattr(settings, "reading_window_days", DEFAULT_READING_WINDOW_DAYS)
        return timedelta(days=days)

    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None:
        """Resolve observed outcome from SimWorld library state."""
        return resolve_reading_outcome(s, world, now)

    def resolve_observed_outcome(
        self,
        s: Situation,
        world: WorldView,
        now: datetime,
        raw_payload: dict[str, Any] | None,
    ) -> Outcome | None:
        """Resolve observed outcome with the link's source record attached."""
        return resolve_reading_outcome(s, world, now, raw_payload=raw_payload)

    def exam_operators(self) -> list[ExamOperator]:
        """Return perturbation operators for exam board evaluation."""
        return READING_EXAM_OPERATORS


reading_pack = ReadingPack()
