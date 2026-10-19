---
feature: "Entity Facts Service and Tavily Vetting"
phase: "Phase 6b — Entity Facts Service (Tavily Vetting)"
status: "Built"
---

# Feature: Entity Facts Service and Tavily Vetting

## 1. Overview
* **Name:** Entity Facts Service and Tavily Vetting
* **Phase:** Phase 6b — Entity Facts Service (Tavily Vetting)
* **Purpose:** Out-of-band sender and link domain vetting via Tavily Search and verified local brand mapping, enforcing the asymmetric web veto (`web_cap = 1`) and strict query guarding without policy bias.
* **Traces to:** `CONTRACT.md` invariants I-21 to I-26, `TAVILY_AND_NEW_PACKS.md` sections 3-6, 11, 12, `PROMPTS.md` section 15, and `TEST_PLAN.md` T-WEBQ, T-WEBISO, T-VET.

## 2. Technical Rationale
* **How we achieved it:**
  - **Deterministic Query Guard (`web/query_guard.py`)**: Whitelisted allowed characters (`^[a-zA-Z0-9\s.\-&']+$`), max 80 characters, max 12 tokens, blocking `@`, `<`, `>`, `http`, 6-digit runs, `<PERSON_n>`, and user name tokens.
  - **Deterministic Derivation (`web/derive.py`)**: Domain parsing, homoglyph normalization (`0->o`, `1->l`, `rn->m`, `vv->w`), Levenshtein distance ($\le 2$), label containment, and status precedence (`lookalike` > `reports_found` > `confirmed_official` > `no_web_presence` > `unverified`).
  - **Production Tavily Client (`web/client.py`)**: Automatic retries, daily call cap (100) and monthly budget guard (800), and full audit logging in `tavily_calls`.
  - **Isolation Boundary (`web/view.py`)**: `WebFactsView` exposing `RestrictionOnly` schemas containing no probability or evidence weights. `policy.py`, `evidence.py`, `licence.py`, and `features.py` have zero imports from `probation.web`.
  - **Offline Fixtures (`tests/fixtures/web_facts_fixtures.json`, `web/fixtures.py`)**: Curated entity catalog ensuring 100% deterministic, offline test execution and backtests.
* **Alternatives considered:** Calling LLM to evaluate sender legitimacy was rejected (`TAVILY_AND_NEW_PACKS.md` section 4) due to prompt-injection vulnerabilities and non-determinism.
* **Why we chose this path:** Preserves the core thesis: "The web can warn you. Only your history can trust."

## 3. Database Schema Impact
* **Tables populated:**
  - `web_facts`: Cached entity status, facts JSON, sources JSON, origin, fetched_at, ttl_until.
  - `tavily_calls`: Audit log of every query text, parameters, credit usage, latency, and success status.
  - `proposals.web_json`: Structured record `{"status": str, "cap": int, "source_ids": list}`.

## 4. Core Logic & Necessary Functions
* `validate_tavily_query` (`backend/src/probation/web/query_guard.py`): Validates outbound search queries.
* `derive_entity_facts` (`backend/src/probation/web/derive.py`): Derives EntityFacts deterministically from results.
* `check_local_brand_list` (`backend/src/probation/web/derive.py`): Zero-network verified brand pre-check.
* `TavilyClient.search` (`backend/src/probation/web/client.py`): Guarded HTTP client with budget accounting.
* `WebFactsView.get_entity_facts` (`backend/src/probation/web/view.py`): Restriction-only view for engine caps.
* `vet_entity` (`backend/src/probation/workers/webfacts.py`): Worker vetting pipeline under `Role.WEBFACTS`.
* `load_web_facts_fixtures` (`backend/src/probation/web/fixtures.py`): Preloads recorded fixtures for offline replays.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_tavily_webfacts.py`: 16 tests passing `T-WEBQ`, `T-WEBISO`, and `T-VET`.
  - `.\make.cmd check`: Ruff, Mypy, and Pytest passing with zero errors.
* **CLI verification:**
  - `probation webfacts vet <domain>`: Verified on `github.com` and `g00gle.com`.
  - `probation webfacts audit`: Verified on `tavily_calls` table.
  - `probation webfacts load-fixtures`: Loaded 9 fixtures.
