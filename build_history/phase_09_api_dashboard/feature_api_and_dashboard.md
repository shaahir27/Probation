---
feature: "API Endpoints and Responsive Dashboard"
phase: "Phase 9 — API and Dashboard"
status: "Built"
---

# Feature: API Endpoints and Responsive Dashboard

## 1. Overview
* **Name:** API Endpoints and Responsive Dashboard
* **Phase:** Phase 9 — API and Dashboard
* **Purpose:** Expose every CONTRACT.md Section 9 HTTP endpoint with strict process boundary isolation and fail-closed error formats, paired with a responsive 5-destination React dashboard using the Spruce & Brass design system.
* **Traces to:** `CONTRACT.md` Section 9, `USER_FLOW.md`, `docs/FRONTEND_IMPLEMENTATION_PLAN.md`.

## 2. Technical Rationale
* **How we achieved it:**
  - Built backend routes in `backend/src/probation/api/routes/` covering:
    * `/api/queue` and `/api/queue/{id}/respond` (writes strictly to `user_responses` with `Role.API`)
    * `/api/items/{id}` (full proposal context, clues, past cases, draft)
    * `/api/actions` and `/api/actions/{id}/undo` (status `DONE` mapped to UI "Completed", writes undo response)
    * `/api/licences` (derived licences and change history)
    * `/api/report-card` (family-scoped evaluation metrics)
    * `/api/metrics/summary`, `/api/habits`, `/api/habits/{id}/deny`, `/api/chains`, `/api/exams`, `/api/exams/run`
    * `/api/boards/{pack}` (radar/reading boards with fail-closed dormancy)
    * `/api/web-facts` (read-only recorded Tavily activity, zero outbound requests)
    * `/api/replay/state`, `/api/replay/{start|pause|speed}`
    * `/api/ledger/verify`, `/api/settings`, `/api/exposure`
  - Frontend built in `frontend/` using Vite, React 18, Tailwind CSS, Lucide icons:
    * 5 top destinations: Home, Queue, Actions, Permissions, More (Insights, Privacy, Web Facts, Ledger, Settings, Replay, Radar).
    * Strictly explicit, visibly labeled Preview Mode toggle for synthetic demo fixtures (Persona: Meena); never silently substituted on live API errors.
    * No extra npm dependencies added.
* **Alternatives considered:** None; strictly bounded by `CONTRACT.md` Section 9 and `FRONTEND_IMPLEMENTATION_PLAN.md`.
* **Why we chose this path:** Preserves architectural purity, strict process permissions (`Role.API`), and fail-closed security.

## 3. Database Schema Impact
* **Changes made:** None. The API utilizes the existing schema defined in `probation.db.schema` and respects SQLite table permissions through `RoleAccess`.

## 4. Core Logic & Necessary Functions
* Key functions & files:
  - `backend/src/probation/api/app.py`: FastAPI application setup, global error handler formatting `{"error": {"code": str, "message": str}}`, router mounting, `/health`, `/api/ledger/verify`, `/api/settings`, `/api/exposure`.
  - `backend/src/probation/api/routes/queue.py`: `get_queue_items()`, `respond_to_proposal()`.
  - `backend/src/probation/api/routes/items.py`: `get_item_detail()`.
  - `backend/src/probation/api/routes/actions.py`: `get_actions()`, `request_action_undo()`.
  - `backend/src/probation/api/routes/licences.py`: `get_licences()`.
  - `backend/src/probation/api/routes/report.py`: `get_report_card()`.
  - `backend/src/probation/api/routes/insights.py`: `get_metrics_summary()`, `get_habits()`, `deny_habit()`, `get_chains()`, `get_exams()`, `trigger_exam_run()`.
  - `backend/src/probation/api/routes/boards.py`: `get_pack_board()`.
  - `backend/src/probation/api/routes/webfacts.py`: `get_web_facts()`.
  - `backend/src/probation/api/routes/replay.py`: `get_replay_state()`, `start_replay()`, `pause_replay()`, `set_replay_speed()`.
  - `frontend/src/App.tsx`: Root dashboard coordinator, persistent layout, preview mode switch, error handling.
  - `frontend/src/api/client.ts`: Typed fetch client with uniform error parsing and explicit preview mode support.
  - `frontend/src/views/`: `HomeView.tsx`, `QueueView.tsx`, `ActionsView.tsx`, `PermissionsView.tsx`, `InsightsView.tsx`, `MoreView.tsx`, `RadarView.tsx`.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/api/test_api_endpoints.py` (11 endpoint, boundary, and error formatting tests)
  - `backend/tests/` (all 119 backend integration, property, and unit tests passing)
  - Frontend build: `npm run build` compiled clean with zero TypeScript errors.
  - Verification suite: `.\make.cmd check` green (Ruff check, Ruff format, Mypy strict, Pytest 119 passed).
* **Manually verified:**
  - Explicit preview mode banner visibility and toggle.
  - Action status `DONE` mapped to "Completed".
  - Radar board hidden/dormant when pack is not active.
  - Web facts page triggers zero external HTTP calls.

## 6. Dependencies & Deferred Work
* **Depends on:** `probation.db`, `probation.engine`, `probation.config`.
* **Known issues/deferred:**
  - Wording conflict in CONTRACT.md between Section 9 ("The API writes to `user_responses` and marks the proposal's outcome") and Section 3 process permissions (`Role.API` forbidden from writing to `outcomes`/`ledger`). The API strictly adheres to Section 3 process permissions and delegates outcome resolution to the Executor worker.
  - Per-task report card scores are currently unavailable at the API layer (the report-card API is family-scoped). Missing API support is surfaced cleanly without fabricating numbers.
