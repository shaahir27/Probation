# Phase 9 Handoff: API Endpoints and Responsive Dashboard

**Branch / Commit:** `phase-9-api-dashboard`  
**Phase:** 9 — API and Dashboard  
**Lane:** Full Stack (Backend API + React Frontend)  

---

## Done

1. **Phase 9 Plan Alignment & Corrections (`docs/FRONTEND_IMPLEMENTATION_PLAN.md`)**:
   - Scope clarified: Phase 9 explicitly covers both `backend/src/probation/api/` and `frontend/`.
   - Process permissions & write boundaries: Documented that the API writes strictly to `user_responses` using `Role.API`. Reported the contract wording conflict between Section 9 and Section 3 process permissions without inventing unapproved writes.
   - Preview mode: Strictly restricted synthetic demo fixtures (Persona: Meena) to an explicit, visibly labeled Preview Mode toggle. Live API errors and empty states never silently substitute mock data.
   - Historical task scores: Enforced that task/action historical agreement scores are shown only when an approved API change provides that scope. Missing API capability is cleanly distinguished from insufficient history.
   - Board views: Added `GET /boards/{pack}` with fail-closed dormancy (`active: false`) for inactive packs (Radar / Reading). Kept Radar hidden until its pack is active. Mapped contract action status `DONE` to the user-friendly UI label "Completed".
   - Web facts transparency: Specified that `GET /web-facts` strictly reads recorded local Tavily queries and verified facts with zero outbound network calls.
   - Visual tokens: Aligned styling to Spruce & Brass (`#111B18` canvas, `#192723` surface, `#C8B27D` brass accent) and replaced machine-specific `file:///` URLs with repo-relative links.

2. **Backend API Endpoints (`backend/src/probation/api/`)**:
   - `queue.py`: `GET /api/queue` (queue items with digests, reasons, draft previews), `POST /api/queue/{proposal_id}/respond` (writes strictly to `user_responses` with `Role.API`).
   - `items.py`: `GET /api/items/{proposal_id}` (situation, proposal, clues, past cases, draft, class stats).
   - `actions.py`: `GET /api/actions` (executed, held, and undone items with remaining recall window), `POST /api/actions/{action_id}/undo` (records undo intent in `user_responses`).
   - `licences.py`: `GET /api/licences` (computes live derived licences and queries last 5 licence changes).
   - `report.py`: `GET /api/report-card?family=` (delegates to `engine.report.generate_report_card`).
   - `insights.py`: `GET /api/metrics/summary`, `GET /api/habits`, `POST /api/habits/{id}/deny`, `GET /api/chains`, `GET /api/exams`, `POST /api/exams/run`.
   - `boards.py`: `GET /api/boards/{pack}` (fail-closed pack boards for radar/reading).
   - `webfacts.py`: `GET /api/web-facts` (reads recorded Tavily calls and quarantined facts).
   - `replay.py`: `GET /api/replay/state`, `POST /api/replay/{start|pause|speed}`.
   - `app.py`: Uniform exception handler returning `{"error": {"code": str, "message": str}}`, `/health`, `/api/ledger/verify` (hash chain integrity), `/api/settings` (read-only safe tunables), `/api/exposure` (LLM token and cost breakdown).

3. **Responsive React Dashboard (`frontend/src/`)**:
   - Zero additional npm dependencies introduced.
   - Design system: Spruce & Brass dark mode semantic tokens configured in `tailwind.config.ts` and `index.css`.
   - Persistent 5-destination navigation: Desktop compact sidebar (`DesktopSidebar.tsx`) and mobile 5-icon bottom bar (`MobileNav.tsx`) with Home, Queue, Actions, Permissions, and More.
   - Views:
     * `HomeView.tsx`: "What needs me now?", pending review cards, licences needing attention, philosophy summary.
     * `QueueView.tsx`: Grouped task items, inline quick decisions ("Do it", "Not this", "Change action"), detail pane with explanations and draft preview.
     * `ActionsView.tsx`: Action audit timeline, status `DONE` rendered as "Completed", 1-click undo within the recall window.
     * `PermissionsView.tsx`: 4-step autonomy ladder (L0..L3) per task/action, safe lower bounds ($LB_{0.95}$), habit drift alerts.
     * `InsightsView.tsx`: Driving test summary, metrics & weekly trends, habit mining rules (with BH denial), chain patterns, diagnostic exams.
     * `MoreView.tsx`: Directory for Insights, Privacy & Exposure, Web Facts Transparency, Activity Record & Ledger Verify, Tunables, Replay Clock, and conditional Radar.
     * `RadarView.tsx`: Opportunity board, hidden / dormant when pack is inactive.
   - Explicit Preview Mode: Accessible via sidebar toggle, rendering a top alert banner when active, and never substituted for live API errors.

---

## Files Changed / Created

