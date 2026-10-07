# AGENTS.md

Standing rules for every coding agent working in this repo. Keep this file short; details live in `docs/`.

## Project
**Probation** is a personal AI that earns permission to act, one task type at a time, by proving on the user's own history that it would have done what they did. Python backend (FastAPI, SQLite), React dashboard. AI models are NVIDIA Nemotron, hosted on Nebius Token Factory.

## Read first
1. `docs/CONTRACT.md` is the highest authority. Never edit it. If a rule must change, write a "Contract change request" in your report and stop.
2. Then the specs for your phase: `docs/ENGINE_SPEC.md`, `docs/DATA_MODEL.md`, `docs/PACKS_SPEC.md`, `docs/PROMPTS.md`.
3. Plan and tests: `docs/IMPLEMENTATION_PLAN.md`, `docs/TEST_PLAN.md`. For any user-interface work also read `docs/USER_FLOW.md`. For anything touching Tavily, `web/`, `links/`, `radar` or `reading`, read `docs/TAVILY_AND_NEW_PACKS.md`.
4. Conflicts: CONTRACT > specs > plans > `docs/SYSTEM_DESIGN.md`.

## Non-negotiable rules (summary of the contract)
- LLM output is data only. LLMs hold no credentials or tools; every output is schema-validated.
- Only the Executor performs side-effects and holds write credentials.
- Fail closed: any failure means ask or watch, never act.
- No peeking: use `HistoryView(as_of=t)` only. Never read future data.
- The ledger is append-only and hash-chained. Never UPDATE or DELETE it.
- Never call the system clock directly; use `core/clock.py`.
- Caps and hands-off lists are hard-coded; licences are derived from evidence, not stored as truth.
- The examiner is not an LLM. Verdicts are computed by code.
- Redact before any text goes to an LLM. Respect the budget guard.
- Synthetic data only. Never read, print, log or commit `.env` or any secret.
- No network calls outside `llm/client.py`, `web/client.py` (Tavily), pack connectors and `workers/executor.py`.
- Web facts may only restrict or inform, never raise autonomy; policy, evidence and licence code must not import `web/`. Raw web text is untrusted: only a quarantined extractor reads it, and the writer never sees it. Never fetch URLs from mail bodies. Tavily queries are built by code from public-entity strings only.

## How to work
- One phase at a time, from `docs/IMPLEMENTATION_PLAN.md`. Use Planning mode: write a plan and task list, wait for approval, then implement.
- Write tests first for the ledger, no-peeking, licence maths and the gate.
- Run `make check` before every commit. Never weaken, skip or delete a test to pass.
- Document every feature built or updated in local `build_history/` following `docs/BUILD_LOGGING_PROTOCOL.md` using `docs/templates/log_schema.md`. Update `build_history/index.md`.
- Commit as `phase-N: short description`, on a branch `phase-N-name`.
- End each phase with a handoff report at `docs/reports/phase-N.md` (template in `docs/AGENT_PLAYBOOK.md` section 6). Do not start the next phase.
- Point to docs by path; do not paste them into prompts.

## Stop and ask when
- Two documents disagree, or a contract rule seems wrong.
- A change needs a new network destination, credential, dependency, or file-system write outside the allowed set.
- A test cannot pass without weakening it.
- Anything involves real personal data or a secret.

## Code style
- Python 3.11 or newer; type hints everywhere; `mypy --strict` on `core/` and `engine/`; `ruff` for lint and format.
- Pure functions for engine logic; I/O at the edges. Seeded randomness only.
- Typed exceptions (`BudgetExceeded`, `LLMValidationError`, `LedgerCorrupt`) handled by failing closed.
- Structured logs; never log message bodies or secrets. Files under about 400 lines.

## Commands
`make setup` · `make check` · `make test` · `make synth PERSONA=1 SEED=1` · `make backtest FAMILY=email_action` · `make serve` · `make web` · `make eval SUITE=main` · `make ledger-verify` · `make budget`
