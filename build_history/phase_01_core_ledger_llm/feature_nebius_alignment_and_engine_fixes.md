---
feature: "Nebius Model Alignment and Phase 1 Engine Remediation"
phase: "Phase 1 — Core, Database, Ledger, LLM Client, Redaction"
status: "Updated"
---

# Feature: Nebius Model Alignment and Phase 1 Engine Remediation

## 1. Overview
* **Name:** Nebius Model Alignment and Phase 1 Engine Remediation
* **Phase:** Phase 1 — Core, Database, Ledger, LLM Client, Redaction
* **Purpose:** Align LLM model identifiers and token pricing with official Nebius Token Factory live endpoints; harden JSON schema parsing against reasoning traces (`<think>` blocks); fix self-inclusion in history clues (P0-2); fix calendar invite situation extraction (P0-3); fix CUSUM/PSI drift tracking and demotion integration (P0-5); add webfacts batch vetting command (P0-7).
* **Traces to:** `CONTRACT.md` Invariants I-1, I-6, I-14, I-15; `ENGINE_SPEC.md` section 3, 11; `PACKS_SPEC.md` section 0.3, 1.2, 2.1-2.5; `TEST_PLAN.md` T-LLM, T-NOPEEK, T-CUSUM, T-PSI.

## 2. Technical Rationale
* **How we achieved it:**
  - Updated model IDs to `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/nemotron-3-super-120b-a12b`, and `nvidia/Nemotron-3-Ultra-550b-a55b`.
  - Added robust reasoning trace stripping (`<think>` / `<thought>`) and pure JSON schema validation in `LLMClient`.
  - Resolved `s.raw_item_id` self-inclusion in `packs/mail/clues.py` and `packs/calendar/clues.py`.
  - Configured calendar import to assign `my_status="NEEDS-ACTION"` to incoming invites and extracted attendee `PARTSTAT`.
  - Extended CUSUM tracking in `engine/replay.py` to record sequential error evidence for all model proposals (`x_t = 1 if disagreement else 0`).
  - Added quantile binning for numeric features in `engine/drift.py` to eliminate false PSI alarms.
* **Alternatives considered:** None; exact mathematical formulas and invariants dictated by specifications.
* **Why we chose this path:** Guarantees strict fail-closed behavior, contract compliance, and deterministic replay.

## 3. Database Schema Impact
* **Changes made:** None to SQLite tables; all updates respect existing schema and role access boundaries.

## 4. Core Logic & Necessary Functions
* `probation.llm.client.LLMClient` (`backend/src/probation/llm/client.py`): Real token-metered chat completions via Nebius Token Factory with pure schema validator and repair fallback.
* `probation.packs.mail.clues.deterministic_clues` (`backend/src/probation/packs/mail/clues.py`): Computes sender tiers without self-inclusion.
* `probation.packs.calendar.clues.deterministic_clues` (`backend/src/probation/packs/calendar/clues.py`): Computes calendar conflict and organizer metrics without self-inclusion.
* `probation.synth.importers.import_calendar` (`backend/src/probation/synth/importers.py`): Correctly stores arrival `my_status` for incoming invitations.
* `probation.engine.drift.check_family_shift` (`backend/src/probation/engine/drift.py`): 10-quantile binning for numeric features, category binning for categoricals.
* `probation.engine.replay.run_replay` (`backend/src/probation/engine/replay.py`): Real-time CUSUM error tracking on all proposals.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_llm_client_and_budget.py` (T-LLM)
  - `backend/tests/unit/test_registry_and_workers.py` (T-ID, T-PACK)
  - `backend/tests/unit/test_drift_cusum_psi.py` (T-CUSUM, T-PSI)
  - `backend/tests/property/test_no_peeking.py` (T-NOPEEK)
  - `backend/tests/integration/test_backtest_e2e.py` (T-E2E)
  - **All 165 unit tests, 4 property/integration tests pass with 100% pass rate.**
  - `mypy --strict` passes on `core/` and `engine/` with 0 issues in 21 source files.
  - `ruff check` and `ruff format --check` pass completely.
* **Manually verified:**
  - Ran live 1-call smoke test against Nebius Token Factory with real API credits ($0.000141 cost).

## 6. Dependencies & Deferred Work
* **Depends on:** Nebius Token Factory API key for live inference; local fixtures for test suite.
* **Known issues/deferred:** Ready for Phase 2 evaluation and full timeline backtest calibration.