- `docs/FRONTEND_IMPLEMENTATION_PLAN.md` (updated: scope, process boundaries, contract conflict, preview mode rules, Spruce & Brass tokens, expanded tests)
- `backend/src/probation/api/app.py` (updated: full router registration, error formats, ledger verify, settings, exposure)
- `backend/src/probation/api/routes/__init__.py` (created)
- `backend/src/probation/api/routes/queue.py` (created)
- `backend/src/probation/api/routes/items.py` (created)
- `backend/src/probation/api/routes/actions.py` (created)
- `backend/src/probation/api/routes/licences.py` (created)
- `backend/src/probation/api/routes/report.py` (created)
- `backend/src/probation/api/routes/insights.py` (created)
- `backend/src/probation/api/routes/boards.py` (created)
- `backend/src/probation/api/routes/webfacts.py` (created)
- `backend/src/probation/api/routes/replay.py` (created)
- `backend/tests/api/test_api_endpoints.py` (created: 11 comprehensive endpoint, boundary, and error tests)
- `frontend/tailwind.config.ts` (updated: Spruce & Brass palette tokens)
- `frontend/src/index.css` (updated: tactile buttons and glass navigation)
- `frontend/src/api/types.ts` (created: complete TypeScript schemas)
- `frontend/src/api/fixtures.ts` (created: synthetic Meena demo data)
- `frontend/src/api/client.ts` (created: typed client with error handling and preview mode toggle)
- `frontend/src/components/common/Badge.tsx` (created)
- `frontend/src/components/common/Button.tsx` (created)
- `frontend/src/components/common/ErrorBanner.tsx` (created)
- `frontend/src/components/common/EmptyState.tsx` (created)
- `frontend/src/components/layout/DesktopSidebar.tsx` (created)
- `frontend/src/components/layout/MobileNav.tsx` (created)
- `frontend/src/components/layout/Header.tsx` (created)
- `frontend/src/views/HomeView.tsx` (created)
- `frontend/src/views/QueueView.tsx` (created)
- `frontend/src/views/ActionsView.tsx` (created)
- `frontend/src/views/PermissionsView.tsx` (created)
- `frontend/src/views/InsightsView.tsx` (created)
- `frontend/src/views/MoreView.tsx` (created)
- `frontend/src/views/RadarView.tsx` (created)
- `frontend/src/App.tsx` (updated: connected 5-destination layout, error boundaries, preview toggle)
- `build_history/phase_09_api_dashboard/feature_api_and_dashboard.md` (created)
- `build_history/index.md` (updated)

---

## Tests

1. **Automated Verification Gate (`.\make.cmd check`)**:
   - `ruff check`: All checks passed.
   - `ruff format --check`: 135 files checked, clean.
   - `mypy --strict`: Success, no issues in 101 source files.
   - `pytest backend/tests/`: 119 passed, 0 failures. Passes `T-API`, `T-LEDGER`, `T-GATE`, `T-LICENCE`, `T-EXEC`, `T-DRIFT`.

2. **Frontend Production Build (`npm run build` in `frontend/`)**:
   - `tsc`: Zero errors under strict typing, `noUnusedLocals`, `noUnusedParameters`.
   - `vite build`: Production bundle generated clean in 21.98s.

3. **Process Permission Write Boundary Tests**:
   - Verified that `RoleAccess(conn, Role.API)` strictly allows writes to `user_responses` and raises `AccessError` if attempting direct writes to `outcomes` or `ledger`.

4. **Zero-Outbound Web Facts Verification**:
   - Verified that `GET /api/web-facts` queries only local SQLite tables (`tavily_calls`, `web_facts`) and executes zero external network calls.

---

## Invariants Touched

- **Invariant I-1 (LLM Data Only)**: Untouched. LLMs hold no tools or credentials.
- **Invariant I-2 (Executor Write Exclusivity)**: Enforced. The API does not execute external mutations or write to `outcomes`.
- **Invariant I-3 (Fail Closed)**: Enforced. Dormant boards return `active: false`, unhandled errors return 500 JSON without data leaks.
- **Invariant I-4 (No Peeking)**: Preserved.
- **Invariant I-5 (Ledger Immutability)**: Verified. Ledger remains append-only and hash-chained (`GET /api/ledger/verify`).
- **Invariant I-9 (Monotonic Replay Clock)**: Preserved. Replay endpoints control `core.clock`.
- **Invariant I-11 (Redaction Prior to Model Dispatch)**: Verified. Exposure endpoint reports redacted exposure metrics.
- **Invariant I-14 (Network Quarantine)**: Verified. Opening web-facts page initiates zero external HTTP calls.

---

## Deviations and Assumptions

- **Contract Change Control**: Did not modify `docs/CONTRACT.md`. All contract requirements respected.
- **Synthetic Preview Mode**: Provided Persona Meena synthetic preview fixtures strictly behind an explicit toggle, keeping live mode pristine.

---

## Contract Change Requests

- **CCR-001 (Queue Response Write Permissions)**:
  - *Conflict*: `CONTRACT.md` Section 9 states: "POST /queue/{proposal_id}/respond: Body: `{response: "accept"|"reject"|"edit", edited_action: ...}`. The API writes to `user_responses` and marks the proposal's outcome in `outcomes`." However, `CONTRACT.md` Section 3 process permissions strictly forbid `Role.API` from writing to `outcomes` or `ledger` (only `Role.EXECUTOR` and `Role.BACKTEST` may write to `outcomes`).
  - *Resolution implemented*: The API strictly honors Section 3 permissions and writes exclusively to `user_responses`. Outcome generation is deferred to the executor worker.
  - *Request*: Formalize in `CONTRACT.md` Section 9 that the API writes to `user_responses`, while outcome marking is processed asynchronously by the Executor.

- **CCR-002 (Task-Level Historical Scores API Scope)**:
  - *Observation*: `GET /report-card?family=` is family-scoped. `CONTRACT.md` Section 9 does not define a `(class_key, action)` endpoint for backtest accuracy.
  - *Resolution implemented*: Surfaced family summary honestly without inferring or fabricating per-task scores.
  - *Request*: Add `GET /report-card/task?class_key=&action=` to `CONTRACT.md` Section 9 in a future revision.

---

## New Dependencies

None. Built entirely using existing dependencies (`fastapi`, `sqlite3`, `react`, `lucide-react`, `tailwindcss`).

---

## LLM Cost Incurred

$0.00 (Zero external LLM API calls made during Phase 9 API and frontend build).

---

## Suggested Next Step

Proceed to Phase 10: Evaluation (`docs/EVALUATION_PLAN.md`), running baseline B3, ablations, and the full evaluation suite across synthetic personas.
