"""Opportunity Radar domain pack adapter.

Authority: docs/TAVILY_AND_NEW_PACKS.md section 8 and docs/CONTRACT.md section 5.
"""

import json
from datetime import datetime, timedelta
from typing import Any

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
from probation.packs.base import ExecutorIO, PackAdapter, WorldView
from probation.packs.radar.clues import (
    extract_radar_clues,
)
from probation.packs.radar.exam_ops import RADAR_EXAM_OPERATORS
from probation.packs.radar.executor import execute_radar_action, undo_radar_action
from probation.packs.radar.resolver import DEFAULT_RADAR_WINDOW_DAYS, resolve_radar_outcome

RADAR_ACTION_CATALOG = [
    ActionSpec(type="TRACK", recallable=True, base_cap=3, loss=3.0),
    ActionSpec(type="DISMISS", recallable=True, base_cap=2, loss=8.0),
    ActionSpec(type="LEAVE", recallable=False, base_cap=0, loss=0.0),
]

OPPORTUNITY_READER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "opp_type",
        "topic",
        "organiser_name",
        "opportunity_name",
        "deadline_text",
        "fee_mentioned",
        "requires_personal_docs",
    ],
    "properties": {
        "opp_type": {
            "type": "string",
            "enum": [
                "hackathon",
                "internship",
                "job",
                "scholarship",
                "competition",
                "conference",
                "workshop",
                "other",
            ],
        },
        "topic": {
            "type": "string",
            "enum": [
                "ai_ml",
                "web_dev",
                "data",
                "cybersecurity",
                "design",
                "finance",
                "core_eng",
                "research",
                "general",
            ],
        },
        "organiser_name": {"type": ["string", "null"], "maxLength": 40},
        "opportunity_name": {"type": ["string", "null"], "maxLength": 60},
        "deadline_text": {"type": ["string", "null"], "maxLength": 40},
        "fee_mentioned": {"type": "boolean"},
        "requires_personal_docs": {"type": "boolean"},
    },
}


class RadarPack(PackAdapter):
    """Opportunity Radar domain pack adapter."""

    name: str = "radar"
    families: tuple[str, ...] = ("opportunity_triage",)

    def iter_situations(self, raw_item: RawItem | dict[str, Any]) -> list[Situation]:
        """Extract situations from opportunity mails or saved links."""
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

        try:
            payload = json.loads(payload_str)
        except Exception:
            payload = {}

        # Trigger 1: Mail with intent == 'opportunity'
        is_opp_mail = item_kind == "mail_in" and (
            payload.get("intent") == "opportunity"
            or "opportunity" in str(payload.get("subject", "")).lower()
            or "hackathon" in str(payload.get("subject", "")).lower()
            or "internship" in str(payload.get("subject", "")).lower()
        )

        # Trigger 2: Link saved for radar
        is_opp_link = pack_name == "radar" or (
            item_kind == "link_saved" and payload.get("variant") == "opportunity"
        )

        if not is_opp_mail and not is_opp_link:
            return []

        variant = "link" if is_opp_link else "mail"
        sender_key = payload.get("from") or payload.get("url") or ""
        if "@" in sender_key:
            sender_key = sender_key.split("@")[-1].strip().lower()

        situation_id = det_id("sit", raw_id, "opportunity_triage", variant)
        subject = payload.get("subject") or payload.get("title") or "Opportunity"
        body = payload.get("body") or payload.get("description") or ""
        redacted_text = f"Subject: {subject}\n\n{body}"

        sit = Situation(
            id=situation_id,
            pack=self.name,
            family="opportunity_triage",
            raw_item_id=raw_id,
            occurred_at=occurred_at,
            sender_key=sender_key,
            content_hash=content_hash,
            redacted_text=redacted_text,
            hands_off_reason=None,
            variant=variant,
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
        return extract_radar_clues(s, hist, payload)

    def reader_spec(self) -> ReaderSpec:
        """Prompt descriptor for opportunity reader."""
        return ReaderSpec(
            prompt_id="reader.opportunity",
            prompt_version="v1",
            json_schema=OPPORTUNITY_READER_SCHEMA,
            redaction_profile="opportunity",
        )

    def class_key(self, s: Situation, f: Features) -> str:
        """Derive class key: radar|{opp_type}|{organiser_domain_class}."""
        opp_type = "other"
        if f.reader and isinstance(f.reader, dict):
            opp_type = str(f.reader.get("opp_type", "other"))
        org_class = str(f.deterministic.get("organiser_domain_class", "other"))
        return f"radar|{opp_type}|{org_class}"

    def action_catalog(self) -> list[ActionSpec]:
        """Return action catalog for Opportunity Radar."""
        return RADAR_ACTION_CATALOG

    def level_cap(self, action: str, s: Situation, f: Features | None = None) -> int:
        """Apply conditional caps: fee_mentioned, requires_personal_docs, web veto."""
        act_upper = action.upper()
        base_cap = 3 if act_upper == "TRACK" else (2 if act_upper == "DISMISS" else 0)
        if base_cap == 0:
            return 0

        # 1. Reader flags: fee_mentioned or requires_personal_docs -> cap 1
        if f is not None and f.reader and isinstance(f.reader, dict):
            fee_mentioned = bool(f.reader.get("fee_mentioned", False))
            requires_personal_docs = bool(f.reader.get("requires_personal_docs", False))
        else:
            fee_mentioned = True
            requires_personal_docs = True

        if fee_mentioned or requires_personal_docs:
            return min(base_cap, 1)

        return base_cap

    def hands_off(self, s: Situation) -> str | None:
        """Check for strictly forbidden hands-off actions."""
        return s.hands_off_reason

    def execute(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Execute Opportunity Radar side-effect into SimWorld."""
        return execute_radar_action(a, io)

    def undo(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Undo executed Opportunity Radar action."""
        return undo_radar_action(a, io)

    def window(self, s: Situation) -> timedelta:
        """Observation window duration."""
        days = getattr(settings, "radar_window_days", DEFAULT_RADAR_WINDOW_DAYS)
        return timedelta(days=days)

    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None:
        """Resolve observed outcome from SimWorld tracker state."""
        return resolve_radar_outcome(s, world, now)

    def exam_operators(self) -> list[ExamOperator]:
        """Return perturbation operators for exam board evaluation."""
        return RADAR_EXAM_OPERATORS


radar_pack = RadarPack()
