"""Day-1 Spike: LLM call and strict JSON-schema support on Nebius Token Factory.

Authority: docs/IMPLEMENTATION_PLAN.md Phase 0 and docs/DECISIONS_AND_OPEN_QUESTIONS.md O-1, O-2.

Run with:
    python scripts/spike_llm.py

Prerequisites:
    Set LLM_API_KEY in your environment or .env file.
"""

import json
import os
import sys
import time
from typing import Optional
from pydantic import BaseModel, Field


class ReaderSampleOutput(BaseModel):
    """Schema for reader extraction spike."""

    intent: str = Field(description="One of reply, file, schedule, notification, unsubscribe, ignore")
    urgency: int = Field(ge=1, le=5, description="Urgency scale 1 to 5")
    money_mentioned: bool = Field(description="True if financial transaction or fee is mentioned")
    summary: str = Field(description="One-sentence plain text summary")


def run_llm_spike() -> None:
    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
    model_name = os.getenv("MODEL_READER", "nvidia/nemotron-mini-4b-instruct")

    print(f"=== Probation Spike: LLM Client & Schema Validation ===")
    print(f"Base URL: {base_url}")
    print(f"Model:    {model_name}")

    if not api_key:
        print("\n[!] LLM_API_KEY is not set.")
        print("Please set your Nebius Token Factory API key in .env or environment:")
        print("    export LLM_API_KEY=your_key_here")
        print("    python scripts/spike_llm.py")
        print("\nSkipping live network call (dry run passed).")
        return

    try:
        from openai import OpenAI
    except ImportError:
        print("[!] openai package is not installed. Run: pip install openai")
        sys.exit(1)

    client = OpenAI(base_url=base_url, api_key=api_key)

    sample_prompt = (
        "Email Subject: Action required: Paper submission deadline\n"
        "Email Body: Hi Team, please submit the camera-ready paper by Friday 5 PM. "
        "The conference registration fee of $150 must be paid prior to upload.\n\n"
        "Extract intent, urgency (1-5), money_mentioned (boolean), and a one-sentence summary."
    )

    print("\nSending structured request with JSON schema...")
    start_time = time.perf_counter()

    try:
        response = client.beta.chat.completions.parse(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a strict data extraction system. Output strictly according to schema."},
                {"role": "user", "content": sample_prompt},
            ],
            response_format=ReaderSampleOutput,
            temperature=0.0,
        )
        elapsed = time.perf_counter() - start_time
        parsed = response.choices[0].message.parsed
        usage = response.usage

        print(f"\n[+] Request Successful in {elapsed:.3f}s")
        if usage:
            print(f"    Tokens In:     {usage.prompt_tokens}")
            print(f"    Tokens Out:    {usage.completion_tokens}")
            print(f"    Total Tokens:  {usage.total_tokens}")
        print("\nParsed Schema Output:")
        print(json.dumps(parsed.model_dump(), indent=2))
        print("\n[+] Verification result: Strict JSON-schema mode is supported!")

    except Exception as exc:
        print(f"\n[-] Structured request failed or rejected: {exc}")
        print("Falling back to standard JSON completion mode test...")
        # Fallback test
        start_time = time.perf_counter()
        try:
            raw_resp = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "Return valid JSON matching keys: intent, urgency, money_mentioned, summary."},
                    {"role": "user", "content": sample_prompt},
                ],
                temperature=0.0,
            )
            elapsed = time.perf_counter() - start_time
            content = raw_resp.choices[0].message.content or ""
            print(f"[+] Fallback successful in {elapsed:.3f}s:\n{content}")
            print("\n[!] Verification result: Model requires JSON markdown/repair fallback path.")
        except Exception as fallback_exc:
            print(f"[-] Fallback also failed: {fallback_exc}")


if __name__ == "__main__":
    run_llm_spike()
