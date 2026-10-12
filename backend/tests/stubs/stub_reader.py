"""Deterministic test stub for reader prompts without external LLM calls.

Authority: docs/TEST_PLAN.md section 4.
Extracts reader fields directly from synthetic ground truth attributes.
Kept in tests/stubs/ to strictly preserve static AST isolation from production code.
"""

import json
from pathlib import Path
from typing import Any

from probation.core.types import Situation


class StubReader:
    """Offline test double deriving reader fields from synthetic truth attributes."""

    def __init__(self, truth_data_or_path: dict[str, Any] | str | Path) -> None:
        if isinstance(truth_data_or_path, (str, Path)):
            p = Path(truth_data_or_path)
            self.truth = json.loads(p.read_text(encoding="utf-8"))
        else:
            self.truth = truth_data_or_path

    def __call__(self, s: Situation) -> tuple[dict[str, Any] | None, bool]:
        """Derive reader output for a given situation."""
        truth_item = self.truth.get(s.id)
        if not truth_item:
            # Fallback default values
            if s.pack == "mail":
                return (
                    {
                        "intent": "other",
                        "asks_me_to_do_something": False,
                        "has_deadline": False,
                        "deadline_text": None,
                        "money_involved": False,
                        "urgency": 1,
                        "formality": "neutral",
                        "asks_for_personal_info": False,
                        "looks_automated": False,
                    },
                    True,
                )
            else:
                return (
                    {
                        "purpose": "other",
                        "looks_mandatory": False,
                        "money_involved": False,
                    },
                    True,
                )

        attrs = truth_item.get("attributes", {})

        if s.pack == "mail":
            urgency_raw = attrs.get("urgency", "normal")
            if isinstance(urgency_raw, int):
                urgency = min(3, max(0, urgency_raw))
            else:
                urgency_map = {"low": 0, "normal": 1, "urgent": 2, "high": 3}
                urgency = urgency_map.get(str(urgency_raw).lower(), 1)

            intent_raw = str(attrs.get("intent", "other"))
            valid_intents = {
                "request",
                "question",
                "fyi",
                "newsletter",
                "receipt",
                "invite_mention",
                "social",
                "sales",
                "opportunity",
                "other",
            }
            intent = (
                intent_raw
                if intent_raw in valid_intents
                else ("social" if intent_raw == "chat" else "other")
            )

            reader_dict = {
                "intent": intent,
                "asks_me_to_do_something": bool(
                    attrs.get("asks_me_to_do_something", intent == "request")
                ),
                "has_deadline": bool(attrs.get("has_deadline", False)),
                "deadline_text": attrs.get("deadline_text"),
                "money_involved": bool(attrs.get("money_involved", False)),
                "urgency": urgency,
                "formality": attrs.get("formality", "neutral"),
                "asks_for_personal_info": bool(attrs.get("asks_for_personal_info", False)),
                "looks_automated": bool(attrs.get("is_automated", False)),
            }
            return reader_dict, True

        elif s.pack == "calendar":
            purpose_raw = str(attrs.get("purpose", "other")).lower()
            valid_purposes = {"class", "club", "interview", "social", "work", "sales", "other"}
            if purpose_raw in valid_purposes:
                purpose = purpose_raw
            elif "class" in purpose_raw or "lecture" in purpose_raw:
                purpose = "class"
            elif "club" in purpose_raw:
                purpose = "club"
            elif "work" in purpose_raw or "sync" in purpose_raw:
                purpose = "work"
            elif "interview" in purpose_raw:
                purpose = "interview"
            else:
                purpose = "other"

            reader_dict = {
                "purpose": purpose,
                "looks_mandatory": bool(attrs.get("looks_mandatory", purpose == "class")),
                "money_involved": bool(attrs.get("money_involved", False)),
            }
            return reader_dict, True

        return None, False
