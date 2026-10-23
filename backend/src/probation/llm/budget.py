"""Spend authority: exact monetary units, verified pricing and the hard cap.

Authority: docs/CONTRACT.md invariant I-15, docs/wp3/WORK_PACKAGES.md P04.3-P04.6.

This module decides whether *this process* may dispatch, and what one physical attempt
cost. It is not a reservation: two workers holding this class cannot serialize on the
last unit of the cap, and a process that dies takes its counters with it. The durable
request/attempt store that makes the cap true across processes needs tables and role
grants that CONTRACT section 3 does not name yet, so it is gated on the W3-D03 schema
review (docs/wp3/W3_D03_SPEND_ACCOUNTING_REVIEW.md) rather than implemented here.
"""

import json
import math
from collections.abc import Mapping
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import Any

from probation.config import settings

# One unit is 1e-8 USD. A rate quoted in USD per million tokens with two decimals is then
# an exact integer number of units per token, so no per-call cost has to be rounded down.
UNITS_PER_USD = 100_000_000
# Two tokens per egress character is this implementation's assumption, listed for review:
# a byte-pair encoder can split a non-Latin character and the request envelope adds framing
# this module cannot see. It is deliberately an upper bound, not a typical-case estimate.
TOKENS_PER_CHAR_BOUND = 2
# A rate above this is treated as corrupt pricing metadata, not as an expensive model.
MAX_RATE_USD_PER_MILLION = Decimal("1000")

Rates = tuple[Decimal, Decimal]
PriceTable = Mapping[str, Rates]


class BudgetExceeded(Exception):
    """An operation lacks budget authority; `code` is the typed denial reason."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _decimal(value: int | float | str | Decimal) -> Decimal:
    if isinstance(value, float) and not math.isfinite(value):
        raise BudgetExceeded("Amount is not finite", code="amount_invalid")
    try:
        return Decimal(value if not isinstance(value, float) else str(value))
    except Exception as exc:
        raise BudgetExceeded("Amount is not a decimal number", code="amount_invalid") from exc


def usd_to_units(value: float | str | Decimal) -> int:
    """Whole units for a dollar amount, always rounded up.

    Rounding a *limit* down would mint headroom the owner never granted, so the same
    upward rule is used for limits and for costs; the direction is only ever conservative.
    """
    amount = _decimal(value)
    if amount < 0:
        raise BudgetExceeded("Amount is negative", code="amount_invalid")
    return int((amount * UNITS_PER_USD).to_integral_value(rounding=ROUND_UP))


def units_to_usd(units: int) -> Decimal:
    return Decimal(int(units)).scaleb(-8)


def units_from_persisted(value: Any) -> int:
    """Recover units from a stored REAL cost, denying metadata that cannot be trusted."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise BudgetExceeded("Stored cost is not a number", code="cost_metadata_invalid")
    amount = _decimal(value)
    if not amount.is_finite() or amount < 0:
        raise BudgetExceeded(
            "Stored cost is not a finite nonnegative amount", code="cost_metadata_invalid"
        )
    return int((amount * UNITS_PER_USD).to_integral_value(rounding=ROUND_UP))


