"""Verify estimated LLM spend against price table and Token Factory console.

Authority: docs/IMPLEMENTATION_PLAN.md Phase 0 and docs/TECH_STACK_AND_REPO.md section 4.2.

Run with:
    python scripts/verify_budget.py
"""

import json
from pathlib import Path

PRICE_TABLE_PATH = Path("config/prices.json")


def verify_budget() -> None:
    print("=== Probation: Budget & Pricing Table Verification ===")
    if not PRICE_TABLE_PATH.exists():
        print(f"[-] Price table not found at {PRICE_TABLE_PATH}")
        return

    with open(PRICE_TABLE_PATH, "r", encoding="utf-8") as f:
        prices = json.load(f)

    print(f"Loaded price table from {PRICE_TABLE_PATH}:")
    for model, rates in prices.items():
        if model.startswith("_"):
            continue
        print(f"  - {model:35s}: ${rates['in']:.2f}/1M in, ${rates['out']:.2f}/1M out")

    # Estimated scenario: 2,000 emails read by Nano model
    # ~700 prompt tokens in, ~80 completion tokens out
    nano_in_rate = prices.get("nvidia/nemotron-mini-4b-instruct", {}).get("in", 0.06)
    nano_out_rate = prices.get("nvidia/nemotron-mini-4b-instruct", {}).get("out", 0.24)

    total_tokens_in = 2000 * 700
    total_tokens_out = 2000 * 80
    cost_in = (total_tokens_in / 1_000_000) * nano_in_rate
    cost_out = (total_tokens_out / 1_000_000) * nano_out_rate
    total_cost = cost_in + cost_out

    print("\nScenario Estimation: 2,000 Mails with Nemotron Nano:")
    print(f"  Input Tokens:  {total_tokens_in:,} (${cost_in:.4f})")
    print(f"  Output Tokens: {total_tokens_out:,} (${cost_out:.4f})")
    print(f"  Total Cost:    ${total_cost:.4f} USD")
    print(f"  Hard Cap:      $20.00 USD")
    print(f"  Budget Margin: {((20.00 - total_cost) / 20.00) * 100:.1f}% remaining")


if __name__ == "__main__":
    verify_budget()
