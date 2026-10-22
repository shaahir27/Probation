---
feature: "Exam Operators and Validators"
phase: "Phase 7 — Exam Board"
status: "Built"
---

# Feature: Exam Operators and Validators

## 1. Overview
* **Name:** Exam Operators and Validators
* **Phase:** Phase 7 — Exam Board
* **Purpose:** Provides pack-specific perturbation operators (both pure-code heuristics and LLM rewrites) and deterministic code validators for counterfactual stress-testing of policies across Mail, Calendar, and Files packs.
* **Traces to:** `ENGINE_SPEC.md` §15, `PACKS_SPEC.md` §1.7, §2.7, §3.7, `CONTRACT.md` I-15, `PROMPTS.md` §8.

## 2. Technical Rationale
* **How we achieved it:** Implemented counterfactual and safety operators across Mail, Calendar, and Files packs with corresponding strict validators:
  - Mail operators: `exam.paraphrase.v1` (invariance), `exam.add_money_request.v1` (critical safety), `exam.add_personal_info_request.v1` (critical safety), plus code fallbacks.
  - Calendar operators: `paraphrase_title` (invariance), `change_time_minor` (other), `change_time_major` (other), `add_new_attendee` (other), `add_money_request` (critical safety).
  - Files operators: `rename_trivial` (invariance), `size_jitter` (invariance), `origin_unknown` (other), `executable_extension` (critical safety), `double_extension` (critical safety), `misleading_name` (critical safety).
* **Alternatives considered:** None; exact operator semantics, expected invariance vs safety constraints, and code validators are defined in `PACKS_SPEC.md`.
* **Why we chose this path:** Pure-code validators verify that simulated perturbations meet semantic requirements (e.g., currency symbols for money requests, PII patterns for personal info, non-empty diffs for paraphrasing) before applying them during an exam.

## 3. Database Schema Impact
* **Changes made:** None directly from operators; perturbations run in memory or are recorded as exam situation variants.

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `apply_mail_operator`, `validate_mail_operator_result` (`backend/src/probation/packs/mail/exam_ops.py`):
    - **Why it is called:** Generates and validates mutated email situations for exam runs.
    - **How it is called & callers:** Called by `engine/exam.py` during exam case generation.
  * `apply_calendar_operator`, `validate_calendar_operator_result` (`backend/src/probation/packs/calendar/exam_ops.py`):
    - **Why it is called:** Mutates calendar events (title, time, attendees) and validates mutations.
    - **How it is called & callers:** Called by `engine/exam.py` during calendar exam runs.
  * `apply_files_code_operator`, `validate_files_operator_result` (`backend/src/probation/packs/files/exam_ops.py`):
    - **Why it is called:** Perturbs file paths, sizes, and origins to evaluate invariance and safety.
    - **How it is called & callers:** Called by `engine/exam.py` for file situations.

```python
def validate_mail_operator_result(operator_name: str, original: dict[str, Any], mutated: dict[str, Any]) -> bool:
    ...
```

## 5. Testing & Verification
* **Automated tests:** `backend/tests/unit/test_exam_board.py`
  - `test_files_pack_operators_and_validators`: Verifies all 6 file operators and validators.
  - `test_calendar_pack_operators_and_validators`: Verifies calendar operators.
  - `test_mail_pack_operators_and_validators`: Verifies invariance and critical safety operators.
* **Manually verified:** Verified that invalid operator mutations return `False` from validators.

## 6. Dependencies & Deferred Work
* **Depends on:** `llm/client.py` for LLM paraphrase perturbations when configured, with robust deterministic fallback.
* **Known issues/deferred:** None.


## WP1 repair update - 22 October 2026

### 1. Overview
Deterministic retry identity and atomic exam storage. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5; CONTRACT remains unchanged.

### 2. Technical rationale
Exam IDs bind the bounded input rows, operators, settings, requested pair/level/time, seed, policy/model versions and explicit attempt ordinal. Case IDs bind run/base/operator. Retries return stored results. Examiner-owned run/case/ledger writes use one unit of work and preserve a parent transaction. CLI --attempt requests a deliberately distinct attempt. Existing exam realism gaps are not claimed fixed; WP5 remains required.

### 3. Database schema impact
No persistent schema/ledger-byte migration or new dependency.

### 4. Core logic and necessary functions
backend/src/probation/engine/exam.py: run_exam(..., clock=None, attempt_ordinal=0). backend/src/probation/engine/exam_storage.py: load_exam(access, run_id), persist_exam(access, result, *, now_iso, model_id, cases). backend/src/probation/workers/examiner.py: run_examiner_job(..., attempt_ordinal=0).
Why/how called: Exam IDs bind the bounded input rows, operators, settings, requested pair/level/time, seed, policy/model versions and explicit attempt ordinal. Case IDs bind run/base/operator. Retries return stored results. Examiner-owned run/case/ledger writes use one unit of work and preserve a parent transaction. CLI --attempt requests a deliberately distinct attempt. Existing exam realism gaps are not claimed fixed; WP5 remains required.

### 5. Testing and verification
Test files test_wp1_clock.py, test_wp1_time_boundaries.py, test_exam_board.py and operator tests.
An earlier isolated full checkpoint passed 291 tests plus lint/types; later targeted results are recorded in docs/reports/wp1-progress-2026-10-22.md. Final checks remain required after all edits.

### 6. Dependencies and remaining work
WP0 committed c92131c; WP1 is in progress. See the progress report for open role/transaction, canonical-payload, clock/identity and handoff requirements. This update is not a WP1 completion claim or live-provider proof.
