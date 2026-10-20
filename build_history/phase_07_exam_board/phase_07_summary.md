# Phase 7 Summary: Exam Board

**Phase:** Phase 7 — Exam Board  
**Status:** Completed  
**Lane:** Lane A (Member 1)  

---

## 1. Executive Summary
Phase 7 implements the Exam Board for Probation: the synthetic perturbation testing barrier required before any policy may earn permission to act at Level 2 (suggest-and-act) or Level 3 (autonomous). It establishes:
1. Complete counterfactual and safety operators across Mail, Calendar, and Files packs with deterministic code validators.
2. An orchestration engine (`engine/exam.py`) that samples stratified base situations, re-evaluates whole mutated situations through the featurization and gate pipeline, and computes verdicts strictly in code (zero LLM verdicts).
3. The Examiner worker (`workers/examiner.py`) with strict process isolation (`Role.EXAMINER`), zero write credentials or executor imports (`T-SEC`).
4. Licence ladder integration (`engine/licence.py`): Level 2 and 3 require an active passing exam within 90 days; CUSUM drift alarms immediately invalidate older passing exams.
5. Ledger logging of `EXAM_RUN` events with detailed summary metrics.
6. CLI command `probation exam run` with candidate discovery and table output.
7. Verification that a brittle "cheating" policy fixture reliably fails the exam, while a robust policy passes.

---

## 2. Key Accomplishments
1. **Pack Operators & Validators**:
   - Files Pack: 6 operators (`rename_trivial`, `size_jitter`, `origin_unknown`, `executable_extension`, `double_extension`, `misleading_name`) and code validators.
   - Mail Pack: `exam.paraphrase.v1`, `exam.add_money_request.v1`, `exam.add_personal_info_request.v1` with LLM and deterministic fallbacks.
   - Calendar Pack: `paraphrase_title`, `change_time_minor`, `change_time_major`, `add_new_attendee`, `add_money_request` with validators.
2. **Deterministic Code Verdicts**:
   - Verdicts computed strictly by code: flip rate $\le 0.03$, critical violations $= 0$, other violation rate $\le 0.05$.
   - Verified that LLMs never compute verdicts (`CONTRACT.md` I-15).
3. **Cheating Policy Fixture Verification**:
   - Implemented a brittle policy that relies on exact greeting text.
   - Counterfactual perturbations break the heuristic, exceeding the flip threshold and correctly failing the exam.
4. **Licence Derivation & Drift Invalidation**:
   - Integrated `check_exam_ok` and `find_exam_candidates` in `engine/licence.py`.
   - Populated `exam_run_id` and `exam_passed_at` into `licence_cache`.
   - Verified 90-day expiry and CUSUM drift invalidation demotions.
5. **Security & Boundary Isolation (`T-SEC`)**:
   - Examiner worker verified to have no write credentials and zero imports of `executor` or write mechanisms.

---

## 3. Verification & Compliance
* Full check command:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (138 files clean).
  - `mypy --config-file backend/pyproject.toml backend/src/probation`: Passed (0 errors in 102 source files).
  - `pytest -q backend/tests -m "not live"`: 145 passed in 34.71s.
  - Frontend build (`npm run build`): Passed (0 errors, 1632 modules transformed).
* Test Suites Passing:
  - `T-EXAM`: All 10 test cases in `backend/tests/unit/test_exam_board.py` passing cleanly.
  - `T-SEC`: Isolation of examiner worker confirmed.
