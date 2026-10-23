"""Mail domain pack implementing PackAdapter.

Authority: docs/PACKS_SPEC.md section 1 and docs/CONTRACT.md section 5.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Any

from probation.config import settings
from probation.core.hashing import canonical_situation_id
from probation.core.history import HistoryView
from probation.core.identity import normalize_address, normalize_user_addresses
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
from probation.llm.context import redaction_names
from probation.llm.jobs import MailReader
from probation.llm.redact import redact
from probation.packs.base import ExecutorIO, PackAdapter, WorldView
from probation.packs.mail.clues import extract_mail_clues
from probation.packs.mail.exam_ops import MAIL_EXAM_OPERATORS
from probation.packs.mail.resolver import DEFAULT_MAIL_WINDOW_DAYS, resolve_mail_outcome

MAIL_ACTION_CATALOG = [
    ActionSpec(type="REPLY", recallable=False, base_cap=2, loss=40.0),
    ActionSpec(type="FORWARD", recallable=False, base_cap=1, loss=40.0),
    ActionSpec(type="TRASH", recallable=True, base_cap=2, loss=20.0),
    ActionSpec(type="ARCHIVE", recallable=True, base_cap=3, loss=5.0),
    ActionSpec(type="LEAVE", recallable=True, base_cap=0, loss=0.0),
]

MAIL_READER_SCHEMA = MailReader.model_json_schema()


class MailPack(PackAdapter):
    """Mail domain pack adapter."""

    name: str = "mail"
    families: tuple[str, ...] = ("email_action",)

    def __init__(self, user_addresses: list[str] | str | None = None) -> None:
        # Normalized once here so intake, featurization and resolution cannot disagree about
        # spelling. `None` is preserved as `None`: it means "not supplied", which lets those
        # callers fall through to the world or configured owner, whereas an explicit empty
        # list means "this mailbox has no owner" and must not fall through.
        self.user_addresses: list[str] | None = (
            None if user_addresses is None else normalize_user_addresses(user_addresses)
        )

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

        # Only incoming mail from other parties creates a situation
        if item_kind != "mail_in":
            return []

        try:
            payload = json.loads(payload_str)
        except Exception:
            payload = {}

        from_addr = payload.get("from", "")
        norm_from = normalize_address(from_addr)
        if self.user_addresses is not None:
            user_addrs = self.user_addresses
        else:
            user_addrs = normalize_user_addresses(settings.user_addresses)

        # Skip if from the user or marked spam/draft
        if norm_from and norm_from in set(user_addrs):
            return []
        labels = [str(lbl).upper() for lbl in payload.get("labels", [])]
        if "SPAM" in labels or "DRAFT" in labels:
            return []

        body = payload.get("body", "")
        subject = payload.get("subject", "")
        full_text = f"Subject: {subject}\n\n{body}"

        # Redact before LLM egress (Invariant I-14). The names in the headers are the person behind
        # the address, so they are passed into redaction here instead of riding along in clear text.
        names = redaction_names(payload.get("from"), payload.get("to"), payload.get("cc"))
        redacted = redact(full_text, profile="mail", display_names=names)

        source_ref = (
            (
                raw_item.get("source_ref")
                if isinstance(raw_item, dict)
                else getattr(raw_item, "source_ref", None)
            )
            or payload.get("message_id")
            or raw_id
        )

        situation_id = canonical_situation_id("mail", source_ref, occurred_at, "email_action", "")
        hands_off_reason = self.hands_off_text(full_text)

        sit = Situation(
            id=situation_id,
            pack=self.name,
            family="email_action",
            raw_item_id=raw_id,
            occurred_at=occurred_at,
            sender_key=norm_from,
            content_hash=content_hash,
            redacted_text=redacted.text,
            hands_off_reason=hands_off_reason,
            variant="",
            created_at=occurred_at,
        )
        return [sit]

    def deterministic_clues(self, s: Situation, hist: HistoryView) -> dict[str, float | str | bool]:
        """Compute all 16 deterministic clues strictly through HistoryView (Invariant I-6)."""
        # Find raw item payload if available
        raw_items = hist.get_raw_items(pack=self.name)
        payload = {}
        for row in raw_items:
            if row["id"] == s.raw_item_id:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    pass
                break
        return extract_mail_clues(s, hist, payload, user_addresses=self.user_addresses)

    def reader_spec(self) -> ReaderSpec:
        """Prompt descriptor for mail reader."""
        return ReaderSpec(
            prompt_id="reader.mail",
            prompt_version="v2",
            json_schema=MAIL_READER_SCHEMA,
            redaction_profile="mail",
        )

    def class_key(self, s: Situation, f: Features) -> str:
        """Derive class key: mail|{intent}|{sender_tier} per PACKS_SPEC section 1.5."""
        intent = "other"
        if f.reader and isinstance(f.reader, dict):
            intent = str(f.reader.get("intent", "other"))
        sender_tier = str(f.deterministic.get("sender_tier", "unknown"))
        return f"mail|{intent}|{sender_tier}"

    def action_catalog(self) -> list[ActionSpec]:
        """Return action catalog for mail."""
        return MAIL_ACTION_CATALOG

    def level_cap(self, action: str, s: Situation, f: Features) -> int:
        """Apply conditional caps per ENGINE_SPEC section 8.1."""
        base_cap = 0
        found = False
        for spec in MAIL_ACTION_CATALOG:
            if spec.type == action:
                base_cap = spec.base_cap
                found = True
                break
        if not found:
            return 0

        sender_tier = str(f.deterministic.get("sender_tier", "unknown"))
        is_unknown = sender_tier == "unknown"

        if f.reader and isinstance(f.reader, dict):
            money_involved = bool(f.reader.get("money_involved", False))
            asks_personal_info = bool(f.reader.get("asks_for_personal_info", False))
        else:
            # When unsure / missing reader, fail closed (PROMPTS.md section 2)
            money_involved = True
            asks_personal_info = True

        conditional_cap = base_cap
        if is_unknown or money_involved or asks_personal_info:
            if action in ("REPLY", "FORWARD", "TRASH"):
                conditional_cap = min(conditional_cap, 1)
            elif action == "ARCHIVE":
                conditional_cap = min(conditional_cap, 2)

        return min(base_cap, conditional_cap)

    def hands_off_text(self, text: str) -> str | None:
        """Check for strictly forbidden hands-off actions."""
        lower = text.lower()
        if (
            "password reset" in lower
            or bool(re.search(r"\botp\b", lower))
            or "bank account verification" in lower
        ):
            return "credential_or_security_sensitive"
        return None

    def hands_off(self, s: Situation) -> str | None:
        """Return hands-off reason if applicable."""
        if s.hands_off_reason:
            return s.hands_off_reason
        return self.hands_off_text(s.redacted_text or "")

    def execute(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Execute mail side effect."""
        from probation.packs.mail.executor import execute_mail_action

        return execute_mail_action(a, io)

    def undo(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Undo executed mail action."""
        from probation.packs.mail.executor import undo_mail_action

        return undo_mail_action(a, io)

    def window(self, s: Situation) -> timedelta:
        """Observation window duration."""
        return timedelta(days=DEFAULT_MAIL_WINDOW_DAYS)

    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None:
        """Resolve observed outcome from SimWorld."""
        return resolve_mail_outcome(s, world, now, user_addresses=self.user_addresses)

    def resolve_observed_outcome(
        self,
        s: Situation,
        world: WorldView,
        now: datetime,
        raw_payload: dict[str, Any] | None,
    ) -> Outcome | None:
        """Resolve observed outcome with the message's source record attached.

        Without `message_id` no sent reply can be matched to this message, so every mail situation
        degrades to a label-only decision and real REPLY and FORWARD evidence is never observed.
        """
        return resolve_mail_outcome(
            s, world, now, raw_payload=raw_payload, user_addresses=self.user_addresses
        )

    def exam_operators(self) -> list[ExamOperator]:
        """Return perturbation operators for exam board evaluation."""
        return MAIL_EXAM_OPERATORS


mail_pack = MailPack()
