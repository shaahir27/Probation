"""Evaluation baseline policies for comparison against Probation.

Authority: docs/EVALUATION_PLAN.md section 4.
Baselines:
- B0: Majority class (modal action for family so far, strictly no-peeking).
- B1: Ask always (100% interruptions, 0% autonomous error).
- B2: Generic rules (non-personal static heuristics).
- B3: LLM-confidence threshold (KnowNo-style confidence thresholding).
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from probation.core.enums import Gate
from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.llm.client import LLMClient


@dataclass(frozen=True)
class BaselineDecision:
    baseline_id: str
    action: str
    confidence: float
    gate: Gate
    is_autonomous: bool
    reasons: list[str]


class MajorityBaseline:
    """B0: Majority class baseline (Sanity check).

    Always predicts the most common past action for the family so far.
    Used for agreement benchmark; does not act autonomously.
    """

    baseline_id: str = "B0"

    def __init__(self) -> None:
        self._counts: dict[str, Counter[str]] = {}

    def update(self, family: str, action: str) -> None:
        """Update past observed action count for family."""
        if family not in self._counts:
            self._counts[family] = Counter()
        self._counts[family][action] += 1

    def predict(self, situation: Situation) -> BaselineDecision:
        """Predict modal action so far for situation family."""
        fam = situation.family
        counter = self._counts.get(fam)
        if not counter:
            # Fallback default actions
            default_act = (
                "REPLY"
                if fam == "email_action"
                else ("ACCEPT" if fam == "invite_rsvp" else "LEAVE")
            )
            return BaselineDecision(
                baseline_id=self.baseline_id,
                action=default_act,
                confidence=0.5,
                gate=Gate.ASK,
                is_autonomous=False,
                reasons=["b0_no_history"],
            )

        top_action, count = counter.most_common(1)[0]
        total = sum(counter.values())
        conf = float(count) / float(total) if total > 0 else 0.5

        return BaselineDecision(
            baseline_id=self.baseline_id,
            action=top_action,
            confidence=conf,
            gate=Gate.ASK,
            is_autonomous=False,
            reasons=[f"b0_majority_count_{count}_of_{total}"],
        )


class AskAlwaysBaseline:
    """B1: Ask always baseline.

    Zero autonomy; produces an ASK gate for every situation.
    100 attention units per 100 situations, 0% autonomous error.
    """

    baseline_id: str = "B1"

    def predict(self, situation: Situation, default_action: str = "REPLY") -> BaselineDecision:
        return BaselineDecision(
            baseline_id=self.baseline_id,
            action=default_action,
            confidence=1.0,
            gate=Gate.ASK,
            is_autonomous=False,
            reasons=["b1_ask_always"],
        )


class GenericRulesBaseline:
    """B2: Generic rules baseline (Non-personal heuristics).

    Mail: if looks_automated or intent in newsletter/receipt/sales -> auto ARCHIVE, else ASK.
    Calendar: always ASK.
    Files: auto-move by extension group to fixed folders, else ASK.
    """

    baseline_id: str = "B2"

    FILE_EXT_FOLDERS: ClassVar[dict[str, str]] = {
        "pdf": "Documents",
        "doc": "Documents",
        "docx": "Documents",
        "txt": "Documents",
        "xls": "Spreadsheets",
        "xlsx": "Spreadsheets",
        "csv": "Spreadsheets",
        "png": "Pictures",
        "jpg": "Pictures",
        "jpeg": "Pictures",
        "zip": "Archives",
        "tar": "Archives",
    }

    def predict(
        self,
        situation: Situation,
        payload: dict[str, Any] | None = None,
    ) -> BaselineDecision:
        p = payload or {}
        fam = situation.family

        if fam == "email_action":
            intent = str(p.get("intent", "")).lower()
            looks_automated = bool(p.get("looks_automated", False))
            body_text = (situation.redacted_text or "").lower()
            is_generic_archive = (
                looks_automated
                or intent in ("newsletter", "receipt", "sales", "notification")
                or "unsubscribe" in body_text
                or "receipt" in body_text
            )
            if is_generic_archive:
                return BaselineDecision(
                    baseline_id=self.baseline_id,
                    action="ARCHIVE",
                    confidence=0.85,
                    gate=Gate.EXECUTE_UNDO,
                    is_autonomous=True,
                    reasons=["b2_automated_or_newsletter"],
                )
            return BaselineDecision(
                baseline_id=self.baseline_id,
                action="REPLY",
                confidence=0.50,
                gate=Gate.ASK,
                is_autonomous=False,
                reasons=["b2_mail_default_ask"],
            )

        elif fam == "invite_rsvp":
            # Calendar: always ask
            return BaselineDecision(
                baseline_id=self.baseline_id,
                action="ACCEPT",
                confidence=0.50,
                gate=Gate.ASK,
                is_autonomous=False,
                reasons=["b2_calendar_always_ask"],
            )

        elif fam == "file_destination":
            filename = str(p.get("filename") or Path(p.get("rel_path", "")).name)
            ext = Path(filename).suffix.lstrip(".").lower()
            folder = self.FILE_EXT_FOLDERS.get(ext)
            if folder:
                return BaselineDecision(
                    baseline_id=self.baseline_id,
                    action=f"MOVE_TO_FOLDER:{folder}",
                    confidence=0.80,
                    gate=Gate.EXECUTE_UNDO,
                    is_autonomous=True,
                    reasons=[f"b2_extension_folder_{folder}"],
                )
            return BaselineDecision(
                baseline_id=self.baseline_id,
                action="LEAVE",
                confidence=0.50,
                gate=Gate.ASK,
                is_autonomous=False,
                reasons=["b2_file_unknown_extension_ask"],
            )

        # Default for other families: ASK
        return BaselineDecision(
            baseline_id=self.baseline_id,
            action="LEAVE",
            confidence=0.50,
            gate=Gate.ASK,
            is_autonomous=False,
            reasons=["b2_family_unsupported_ask"],
        )


class LLMConfidenceBaseline:
    """B3: LLM-confidence threshold baseline (KnowNo-style).

    Provides redacted situation text + 10 nearest past situations with known outcomes.
    Requests {'action': str, 'confidence': float}.
    Acts autonomously if confidence >= tau; sweeps tau over {0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99}.
    Supports pre-cached offline responses to avoid incurring live costs in CI.
    """

    baseline_id: str = "B3"

    B3_SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "confidence"],
        "properties": {
            "action": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }

    def __init__(
        self,
        tau: float = 0.80,
        llm_client: LLMClient | None = None,
        cached_predictions: dict[str, tuple[str, float]] | None = None,
    ) -> None:
        self.tau = tau
        self.llm_client = llm_client
        self.cached_predictions = cached_predictions or {}

    def predict(
        self,
        situation: Situation,
        history: HistoryView | None = None,
        nearest_examples: list[dict[str, str]] | None = None,
    ) -> BaselineDecision:
        """Predict action and confidence using LLM or offline cache."""
        sit_id = situation.id

        # 1. Check local cached prediction fixture
        if sit_id in self.cached_predictions:
            act, conf = self.cached_predictions[sit_id]
            is_auto = conf >= self.tau
            gate = Gate.EXECUTE_UNDO if is_auto else Gate.ASK
            return BaselineDecision(
                baseline_id=self.baseline_id,
                action=act,
                confidence=conf,
                gate=gate,
                is_autonomous=is_auto,
                reasons=[f"b3_cached_tau_{self.tau}"],
            )

        # A raw client or guessed heuristic cannot establish a B3 measurement.
        # WP10 must supply frozen validated predictions with its ten-example cohort.
        return BaselineDecision(
            baseline_id=self.baseline_id,
            action="ABSTAIN",
            confidence=0.0,
            gate=Gate.ASK,
            is_autonomous=False,
            reasons=["b3_not_run_missing_validated_prediction"],
        )
