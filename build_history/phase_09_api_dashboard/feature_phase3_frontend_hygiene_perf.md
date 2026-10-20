---
feature: "Phase 3 Remediation: Frontend Production Build, Hygiene, and Performance Optimization"
phase: "Phase 3 — Mail and Calendar packs (Remediation) & Dashboard"
status: "Built"
---

# Feature: Phase 3 Remediation: Frontend Production Build, Hygiene, and Performance Optimization

## 1. Overview
* **Name:** Phase 3 Remediation: Frontend Production Build, Hygiene, and Performance Optimization
* **Phase:** Phase 3 / Phase 9 — Frontend, Hygiene, and Performance
* **Purpose:** Address audit items H10 and P2: eliminate mock fallbacks and hardcoded backend URLs in the frontend dashboard, filter non-action `ABSTAIN` out of report card task listings, fix false positives in OTP detection using regex word boundaries, remove executable script extensions from hands-off blocks, remove stray directories, and optimize resolver performance.
* **Traces to:** `docs/USER_FLOW.md`, `docs/ENGINE_SPEC.md` §8, and `docs/PACKS_SPEC.md` §1.2.

## 2. Technical Rationale
* **How we achieved it:**
  - In `frontend/src/api/client.ts`, dynamically resolved `API_BASE` via `import.meta.env.VITE_API_BASE_URL || "/api"`, replacing hardcoded `http://localhost:8000`. Added `frontend/src/vite-env.d.ts` for Vite client declarations.
  - In `frontend/src/views/InsightsView.tsx`, removed `MOCK_REPORT_CARD` fallbacks so live API metrics and report cards are displayed accurately. Filtered out `ABSTAIN` actions from task report cards.
  - In `backend/src/probation/engine/report.py`, filtered `ABSTAIN` actions out of `tasks_list` so report cards reflect genuine task decisions.
  - In `backend/src/probation/engine/handsoff.py`, removed `".sh"`, `".py"`, `".pyw"` from `BLOCKED_EXTENSIONS` allowing benign code files.
  - In `backend/src/probation/packs/mail/exam_ops.py` and `clues.py`, bounded OTP pattern matching with word boundaries `r"\b(?:otp|pin)\b"` to eliminate false positives on common words (e.g. "prototype", "hotpot", "footpath").
  - Removed stray test/data artifacts in `backend/data` and default tiny_synth CLI output.
* **Alternatives considered:** None.
* **Why we chose this path:** Ensures reliable production frontend builds, crisp UX without synthetic mock contamination, and clean security boundaries without collateral false alarms.

## 3. Database Schema Impact
* **Changes made:** None.

## 4. Core Logic & Necessary Functions
* `API_BASE` (`frontend/src/api/client.ts`): Base path config leveraging Vite environment variables with fallback to relative `/api`.
* `TasksReport` (`frontend/src/views/InsightsView.tsx`): Filters out `ABSTAIN` tasks to surface actionable autonomous task classifications.
* `is_hands_off` (`backend/src/probation/engine/handsoff.py`): Checks attachment file safety without restricting safe scripting extensions.
* `validate_mail_operator_result` (`backend/src/probation/packs/mail/exam_ops.py`): Validates examination perturbations using word-bounded regexes.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_caps_and_handsoff.py`: Confirms safe scripts pass hands-off checks and OTP word boundaries prevent false triggers.
  - Frontend build: `npm run build` ran clean with zero TypeScript errors and produced production bundle.
* **Manually verified:** Ran end-to-end unit, integration, and property tests (182 tests total).

## 6. Dependencies & Deferred Work
* **Depends on:** FastAPI endpoints and Vite dashboard infrastructure.
* **Known issues/deferred:** None. All Phase 3 items (H10, P2) complete.
