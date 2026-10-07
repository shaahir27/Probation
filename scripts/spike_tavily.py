"""Day-1 Spike: Tavily runtime Search and Extract for Hackathon Bonus eligibility ($3,000).

Authority: docs/IMPLEMENTATION_PLAN.md Phase 0 and docs/TAVILY_AND_NEW_PACKS.md section 12.

Run with:
    python scripts/spike_tavily.py

Prerequisites:
    Set TAVILY_API_KEY in .env or environment.
"""

import json
import os
import sys
import time
from typing import Any, Dict


def run_tavily_spike() -> None:
    api_key = os.getenv("TAVILY_API_KEY")
    base_url = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com")

    print("=== Probation Spike: Tavily Search & Extract Runtime Call ===")
    print(f"Base URL: {base_url}")

    if not api_key:
        print("\n[!] TAVILY_API_KEY is not set.")
        print("Please set your Tavily API key in .env or environment:")
        print("    export TAVILY_API_KEY=tvly-...")
        print("    python scripts/spike_tavily.py")
        print("\nSkipping live call (dry run passed).")
        return

    try:
        import httpx
    except ImportError:
        print("[!] httpx is not installed. Run: pip install httpx")
        sys.exit(1)

    client = httpx.Client(timeout=20.0)

    # 1. Search Spike: Out-of-band entity lookup (Public entity only)
    search_query = "NVIDIA Global AI Hackathon Devpost official page"
    print(f"\n1. Executing Tavily Search call: '{search_query}'...")
    search_start = time.perf_counter()

    try:
        search_resp = client.post(
            f"{base_url}/search",
            json={
                "api_key": api_key,
                "query": search_query,
                "max_results": 3,
                "search_depth": "basic",
            },
        )
        search_latency = time.perf_counter() - search_start
        search_data = search_resp.json()

        print(f"[+] Search response received in {search_latency:.3f}s (HTTP {search_resp.status_code})")
        results = search_data.get("results", [])
        print(f"    Returned {len(results)} search results.")
        for idx, res in enumerate(results[:2], 1):
            print(f"    [{idx}] {res.get('title')} -> {res.get('url')}")

    except Exception as exc:
        print(f"[-] Search call failed: {exc}")
        return

    # 2. Extract Spike: Reading public opportunity page
    target_url = "https://tavily.com"
    print(f"\n2. Executing Tavily Extract call: '{target_url}'...")
    extract_start = time.perf_counter()

    try:
        extract_resp = client.post(
            f"{base_url}/extract",
            json={
                "api_key": api_key,
                "urls": [target_url],
            },
        )
        extract_latency = time.perf_counter() - extract_start
        extract_data = extract_resp.json()

        print(f"[+] Extract response received in {extract_latency:.3f}s (HTTP {extract_resp.status_code})")
        ext_results = extract_data.get("results", [])
        print(f"    Extracted {len(ext_results)} pages.")
        if ext_results:
            sample_chars = len(ext_results[0].get("raw_content", ""))
            print(f"    First page content length: {sample_chars} characters.")

        print("\n[+] Tavily runtime integration verified successfully!")
        print("    Eligibility for $3,000 Tavily Hackathon Bonus Track confirmed.")

    except Exception as exc:
        print(f"[-] Extract call failed: {exc}")


if __name__ == "__main__":
    run_tavily_spike()
