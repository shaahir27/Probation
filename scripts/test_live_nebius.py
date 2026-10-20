"""1-call live smoke test for Nebius Token Factory.

Authority: docs/IMPLEMENTATION_PLAN.md Phase 0/1 acceptance criteria.
Verifies real API key, model availability, schema validation, and latency with exactly 1 call.
Never prints or logs secrets.
"""

import sys
import time

from probation.config import settings
from probation.llm.client import LLMClient
from probation.packs.mail import MAIL_READER_SCHEMA


def main() -> None:
    if not settings.llm_api_key:
        print("ERROR: llm_api_key is empty in .env. Please set LLM_API_KEY.", file=sys.stderr)
        sys.exit(1)

    print(f"Target Base URL: {settings.llm_base_url}")
    print(f"Target Reader Model: {settings.model_reader}")

    client = LLMClient()
    system = "You are a form-filling tool. You read ONE email and fill a JSON form adhering strictly to the schema."
    user = (
        "<email>\n"
        "From: advisor@university.edu\n"
        "Subject: Meeting tomorrow regarding thesis\n\n"
        "Hi Meena,\n\n"
        "Can you send me the latest draft of your thesis before our meeting tomorrow at 2pm?\n\n"
        "Best,\nProf. Sharma\n"
        "</email>"
    )

    cache_parts = {
        "content_hash": "live_smoke_test_001",
        "prompt_id": "reader.mail",
        "prompt_version": "v2",
    }

    try:
        start = time.perf_counter()
        result = client.chat_json(
            kind="reader",
            model=settings.model_reader,
            system=system,
            user=user,
            schema=MAIL_READER_SCHEMA,
            cache_parts=cache_parts,
            max_tokens=800,
        )
        elapsed = time.perf_counter() - start
        print(f"\n[LIVE API CALL SUCCESS] Completed in {elapsed:.2f}s")
        print("Valid JSON Schema Output received:")
        for k, v in result.items():
            print(f"  {k}: {v}")
        print(f"\nRecorded spend: ${client.budget_guard.spent_usd:.6f}")
    except Exception as exc:
        print(f"\n[LIVE API CALL FAILED]: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
