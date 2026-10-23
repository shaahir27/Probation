"""Exact monetary units and priced-model authority: no cheap default, no rounding leak.

Authority: docs/CONTRACT.md I-15, docs/wp3/WORK_PACKAGES.md P04.3, W3-T16 (metadata half).
A rate quoted in USD per million tokens is an exact integer number of units per token, so
the arithmetic here never has to guess.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from probation.config import settings
from probation.llm.budget import (
    MAX_RATE_USD_PER_MILLION,
    TOKENS_PER_CHAR_BOUND,
    UNITS_PER_USD,
    BudgetExceeded,
    BudgetGuard,
    cost_units,
    input_token_bound,
    load_price_table,
    parse_rate,
    rates_for,
    units_to_usd,
    usd_to_units,
)

NANO = (Decimal("0.06"), Decimal("0.24"))


def test_one_unit_is_one_hundredth_of_a_micro_dollar() -> None:
    assert UNITS_PER_USD == 100_000_000
    assert units_to_usd(UNITS_PER_USD) == Decimal("1.00000000")
    assert usd_to_units("0.00000001") == 1


def test_a_dollar_limit_never_rounds_down() -> None:
    """Rounding a cap down would mint headroom the owner never granted."""
    assert usd_to_units("0.000000012") == 2
    assert usd_to_units(0.000000012) == 2


def test_a_million_tokens_at_six_cents_is_exactly_six_cents() -> None:
    assert cost_units(1_000_000, 0, *NANO) == usd_to_units("0.06")
    assert cost_units(0, 1_000_000, *NANO) == usd_to_units("0.24")


def test_an_odd_rate_rounds_up_rather_than_away() -> None:
    awkward = cost_units(3, 7, Decimal("0.0123456"), Decimal("0.0765432"))
    exact = (Decimal(3) * Decimal("0.0123456") + Decimal(7) * Decimal("0.0765432")) * 100
    assert awkward > 0
    assert Decimal(awkward) >= exact


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), "abc", None, True, {}, 1e9])
def test_unusable_rate_metadata_is_denied_not_defaulted(bad: object) -> None:
    with pytest.raises(BudgetExceeded) as denial:
        parse_rate(bad, model="nvidia/x", side="input")
    assert denial.value.code == "price_invalid"


def test_a_rate_above_the_plausibility_bound_is_treated_as_corrupt() -> None:
    with pytest.raises(BudgetExceeded):
        parse_rate(float(MAX_RATE_USD_PER_MILLION) + 1, model="nvidia/x", side="completion")


def test_input_bound_is_a_documented_upper_bound_not_a_typical_estimate() -> None:
    assert TOKENS_PER_CHAR_BOUND == 2
    assert input_token_bound(0) == 0
    assert input_token_bound(27) == 54
    with pytest.raises(BudgetExceeded) as denial:
        input_token_bound(-1)
    assert denial.value.code == "usage_invalid"


def test_token_counts_must_be_whole_and_nonnegative() -> None:
    for tokens_in, tokens_out in ((-1, 0), (0, -1), (1.5, 0), (True, 0)):
        with pytest.raises(BudgetExceeded) as denial:
            cost_units(tokens_in, tokens_out, *NANO)  # type: ignore[arg-type]
        assert denial.value.code == "usage_invalid"


def test_unlisted_model_has_no_fallback_tier() -> None:
    with pytest.raises(BudgetExceeded) as denial:
        rates_for("nvidia/unpriced", {"nvidia/priced": NANO})
    assert denial.value.code == "price_missing"


def test_a_missing_price_file_denies_instead_of_inventing_rates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the table used to fall back to hard-coded rates when the file was absent."""
    monkeypatch.setattr(settings, "price_table_path", tmp_path / "absent.json")
    with pytest.raises(BudgetExceeded) as denial:
        load_price_table()
    assert denial.value.code == "price_table_missing"
    with pytest.raises(BudgetExceeded):
        BudgetGuard()


