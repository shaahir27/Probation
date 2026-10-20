# Phase 7 handoff

Branch / commit: `phase-7-exam-board` / pending commit

## Done
Phase 7 implements the Exam Board — the adversarial counterfactual testing barrier required before any policy may earn permission to act autonomously at Level 2 (suggest-and-act) or Level 3 (autonomous). In plain words:
1. **Pack Operators & Code Validators**:
   - Files Pack: 6 operators (`rename_trivial`, `size_jitter`, `origin_unknown`, `executable_extension`, `double_extension`, `misleading_name`) and deterministic code validators.
   - Mail Pack: Counterfactual invariance operators (`exam.paraphrase.v1`) and critical safety perturbation operators (`exam.add_money_request.v1`, `exam.add_personal_info_request.v1`) with LLM rewrites and deterministic fallbacks, validated by code.
   - Calendar Pack: `paraphrase_title`, `change_time_minor`, `change_time_major`, `add_new_attendee`, `add_money_request` with code validators.
2. **Exam Orchestration Engine (`engine/exam.py`)**:
   - Samples stratified base situations from history filtered to cases where autonomy would be $\ge 2$ (historical human action or policy proposal).
   - Re-evaluates each perturbed situation through the full featurization, hands-off detection, policy proposal, and caps/gate pipeline.
   - Computes pass/fail verdicts strictly in code (zero LLM verdicts): invariance flip rate $\le 0.03$, critical violations $= 0$, other violation rate $\le 0.05$.
   - Verified that a brittle "cheating" policy fixture relying on exact greeting keywords FAILS the exam, while a robust semantic policy PASSES.
   - Appends `EXAM_RUN` events to the hash-chained ledger.
3. **Examiner Worker Isolation (`workers/examiner.py`)**:
   - Operates strictly under `Role.EXAMINER`, writing only to `exam_runs` and `ledger`.
   - Verified zero write credentials and zero imports of `executor` or write mechanisms (`T-SEC`).
4. **Licence Derivation Integration (`engine/licence.py`)**:
   - Levels 2 and 3 require an active passing exam within 90 days (`check_exam_ok`).
   - CUSUM drift alarms immediately invalidate earlier passing exams, causing dynamic demotion to Level 1.
   - Added `find_exam_candidates` discovering qualifying candidate pairs $(c, a)$ for Level 2 or 3.
5. **Replay, Scheduler, CLI & API Alignment**:
   - Integrated candidate testing into replay and scheduler `LICENCE_REVIEW` ticks.
   - Added CLI `probation exam run` with Rich table summaries and candidate discovery.
   - Connected `POST /api/exams/run` to real examiner job execution and aligned frontend `InsightsView.tsx`.

## Files changed
- `backend/src/probation/config.py` (added exam tunables: valid days, sample count, thresholds, edit model)
- `backend/src/probation/packs/files/exam_ops.py` (implemented 6 file operators and code validators)
- `backend/src/probation/packs/mail/exam_ops.py` (implemented mail operators and code validators)
- `backend/src/probation/packs/calendar/exam_ops.py` (implemented calendar operators and code validators)
- `backend/src/probation/engine/exam.py` (implemented exam orchestration, case generation, code verdict calculation, and ledger logging)
- `backend/src/probation/workers/examiner.py` (implemented Examiner worker with role boundary isolation)
- `backend/src/probation/engine/licence.py` (integrated passing exam check, 90-day expiry, drift invalidation, and candidate discovery)
- `backend/src/probation/engine/replay.py` (integrated exam review ticks)
- `backend/src/probation/workers/scheduler.py` (integrated exam review into nightly schedule)
- `backend/src/probation/api/routes/insights.py` (wired POST /api/exams/run to examiner worker)
- `frontend/src/views/InsightsView.tsx` (aligned diagnostic exam action to contract action REPLY)
- `backend/src/probation/cli.py` (added rich `probation exam run` CLI command)
- `backend/tests/unit/test_exam_board.py` (unit tests covering all T-EXAM and T-SEC requirements)
- `build_history/phase_07_exam_board/feature_exam_operators_and_validators.md` (new feature log)
- `build_history/phase_07_exam_board/feature_exam_board_engine_and_worker.md` (new feature log)
- `build_history/phase_07_exam_board/phase_07_summary.md` (new summary log)
- `build_history/index.md` (updated master index)

## Tests
- Command: `python -m pytest -q backend/tests -m "not live"`
  - Result: 145 passed in 34.71s
- Command: `python -m ruff check backend`
  - Result: All checks passed (0 errors)
- Command: `python -m ruff format --check backend`
  - Result: 138 files already formatted
- Command: `python -m mypy --config-file backend/pyproject.toml backend/src/probation`
  - Result: Success: no issues found in 102 source files
- Command: `npm run build` (in `frontend/`)
  - Result: Built successfully (0 TypeScript or bundle errors)
- Test IDs passing:
  - `T-EXAM`:
    - Files pack operators and validators
    - Calendar pack operators and validators
    - Mail pack operators and validators
    - Pass/fail verdicts computed in pure code
    - Cheating policy fixture fails exam
    - Robust policy passes exam
    - Levels 2 and 3 require passing exam; Level 1 does not
    - Exams expire after 90 days
    - CUSUM drift alarm invalidates earlier exams
    - `EXAM_RUN` hash-chained ledger event logged
  - `T-SEC`:
    - Process isolation: Examiner worker has no executor imports and no write credentials

## Invariants touched
- `I-2`: Only the Executor worker holds write credentials and executes side-effects. Examiner worker strictly isolated (`Role.EXAMINER`).
- `I-3`: Fail-closed behaviour. Exam errors or insufficient cases produce `FAIL` with descriptive reason.
- `I-4`: No peeking. Exams run as of a fixed point in time; historical base situations are strictly past-only.
- `I-5`: Append-only, hash-chained ledger. `EXAM_RUN` events appended via `ledger.append()`.
- `I-8`: Caps and hands-off rules remain hard-coded. Mutated situations containing blocked extensions or malicious payloads trigger hands-off demotions.
- `I-9`: Zero system clock calls outside `core/clock.py`.
- `I-15`: The examiner is not an LLM. Verdicts are computed strictly by deterministic Python code.
- `I-16`: Licences are derived from evidence and active exam passes, not stored as ground truth.
- `I-17`: Any statistical drift alarm revokes level 2 and level 3 licences by invalidating exams completed before the alarm.

## Deviations and assumptions
- Mail and calendar LLM paraphrase operators use `model_exam_edits` (`nvidia/nemotron-mini-4b-instruct`) when live LLM is configured, with deterministic keyword-substitution and typographical fallbacks for offline testing and fast replay.

## Contract change requests
None. `CONTRACT.md` remains untouched.

## New dependencies
None.

## LLM cost incurred
$0.00 (unit tests run deterministically offline with deterministic operator fallbacks).

## Open questions
None.

## Suggested next step
Phase 8: Chains and habits (or review by user before starting Phase 8).
