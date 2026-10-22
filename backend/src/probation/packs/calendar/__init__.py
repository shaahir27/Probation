"""Calendar domain pack implementing PackAdapter.

Authority: docs/PACKS_SPEC.md section 2 and docs/CONTRACT.md section 5.
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
from probation.llm.jobs import InviteReader
from probation.llm.redact import redact
from probation.packs.base import ExecutorIO, PackAdapter, WorldView
from probation.packs.calendar.clues import extract_calendar_clues
from probation.packs.calendar.exam_ops import CALENDAR_EXAM_OPERATORS
from probation.packs.calendar.resolver import DEFAULT_INVITE_MAX_DAYS, resolve_calendar_outcome
from probation.packs.mail.clues import normalize_address

CALENDAR_ACTION_CATALOG = [
    ActionSpec(type="ACCEPT", recallable=False, base_cap=2, loss=10.0),
    ActionSpec(type="DECLINE", recallable=False, base_cap=2, loss=20.0),
    ActionSpec(type="TENTATIVE", recallable=False, base_cap=2, loss=5.0),
    ActionSpec(type="NO_RESPONSE", recallable=False, base_cap=0, loss=0.0),
    ActionSpec(type="BLOCK_TIME", recallable=True, base_cap=3, loss=3.0),
]

CALENDAR_READER_SCHEMA = InviteReader.model_json_schema()


class CalendarPack(PackAdapter):
    """Calendar domain pack adapter."""

    name: str = "calendar"
    families: tuple[str, ...] = ("invite_rsvp",)

    def __init__(self, user_addresses: list[str] | str | None = None) -> None:
        self.user_addresses: list[str] | None
        if isinstance(user_addresses, str):
            self.user_addresses = [a.strip() for a in user_addresses.split(",") if a.strip()]
        elif user_addresses is not None:
            self.user_addresses = list(user_addresses)
        else:
            self.user_addresses = None

    def iter_situations(self, raw_item: RawItem | dict[str, Any]) -> list[Situation]:
        """Extract atomic situations from an ingested raw record."""
        if isinstance(raw_item, dict):
            raw_id = raw_item["id"]
            item_kind = raw_item.get("item_kind", "")
            occurred_at = raw_item["occurred_at"]
            payload_str = raw_item["payload_json"]
            content_hash = raw_item.get("content_hash", "")
        else:
            raw_id = raw_item.id
            item_kind = raw_item.item_kind
            occurred_at = raw_item.occurred_at
            payload_str = raw_item.payload_json
            content_hash = raw_item.content_hash

        # Only inbound invites create an RSVP situation
        if item_kind != "invite":
            return []

        try:
            payload = json.loads(payload_str)
        except Exception:
            payload = {}

        organizer = payload.get("organizer", "")
        norm_org = normalize_address(organizer)
        if self.user_addresses is not None:
            user_addrs = [normalize_address(a) for a in self.user_addresses]
        else:
            user_addrs = [normalize_address(a) for a in settings.user_addresses.split(",")]

        # Skip if organized by the user
        if any(u in norm_org for u in user_addrs):
            return []

        # Check attendee status at arrival was NEEDS-ACTION
        my_status = str(
            payload.get("my_status")
            or ("NEEDS-ACTION" if item_kind == "invite" else payload.get("status", "NEEDS_ACTION"))
        ).upper()
        if "NEEDS" not in my_status and "ACTION" not in my_status:
            return []

        title = payload.get("title", "")
        desc = payload.get("description", "")
        full_text = f"Title: {title}\nDescription: {desc}"

        # Redact before LLM egress (Invariant I-14)
        redacted = redact(full_text, profile="invite")

        situation_id = det_id("sit", raw_id, "invite_rsvp", "")
        hands_off_reason = self.hands_off_text(full_text)

        sit = Situation(
            id=situation_id,
            pack=self.name,
            family="invite_rsvp",
            raw_item_id=raw_id,
            occurred_at=occurred_at,
            sender_key=norm_org,
            content_hash=content_hash,
            redacted_text=redacted.text,
            hands_off_reason=hands_off_reason,
            variant="",
            created_at=occurred_at,
        )
        return [sit]

    def deterministic_clues(self, s: Situation, hist: HistoryView) -> dict[str, float | str | bool]:
        """Compute all 12 deterministic clues strictly through HistoryView (Invariant I-6)."""
        raw_items = hist.get_raw_items(pack=self.name)
        payload = {}
        for row in raw_items:
            if row["id"] == s.raw_item_id:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    pass
                break
        return extract_calendar_clues(s, hist, payload)

    def reader_spec(self) -> ReaderSpec:
        """Prompt descriptor for calendar reader."""
        return ReaderSpec(
            prompt_id="reader.invite",
            prompt_version="v1",
            json_schema=CALENDAR_READER_SCHEMA,
            redaction_profile="invite",
        )

    def class_key(self, s: Situation, f: Features) -> str:
        """Derive class key: cal|{organizer_tier}|{purpose} per PACKS_SPEC section 2.4."""
        purpose = "other"
        if f.reader and isinstance(f.reader, dict):
            purpose = str(f.reader.get("purpose", "other"))
        org_tier = str(f.deterministic.get("organizer_tier", "unknown"))
        return f"cal|{org_tier}|{purpose}"

    def action_catalog(self) -> list[ActionSpec]:
        """Return action catalog for calendar."""
        return CALENDAR_ACTION_CATALOG

    def level_cap(self, action: str, s: Situation, f: Features) -> int:
        """Apply conditional caps per ENGINE_SPEC section 8.1."""
        base_cap = 0
        found = False
        for spec in CALENDAR_ACTION_CATALOG:
            if spec.type == action:
                base_cap = spec.base_cap
                found = True
                break
        if not found:
            return 0

        org_tier = str(f.deterministic.get("organizer_tier", "unknown"))
        is_unknown = org_tier == "unknown"

        if f.reader and isinstance(f.reader, dict):
            money_involved = bool(f.reader.get("money_involved", False))
        else:
            # If reader missing or failed, fail closed
            money_involved = True

        conditional_cap = base_cap
        if is_unknown or money_involved:
            if action in ("ACCEPT", "DECLINE", "TENTATIVE"):
                conditional_cap = min(conditional_cap, 1)

        return min(base_cap, conditional_cap)

    def hands_off_text(self, text: str) -> str | None:
        """Check for strictly forbidden hands-off actions."""
        lower = text.lower()
        if "bank account" in lower or "credit card payment" in lower:
            return "financial_sensitive"
        return None

    def hands_off(self, s: Situation) -> str | None:
        """Return hands-off reason if applicable."""
        if s.hands_off_reason:
            return s.hands_off_reason
        return self.hands_off_text(s.redacted_text or "")

    def execute(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Execute calendar side effect."""
        from probation.packs.calendar.executor import execute_calendar_action

        return execute_calendar_action(a, io)

    def undo(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Undo executed calendar action."""
        from probation.packs.calendar.executor import undo_calendar_action

        return undo_calendar_action(a, io)

    def window(self, s: Situation) -> timedelta:
        """Observation window duration."""
        return timedelta(days=DEFAULT_INVITE_MAX_DAYS)

    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None:
        """Resolve observed outcome from SimWorld."""
        return resolve_calendar_outcome(s, world, now)

    def exam_operators(self) -> list[ExamOperator]:
        """Return perturbation operators for exam board evaluation."""
        return CALENDAR_EXAM_OPERATORS


calendar_pack = CalendarPack()
