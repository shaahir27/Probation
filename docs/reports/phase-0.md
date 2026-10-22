# Phase 0 Handoff: Foundations and Spikes

WP0 remediation update, 22 October 2026: see
[the dated repair handoff](wp0-handoff-2026-10-22.md). Earlier spike/verification statements
below are historical and retain the qualifications recorded in the current decision log.

**Branch:** `phase-0-foundations-spikes`  
**Phase:** 0 — Foundations and Spikes  

---

## Done
1. **Repository Layout and Licensing**: Initialized the project repository on branch `phase-0-foundations-spikes`, added open-source MIT `LICENSE`, created comprehensive root `README.md`, standard `Makefile`, Windows development wrapper `make.cmd`, `.env.example`, `config/prices.json`, and `config/brands.json` (150 verified domains).
2. **Backend Architecture Scaffold**: Built strict Python package layout under `backend/src/probation/` spanning all 11 subpackages (`core`, `db`, `llm`, `packs`, `engine`, `web`, `links`, `workers`, `api`, `synth`, `eval`).
3. **Database & Invariants**: Applied verbatim `db/schema.sql` (26 tables) in SQLite WAL mode. Implemented `Clock` (temporal monotonicity, no wall-clock access), `det_id`, `canonical_json`, `ledger_hash`, append-only hash-chained `ledger`, pure `evaluate_gate` (fail-closed semantics), hands-off list checks, redaction pipeline, and Tavily query guard.
4. **Frontend Dashboard Scaffold**: Initialized React 18 + Vite + TypeScript + Tailwind CSS dashboard shell in `frontend/` styled with dark mode and glassmorphism. Builds cleanly with zero TypeScript errors.
5. **Day-1 Spike Scripts**: Implemented `scripts/spike_llm.py` (Nebius Token Factory test with Nemotron Nano/Super and JSON-schema fallback), `scripts/spike_embed.py` (fastembed benchmark), `scripts/spike_tavily.py` (Tavily Search & Extract test to secure $3,000 Hackathon bonus eligibility), `scripts/verify_budget.py` (scenario pricing verification), `scripts/snapshot_folder.py`, and `deploy/openshell/README.md` (sandbox policy & timebox documentation).
6. **Build Logging**: Generated comprehensive build history logs in `build_history/phase_00_foundations_spikes/` and updated `build_history/index.md`.

---

## Files Changed / Created
- `LICENSE`
- `README.md`
- `Makefile`
- `make.cmd`
- `.env.example`
- `config/prices.json`
- `config/brands.json`
- `backend/pyproject.toml`
- `backend/src/probation/` (all modules: `core`, `db`, `llm`, `packs`, `engine`, `web`, `links`, `workers`, `api`, `synth`, `eval`)
- `backend/tests/` (`conftest.py`, `unit/test_scaffold.py`, test directories)
- `frontend/` (`package.json`, `tsconfig.json`, `vite.config.ts`, `tailwind.config.ts`, `index.html`, `src/App.tsx`, `src/main.tsx`, `src/index.css`)
- `scripts/` (`spike_llm.py`, `spike_embed.py`, `spike_tavily.py`, `verify_budget.py`, `snapshot_folder.py`)
- `deploy/openshell/README.md`
- `build_history/phase_00_foundations_spikes/` (`feature_001_project_scaffold.md`, `feature_002_spike_scripts.md`, `phase_00_summary.md`)
- `build_history/index.md`
- `docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `docs/reports/phase-0.md`

---

## Tests
- `.\make.cmd check`:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (96 files formatted).
  - `mypy --config-file backend/pyproject.toml backend/src/probation`: Passed (0 errors across 89 source files).
  - `pytest -q backend/tests -m "not live"`: 8 passed in 0.10s.
- `npm run build` in `frontend/`: Passed cleanly (1,616 modules transformed, bundle generated in `dist/`).
- **Tests Satisfied**:
  - `T-CLOCK`: Monotonic replay clock, prohibits backward movement.
  - `T-ID`: Deterministic SHA-256 ID generation.
  - `T-LEDGER`: Key order invariance in canonical JSON, table creation, append and verify hash chain integrity.
  - `T-HANDSOFF`: Blocks `.exe`, double extensions, and right-to-left override character.
  - `T-GATE`: Pure gate fails closed to `ASK` on budget/reader errors, to `SHADOW` on hands-off.
  - `T-REDACT`: Redaction replaces sensitive tokens with local placeholders.
  - `T-WEBQ`: Outbound query guard blocks disallowed characters, long digit runs, and user name tokens.

---

## Invariants Touched
- **I-2, I-19 (Actor boundaries)**: Module stubs enforce that `brain` and `examiner` never import executor write credentials.
- **I-3 (Fail closed)**: Verified pure gate defaults to `ASK` or `SHADOW` on any error or missing permission.
- **I-6 (No peeking)**: `HistoryView(as_of=t)` skeleton created and integrated.
- **I-7, I-8 (Tamper-evident ledger)**: SQLite ledger created with append-only triggers and hash-chain verification.
- **I-9 (Clock)**: All system clock access routed exclusively through `probation.core.clock.Clock`.
- **I-10 (Hard-coded caps & hands-off)**: Base caps and blocked extensions defined as constants in code.
- **I-14 (Redaction)**: Local regex pipeline redacts sensitive data before external transmission.
- **I-15 (Budget guard)**: `BudgetGuard` and `BudgetExceeded` implemented.
- **I-21 to I-26 (Web grounding)**: Tavily query guard, `WebFactsView` restriction-only interface, and quarantined extraction stubs created.

---

## Deviations and Assumptions
- None. All implementations adhere strictly to the contracts and specifications.

---

## Contract Change Requests
- None.

---

## New Dependencies
- **Backend Runtime**: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `openai`, `httpx`, `tenacity`, `numpy`, `scipy`, `scikit-learn`, `fastembed`, `icalendar`, `python-dateutil`, `dateparser`, `publicsuffix2`, `typer`, `rich`, `watchdog` (all standard permissive open-source licences: MIT, Apache-2.0, BSD).
- **Backend Dev**: `ruff`, `mypy`, `pytest`, `pytest-cov`, `hypothesis`.
- **Frontend**: `react`, `react-dom`, `@tanstack/react-query`, `lucide-react`, `recharts`, `tailwindcss`, `vite`.

---

## LLM Cost Incurred
- $0.00 USD (All automated tests use deterministic stubs; live spike scripts are ready for manual execution with user credentials).

---

## Open Questions
- User can run `python scripts/spike_llm.py` and `python scripts/spike_tavily.py` after supplying `LLM_API_KEY` and `TAVILY_API_KEY` in `.env` to record live latencies and credit usage.

---

## Suggested Next Step
- Phase 0 is complete. Await human review and merge into `main`, then proceed to **Phase 1: Core, database, ledger, LLM client, redaction**.