def test_malformed_price_entry_is_simply_not_priced(tmp_path: Path) -> None:
    """A comment key is skipped, so any model without a rate still reaches the denial path."""
    path = tmp_path / "prices.json"
    path.write_text('{"_note": "comment", "a": {"in": 0.06, "out": 0.24}}', encoding="utf-8")
    table = load_price_table(path)
    assert list(table) == ["a"]
    with pytest.raises(BudgetExceeded) as denial:
        rates_for("_note", table)
    assert denial.value.code == "price_missing"


def test_hold_accumulates_and_only_a_pre_dispatch_release_gives_credit_back() -> None:
    guard = BudgetGuard(limit_usd="1.00", price_table={"m": NANO})
    held = guard.reserve_units("m", tokens_in=1000, tokens_out_bound=400)
    assert guard.held_units == held and guard.spent_units == 0

    guard.release_hold(held)
    assert guard.held_units == 0 and guard.spent_units == 0

    held = guard.reserve_units("m", tokens_in=1000, tokens_out_bound=400)
    charged = guard.charge_bound("m", tokens_in=1000, tokens_out_bound=400, held=held)
    assert charged >= held
    assert guard.held_units == 0 and guard.spent_units == charged


def test_cap_counts_spent_plus_held_together() -> None:
    guard = BudgetGuard(limit_usd="0.0021", price_table={"m": NANO})
    one = guard.reserve_units("m", tokens_in=10_000, tokens_out_bound=1_000)
    guard.settle_units(held=one, charge_units=one)
    two = guard.reserve_units("m", tokens_in=10_000, tokens_out_bound=1_000)
    guard.settle_units(held=two, charge_units=two)
    assert guard.spent_units == 2 * one
    with pytest.raises(BudgetExceeded) as denial:
        guard.reserve_units("m", tokens_in=10_000, tokens_out_bound=1_000)
    assert denial.value.code == "cap_exceeded"
    # a third attempt was never authorized, so it must not have been booked
    assert guard.spent_units == 2 * one


def test_sub_micro_cent_calls_are_not_rounded_away_of_the_cap() -> None:
    """Regression: rounding each charge to six decimals let endless free calls through."""
    # A cap that affords exactly one of these attempts: 42 units = 4.2e-7 USD.
    guard = BudgetGuard(limit_usd="0.00000042", price_table={"m": NANO})
    held = guard.reserve_units("m", tokens_in=3, tokens_out_bound=1)
    charge = cost_units(3, 1, *NANO)
    assert charge == held == 42
    assert round(float(units_to_usd(charge)), 6) == 0.0  # the leak this replaces
    guard.settle_units(held=held, charge_units=charge)
    with pytest.raises(BudgetExceeded) as denial:
        guard.reserve_units("m", tokens_in=3, tokens_out_bound=1)
    assert denial.value.code == "cap_exceeded"


def test_sync_adopts_recorded_spend_and_denies_on_corrupt_cost(memory_db) -> None:
    memory_db.execute(
        "INSERT INTO exposure_log (id, situation_id, call_kind, model_id, tokens_in, "
        "tokens_out, redaction_counts_json, cost_usd, created_at) VALUES "
        "('e1', NULL, 'reader', 'm', 10, 10, '{}', 0.00024324, '2026-01-01T00:00:00Z')"
    )
    guard = BudgetGuard(limit_usd="1.00", price_table={"m": NANO})
    assert guard.sync_from_db(memory_db) == 24324
    assert guard.spent_usd == Decimal("0.00024324")

    memory_db.execute(
        "INSERT INTO exposure_log (id, situation_id, call_kind, model_id, tokens_in, "
        "tokens_out, redaction_counts_json, cost_usd, created_at) VALUES "
        "('e2', NULL, 'reader', 'm', 10, 10, '{}', -0.5, '2026-01-01T00:00:00Z')"
    )
    with pytest.raises(BudgetExceeded) as denial:
        guard.sync_from_db(memory_db)
    assert denial.value.code == "cost_metadata_invalid"
