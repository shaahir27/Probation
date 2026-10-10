---
feature: "Day-1 Spike Scripts and Budget Verification"
phase: "Phase 0 — Foundations and Spikes"
status: "Built"
---

# Feature: Day-1 Spike Scripts and Budget Verification

## 1. Overview
* **Name:** Day-1 Spike Scripts and Budget Verification
* **Phase:** Phase 0 — Foundations and Spikes
* **Purpose:** Resolve the critical Day-1 technical unknowns: Nebius Token Factory connection & strict JSON-schema parsing (O-1, O-2), local CPU embedding latency with ONNX `fastembed` (O-6), Tavily Search and Extract runtime calls for the $3,000 Hackathon bonus track (O-17), sandbox policy evaluation (O-4), and token price table validation (O-14).
* **Traces to:** `IMPLEMENTATION_PLAN.md` Phase 0 tasks 49-53; `DECISIONS_AND_OPEN_QUESTIONS.md` section 3 (O-1, O-2, O-4, O-6, O-14, O-17); `TAVILY_AND_NEW_PACKS.md` section 12.

## 2. Technical Rationale
* **How we achieved it:**
  - `scripts/spike_llm.py`: Implements Pydantic v2 structured output parse test (`client.beta.chat.completions.parse`) targeting Nebius Token Factory with Nemotron models (`nvidia/nemotron-mini-4b-instruct`, `nvidia/nemotron-4-340b-instruct`) and automatic graceful fallback to standard markdown JSON completions.
  - `scripts/spike_embed.py`: Evaluates local CPU ONNX embedding throughput on `sentence-transformers/all-MiniLM-L6-v2` with `fastembed`.
  - `scripts/spike_tavily.py`: Tests out-of-band Tavily Search and Extract endpoints, printing credit usage and latency to secure early bonus eligibility.
  - `scripts/verify_budget.py`: Loads `config/prices.json` and evaluates token expenditure scenarios against the hard budget cap ($20.00 USD).
  - `deploy/openshell/README.md`: Explores NVIDIA OpenShell sandbox egress allow-lists and documents the time-boxed decision.
* **Alternatives considered:** None; required by Phase 0 plan.
* **Why we chose this path:** Resolving external API dependencies on Day 1 prevents downstream blocking during Phase 1 (LLMClient) and Phase 6b (Tavily vetting).

## 3. Database Schema Impact
* **Changes made:** None (pure scripts and documentation).

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `run_llm_spike` (`scripts/spike_llm.py`): Tests OpenAI-compatible Nebius Token Factory endpoint with schema-validated outputs.
    - **Why it is called:** Verifies whether Nemotron models support OpenAI-compatible strict JSON schema parsing or require the repair fallback path.
    - **How it is called & callers:** Run via CLI: `python scripts/spike_llm.py`.
  ```python
  def run_llm_spike() -> None: ...
  ```

  * `run_embed_spike` (`scripts/spike_embed.py`): Benchmarks local CPU ONNX vector embeddings.
    - **Why it is called:** Measures CPU inference throughput to guarantee sub-millisecond retrieval without PyTorch dependency.
    - **How it is called & callers:** Run via CLI: `python scripts/spike_embed.py`.
  ```python
  def run_embed_spike() -> None: ...
  ```

  * `run_tavily_spike` (`scripts/spike_tavily.py`): Executes runtime search and extract calls.
    - **Why it is called:** Establishes working integration proof for the $3,000 Tavily Hackathon Bonus track.
    - **How it is called & callers:** Run via CLI: `python scripts/spike_tavily.py`.
  ```python
  def run_tavily_spike() -> None: ...
  ```

  * `verify_budget` (`scripts/verify_budget.py`): Validates pricing rates and models token expenditure.
    - **Why it is called:** Verifies that a full synthetic persona run stays within the $20.00 hard budget limit.
    - **How it is called & callers:** Run via CLI: `python scripts/verify_budget.py`.
  ```python
  def verify_budget() -> None: ...
  ```

## 5. Testing & Verification
* **Automated tests:** Scripts handle missing API keys gracefully and validate configurations.
* **Manually verified:**
  - Executed `python scripts/verify_budget.py`: confirmed rates loaded from `config/prices.json`, 2,000 email scenario estimated at $0.1224 USD (99.4% margin remaining).
  - Executed `python scripts/spike_llm.py`: confirmed clean dry-run diagnostics when `LLM_API_KEY` is not present.
  - Executed `python scripts/spike_tavily.py`: confirmed clean dry-run diagnostics when `TAVILY_API_KEY` is not present.
  - Executed `python scripts/spike_embed.py`: confirmed clean dry-run diagnostics for `fastembed`.

## 6. Dependencies & Deferred Work
* **Depends on:** `openai`, `httpx`, `fastembed`, `pydantic`.
* **Known issues/deferred:**
  - Live execution against Nebius and Tavily requires user-provided API credentials via `.env`.