def parse_rate(value: object, *, model: str, side: str) -> Decimal:
    """Validate one quoted price before it can authorize a cheaper dispatch."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise BudgetExceeded(f"Model {model} {side} rate is not a number", code="price_invalid")
    try:
        rate = _decimal(value)
    except BudgetExceeded as exc:
        raise BudgetExceeded(
            f"Model {model} {side} rate is not a decimal number", code="price_invalid"
        ) from exc
    if not rate.is_finite() or rate < 0 or rate > MAX_RATE_USD_PER_MILLION:
        raise BudgetExceeded(f"Model {model} {side} rate is out of range", code="price_invalid")
    return rate


def input_token_bound(chars: int) -> int:
    """Prompt-token bound for `chars` characters leaving this process."""
    if isinstance(chars, bool) or not isinstance(chars, int) or chars < 0:
        raise BudgetExceeded("Character bound is not a nonnegative count", code="usage_invalid")
    return chars * TOKENS_PER_CHAR_BOUND


def cost_units(tokens_in: int, tokens_out: int, rate_in: Decimal, rate_out: Decimal) -> int:
    """Cost in units for one attempt: USD = tokens x rate / 1e6, so units = tokens x rate x 100."""
    for label, count in (("prompt", tokens_in), ("completion", tokens_out)):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise BudgetExceeded(f"{label} token count is invalid", code="usage_invalid")
    gross = (Decimal(tokens_in) * rate_in + Decimal(tokens_out) * rate_out) * 100
    return int(gross.to_integral_value(rounding=ROUND_UP))


def load_price_table(path: Path | str | None = None) -> dict[str, Rates]:
    """Read USD-per-million rates, or deny.

    The previous version returned hard-coded rates when the file was missing, and
    `calculate_cost` defaulted any unlisted model to the Super tier. That is exactly how
    an unpriced model became a cheap one, so both defaults are gone: a missing or
    malformed table is a denial, and an entry this function skips simply has no price.
    """
    price_path = Path(path) if path else settings.price_table_path
    if not price_path.is_file():
        raise BudgetExceeded("Price table is unavailable", code="price_table_missing")
    try:
        data = json.loads(price_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BudgetExceeded("Price table is unreadable", code="price_table_invalid") from exc
    if not isinstance(data, dict):
        raise BudgetExceeded("Price table is not an object", code="price_table_invalid")

    table: dict[str, Rates] = {}
    for model, entry in data.items():
        if not isinstance(model, str):
            continue
        if isinstance(entry, dict) and "in" in entry and "out" in entry:
            table[model] = (
                parse_rate(entry["in"], model=model, side="input"),
                parse_rate(entry["out"], model=model, side="completion"),
            )
    return table


def rates_for(model: str, table: PriceTable) -> Rates:
    """Rates for one exact model id; an unlisted model has no fallback tier."""
    rates = table.get(model)
    if rates is None:
        raise BudgetExceeded(f"Model {model} has no verified price", code="price_missing")
    return rates


class BudgetGuard:
    """Hard-cap check and in-process attempt accounting, in exact units.

    `held_units` is provisional while an attempt is in flight, so the ladder of retries,
    format fallback and repair cannot collectively outrun the cap on one authorization.
    A held amount is only ever released before dispatch, never after: an attempt that
    left this process may have been billed whatever its outcome.
    """

    def __init__(
        self,
        limit_usd: float | str | Decimal = settings.budget_hard_limit_usd,
        price_table: PriceTable | None = None,
    ) -> None:
        self.limit_units = usd_to_units(limit_usd)
        self.price_table: PriceTable = (
            dict(load_price_table()) if price_table is None else price_table
        )
        self.spent_units = 0
        self.held_units = 0

    @property
    def limit_usd(self) -> Decimal:
        return units_to_usd(self.limit_units)

    @property
    def spent_usd(self) -> Decimal:
        return units_to_usd(self.spent_units)

    def sync_from_db(self, conn: Any) -> int:
        """Adopt billed spend already recorded in `exposure_log`.

        Reads through the caller's connection but writes nothing, so a role connection
        cannot use this to launder a write.
        """
        rows = conn.execute("SELECT cost_usd FROM exposure_log").fetchall()
        self.spent_units = sum(units_from_persisted(row[0]) for row in rows)
        return self.spent_units

    def reserve_units(self, model: str, *, tokens_in: int, tokens_out_bound: int) -> int:
        """Authorize one physical attempt against spent plus held, and hold its bound."""
        if tokens_out_bound <= 0:
            raise BudgetExceeded("Completion bound must be positive", code="usage_invalid")
        rate_in, rate_out = rates_for(model, self.price_table)
        estimate = cost_units(tokens_in, tokens_out_bound, rate_in, rate_out)
        if self.spent_units + self.held_units + estimate > self.limit_units:
            raise BudgetExceeded(
                f"Budget cap of {self.limit_usd} USD reached: spent {self.spent_usd}, "
                f"held {units_to_usd(self.held_units)}, requested {units_to_usd(estimate)}",
                code="cap_exceeded",
            )
        self.held_units += estimate
        return estimate

    def release_hold(self, units: int) -> None:
        """Give a hold back only for an attempt known never to have left this process."""
        self.held_units = max(0, self.held_units - units)

    def settle_units(self, *, held: int, charge_units: int) -> int:
        """Close one attempt: drop its hold and book the charge, which is never less than zero."""
        self.release_hold(held)
        self.spent_units += int(charge_units)
        return int(charge_units)

    def charge_bound(self, model: str, *, tokens_in: int, tokens_out_bound: int, held: int) -> int:
        """Bill an ambiguous dispatched attempt at its bound and stop cheaper self-deception."""
        rate_in, rate_out = rates_for(model, self.price_table)
        bound = cost_units(tokens_in, tokens_out_bound, rate_in, rate_out)
        return self.settle_units(held=held, charge_units=max(bound, held))
