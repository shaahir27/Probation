---
feature: "PII Redaction Pipeline and Resilient LLM Client"
phase: "Phase 1 — Core, Database, Ledger, LLM Client, Redaction"
status: "Built"
---

# Feature: PII Redaction Pipeline and Resilient LLM Client

## 1. Overview
* **Name:** PII Redaction Pipeline and Resilient LLM Client
* **Phase:** Phase 1 — Core, Database, Ledger, LLM Client, Redaction
* **Purpose:** Implements local deterministic PII sanitization before network egress (invariant I-14), token expenditure tracking with hard budget caps (invariant I-15), deterministic response caching (invariant I-16), retry resilience on HTTP 429/5xx, structured output fallback with repair retries, and exposure audit logging.
* **Traces to:** `CONTRACT.md` section 6, invariants I-1, I-3, I-14, I-15, I-16, and `PROMPTS.md` sections 1, 2.

## 2. Technical Rationale
* **How we achieved it:** Built a multi-stage regex pipeline scrubbing email quoted history and signatures, followed by numbered typed placeholder substitutions (`<TYPE_n>`) with Luhn card verification and Aadhaar negative boundary checks. Built `LLMClient` supporting OpenAI-compatible structured output `json_schema` with automatic fallback to JSON-only mode and 1 repair retry on schema failure. Enforced `BudgetGuard` pre-flight checks and SQLite-backed `exposure_log` accounting.
* **Alternatives considered:** None. The specification strictly requires local regex redaction and Nebius Token Factory inference.
* **Why we chose this path:** Guarantees zero sensitive data leakage to external models while ensuring high availability and cost predictability.

## 3. Database Schema Impact
* **Changes made:** Utilizes `llm_cache` and `exposure_log` tables in `schema.sql`.

## 4. Core Logic & Necessary Functions
* `redact` (`backend/src/probation/llm/redact.py`): Local deterministic PII sanitization.
  - **Why it is called:** Executed before every external LLM call to strip private tokens.
  - **How it is called & callers:** Called by `brain` and `examiner` workers prior to prompt formatting.
* `LLMClient.chat_json`, `LLMClient.chat_text` (`backend/src/probation/llm/client.py`): Resilient inference client.
  - **Why it is called:** Manages token generation with budget verification, retries, caching, and structured output parsing.
  - **How it is called & callers:** Invoked by reader, writer, wording, and exam operators.
* `BudgetGuard` (`backend/src/probation/llm/budget.py`): Spend guard.
  - **Why it is called:** Enforces hard spend ceilings ($20.00 USD) and fails closed with `BudgetExceeded`.
  - **How it is called & callers:** Called by `LLMClient` before dispatching network requests.

```python
def redact(
    text: str,
    *,
    display_names: Iterable[str] | None = None,
    profile: str = "mail",
) -> RedactionResult: ...

class LLMClient:
    def chat_json(self, *, kind: str, model: str, system: str, user: str, schema: dict[str, Any], cache_parts: dict[str, str], ...) -> dict[str, Any]: ...
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_redaction_pipeline.py` (`T-REDACT`: positive and negative tests across all 10 PII patterns)
  - `backend/tests/unit/test_llm_client_and_budget.py` (`T-LLM`: retries, fallback, 1 repair retry, cache hit, budget cap)
* **Manually verified:** Ran `python -m probation.cli budget show`.

## 6. Dependencies & Deferred Work
* **Depends on:** `core/types.py`, `config/prices.json`.
* **Known issues/deferred:** None.


## WP1 repair update - 22 October 2026

### 1. Overview
Strict output validation and atomic inference recording. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5; CONTRACT remains unchanged.

### 2. Technical rationale
LLMClient validates fresh and cached output through strict Pydantic schemas and registered semantic models. It records cache plus exposure after HTTP in one savepoint. The caller retains transaction ownership; a failed exposure insert cannot leave an unaccounted cache entry. Inference uses the runtime context clock. Cache values retain numeric precision.

### 3. Database schema impact
No persistent schema/ledger-byte migration or new dependency.

### 4. Core logic and necessary functions
backend/src/probation/llm/jobs.py: strict fourteen-job models and validate_job_output(data, prompt_id, prompt_version). backend/src/probation/llm/schema.py: compile_schema(schema), validate_json_schema(data, schema). backend/src/probation/db/inference.py: record_inference(conn, *, cache_key, ..., created_at, ...). backend/src/probation/llm/client.py: LLMClient(..., clock=None).
Why/how called: LLMClient validates fresh and cached output through strict Pydantic schemas and registered semantic models. It records cache plus exposure after HTTP in one savepoint. The caller retains transaction ownership; a failed exposure insert cannot leave an unaccounted cache entry. Inference uses the runtime context clock. Cache values retain numeric precision.

### 5. Testing and verification
Test files test_wp1_validation.py, test_wp1_context.py and test_llm_client_and_budget.py (T-LLM). See docs/LLM_SCHEMA_SUPPORT.md for the exact supported surface.
An earlier isolated full checkpoint passed 291 tests plus lint/types; later targeted results are recorded in docs/reports/wp1-progress-2026-10-22.md. Final checks remain required after all edits.

### 6. Dependencies and remaining work
WP0 committed c92131c; WP1 is in progress. See the progress report for open role/transaction, canonical-payload, clock/identity and handoff requirements. This update is not a WP1 completion claim or live-provider proof.
