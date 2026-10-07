"""Budget guard tracking LLM token expenditure.

Authority: docs/CONTRACT.md invariant I-15.
"""

from probation.config import settings


class BudgetExceeded(Exception):
    """Raised when an operation would exceed the hard budget limit."""

    pass


class BudgetGuard:
    """Enforces token spend caps before invoking external inference endpoints."""

    def __init__(self, limit_usd: float = settings.budget_hard_limit_usd) -> None:
        self.limit_usd = limit_usd
        self.spent_usd: float = 0.0

    def check_and_reserve(self, estimated_cost_usd: float) -> None:
        """Verify that proposed expenditure will not exceed the hard budget limit."""
        if self.spent_usd + estimated_cost_usd > self.limit_usd:
            raise BudgetExceeded(
                f"Budget limit of ${self.limit_usd:.2f} exceeded. Current spend: ${self.spent_usd:.4f}, estimated: ${estimated_cost_usd:.4f}"
            )

    def record_spend(self, actual_cost_usd: float) -> None:
        """Record actual spend incurred after a completed API call."""
        self.spent_usd += actual_cost_usd
