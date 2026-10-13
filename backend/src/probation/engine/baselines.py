"""Baseline agents B0, B1, and B2.

Authority: docs/EVALUATION_PLAN.md section 4.
All baselines see the same situations in the same order and obey the same no-peeking rule.
"""

from collections import Counter

from probation.core.enums import GateDecision
from probation.core.types import Features, Situation


class BaselineB0:
    """B0: Majority class baseline.

    Always predicts the most common past strong action for the family.
    Used only for the agreement metric.
    """

    def __init__(self, family: str) -> None:
        self.family = family
        self.action_counts: Counter[str] = Counter()

    def update(self, action: str) -> None:
        """Record an observed past action."""
        self.action_counts[action] += 1

    def predict(self, default_action: str = "ARCHIVE") -> str:
        """Predict majority action from past observations."""
        if not self.action_counts:
            return default_action
        most_common = self.action_counts.most_common(1)
        return most_common[0][0]


class BaselineB1:
    """B1: Always ask baseline.

    Asks the human for every situation (100% asks, 0% autonomy).
    """

    @staticmethod
    def predict() -> tuple[str, GateDecision]:
        """Return (action, gate)."""
        return "ASK", GateDecision.ASK


class BaselineB2:
    """B2: Generic, impersonal heuristic rules baseline.

    - Mail: if looks_automated or intent in ('newsletter', 'receipt', 'sales') -> ARCHIVE, else ASK.
    - Calendar: always ASK.
    """

    @staticmethod
    def predict(
        situation: Situation,
        features: Features | None = None,
    ) -> tuple[str, GateDecision]:
        """Predict action and gate decision based on generic rules."""
        if situation.family == "email_action":
            det = features.deterministic if features else {}
            reader = features.reader if features and features.reader else {}

            looks_auto = bool(
                det.get("looks_automated", False)
                or det.get("sender_tier") == "automated"
                or det.get("has_unsubscribe", False)
                or det.get("is_noreply", False)
            )
            intent = str(reader.get("intent", det.get("intent", ""))).lower()

            if looks_auto or intent in {"newsletter", "receipt", "sales"}:
                return "ARCHIVE", GateDecision.HOLD_THEN_EXECUTE
            return "ASK", GateDecision.ASK

        if situation.family == "invite_rsvp":
            return "ASK", GateDecision.ASK

        return "ASK", GateDecision.ASK
