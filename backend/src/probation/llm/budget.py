"""Budget guard tracking LLM token expenditure.

Authority: docs/CONTRACT.md invariant I-15.
Hard budget cap is enforced in the LLM client.
When estimated spend reaches the cap, client raises BudgetExceeded and fails closed.
"""

import json
import sqlite3
from pathlib import Path

from probation.config import settings


class BudgetExceeded(Exception):
    """Raised when an operation would exceed the hard budget limit."""

    pass


def load_price_table(path: Path | str | None = None) -> dict[str, dict[str, float]]:
    """Load model pricing table from JSON file (USD per 1M tokens)."""
    price_path = Path(path) if path else settings.price_table_path
    if not price_path.exists():
        # Fallback default pricing
        return {
            settings.model_reader: {"in": 0.06, "out": 0.24},
            settings.model_writer: {"in": 0.30, "out": 0.90},
            settings.model_exam_edits: {"in": 0.06, "out": 0.24},
        }

    with open(price_path, encoding="utf-8") as f:
        data = json.load(f)

    pricing: dict[str, dict[str, float]] = {}
    for k, v in data.items():
        if isinstance(v, dict) and "in" in v and "out" in v:
            pricing[k] = {"in": float(v["in"]), "out": float(v["out"])}
    return pricing


def calculate_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    price_table: dict[str, dict[str, float]] | None = None,
) -> float:
    """Calculate cost in USD given model and token counts."""
    table = price_table or load_price_table()
    rates = table.get(model)
    if rates is None:
        # Default fallback to Super rates if unlisted
        rates = {"in": 0.30, "out": 0.90}

    cost_in = (tokens_in / 1_000_000.0) * rates["in"]
    cost_out = (tokens_out / 1_000_000.0) * rates["out"]
    return round(cost_in + cost_out, 6)


class BudgetGuard:
    """Enforces token spend caps before invoking external inference endpoints."""

    def __init__(
        self,
        limit_usd: float = settings.budget_hard_limit_usd,
        price_table: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.limit_usd = limit_usd
        self.spent_usd: float = 0.0
        self.price_table = price_table or load_price_table()

    def sync_from_db(self, conn: sqlite3.Connection) -> float:
        """Sync spent_usd with exposure_log in database."""
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM exposure_log;")
        row = cursor.fetchone()
        self.spent_usd = float(row[0]) if row else 0.0
        return self.spent_usd

    def check_and_reserve(self, estimated_cost_usd: float) -> None:
        """Verify that proposed expenditure will not exceed the hard budget limit."""
        if self.spent_usd + estimated_cost_usd > self.limit_usd:
            raise BudgetExceeded(
                f"Budget limit of ${self.limit_usd:.2f} exceeded. "
                f"Current spend: ${self.spent_usd:.4f}, requested: ${estimated_cost_usd:.4f}"
            )

    def record_spend(self, actual_cost_usd: float) -> None:
        """Record actual spend incurred after a completed API call."""
        self.spent_usd = round(self.spent_usd + actual_cost_usd, 6)
