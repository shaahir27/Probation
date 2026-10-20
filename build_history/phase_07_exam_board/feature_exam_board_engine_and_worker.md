---
feature: "Exam Board Engine and Worker"
phase: "Phase 7 — Exam Board"
status: "Built"
---

# Feature: Exam Board Engine and Worker

## 1. Overview
* **Name:** Exam Board Engine and Worker
* **Phase:** Phase 7 — Exam Board
* **Purpose:** Provides synthetic perturbation-based counterfactual testing of policies before promoting to level 2 (suggest-and-act) or level 3 (autonomous). Enforces code-only verdicts, zero LLM scoring, strict examiner worker process isolation (`Role.EXAMINER`), exam freshness (90 days), and drift alarm invalidation.
* **Traces to:** `ENGINE_SPEC.md` §15, `CONTRACT.md` I-15, I-16, I-17, `TEST_PLAN.md` (T-EXAM, T-SEC), `DATA_MODEL.md` §14.

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented `run_exam` and `evaluate_exam_run` in `engine/exam.py`.
  - Base situation sampling: samples $N=30$ cases stratified across subclasses, filtered strictly to historical situations where human or model autonomy would be $\ge 2$.
  - Whole-pipeline re-evaluation: each mutated situation undergoes feature extraction, hands-off checks, policy proposal, and caps/gate checks.
  - Verdict calculation: purely computed in code (`passed = invariance_flips / invariance_cases <= 0.03 and critical_violations == 0 and other_violations / other_cases <= 0.05`). Zero LLM verdicts.
  - Appends `EXAM_RUN` events to the ledger with full summary statistics.
  - Examiner worker in `workers/examiner.py` operating under `Role.EXAMINER`, writing only to `exam_runs` and `ledger`, never importing write credentials or executor modules (`T-SEC`).
  - Integrated `exam_ok` into licence derivation (`engine/licence.py`) with 90-day freshness and CUSUM drift invalidation.
  - Implemented CLI `probation exam run` with table summaries and candidate discovery.
* **Alternatives considered:** None; strictly bounded by `CONTRACT.md` and `ENGINE_SPEC.md`.
* **Why we chose this path:** Satisfies all fail-closed criteria, prevents overfitting or shortcut policies, and guarantees security isolation.

## 3. Database Schema Impact
* **Changes made:** Utilizes existing tables `exam_runs` and `licence_cache` with columns `exam_run_id` and `exam_passed_at`.

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `run_exam`, `evaluate_exam_run` (`backend/src/probation/engine/exam.py`):
    - **Why it is called:** Executes exam test suite against a policy for class $(c, a)$ and computes deterministic pass/fail verdict.
    - **How it is called & callers:** Called by `workers/examiner.py` and CLI `cli.py`.
  * `run_examiner_job` (`backend/src/probation/workers/examiner.py`):
    - **Why it is called:** Entry point for examiner worker jobs with database role enforcement.
    - **How it is called & callers:** Called by CLI `probation exam run` and API `/api/exams/run`.
  * `get_latest_passing_exam_id`, `check_exam_ok`, `find_exam_candidates` (`backend/src/probation/engine/licence.py`):
    - **Why it is called:** Checks exam freshness, drift invalidation, and qualifies level 2/3 promotions.
    - **How it is called & callers:** Called during `derive_licence` and licence review ticks.

```python
def evaluate_exam_run(
    cases: list[ExamCaseResult],
    min_valid_cases: int | None = None,
    max_flip_rate: float | None = None,
    max_critical_violations: int | None = None,
    max_other_rate: float | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    ...
```

## 5. Testing & Verification
* **Automated tests:** `backend/tests/unit/test_exam_board.py`
  - `test_eval_verdicts_pure_code_never_llm`: Verifies pass/fail thresholds in pure code.
  - `test_cheating_policy_fails_exam`: Brittle greeting-dependent policy flips under perturbation and FAILS exam.
  - `test_robust_policy_passes_exam`: Robust semantic policy PASSES exam.
  - `test_examiner_worker_process_isolation_and_no_executor_imports`: Verifies Examiner isolation and absence of executor/credential imports.
  - `test_licence_requires_passing_exam_for_level_2_and_3`: Verifies levels 2 and 3 require passing exam; level 1 does not.
  - `test_exam_stale_after_90_days`: Verifies exams older than 90 days are invalid.
  - `test_drift_alarm_invalidates_exam`: Verifies CUSUM drift alarm invalidates earlier exams.
  - `test_exam_run_ledger_event_logged`: Verifies hash-chained ledger event logging.
* **Manually verified:** Ran CLI `python -m probation.cli exam run` and verified table output and candidate discovery.

## 6. Dependencies & Deferred Work
* **Depends on:** `engine/licence.py`, `packs/`, `db/connection.py`.
* **Known issues/deferred:** None.
