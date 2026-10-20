# Phase 8 Handoff: Chains and Habits

**Branch:** `phase-8-chains-habits`  
**Date:** 2026-10-20  
**Phase:** 8 — Chains and Habits  

---

## Done
In this phase, we completed the core implementations for **Habit Mining** and the **Chains Pack**, fulfilling all requirements from `docs/ENGINE_SPEC.md` §13 & §14, `docs/PACKS_SPEC.md` §4, `docs/PROMPTS.md` §7, and `docs/TEST_PLAN.md` (`T-HABIT`, `T-CHAIN`):

1. **Benjamini-Hochberg Habit Mining Engine (`backend/src/probation/engine/habits.py`):**
   - Implemented one-vs-rest Fisher's exact test (`scipy.stats.fisher_exact(alternative="greater")`) on clue vs observed action tables with quartile binning for numeric features.
   - Applied Benjamini-Hochberg false discovery rate control (`scipy.stats.false_discovery_control`) enforcing $q < 0.01$, support $n \ge 20$, and lift $\ge 1.5$.
   - Built deterministic template statements and integrated fallback LLM humanization (`wording.v1`).
   - Implemented code-side number-preserving wording validator (`validate_wording_sentence`) enforcing multiset equality of all numeric tokens and length bounds (20–160 chars).
   - Preserved user denial states (`status = 'denied'`), excluding denied habits from explanations without altering statistical scoring models.

2. **Cross-Tool Action Chains Pack (`backend/src/probation/packs/chains/`):**
   - **Sequence Mining (`mining.py`):** Discovers cross-tool follow-up actions within 24-hour observation windows `(t, t + 24h]` across `REPLY`, `BLOCK_TIME`, and `CREATE_TASK` with dual linking: explicit thread link (STRONG) and token cosine similarity $\ge 0.45$ (WEAK). Base rates are computed over all active days of raw item history ($n \ge 20$, $k/n \ge 0.60$, $\text{lift} \ge 1.5$).
   - **Independent Gated Proposer (`proposer.py`):** Creates distinct situations with `pack='chains'`, `family='chain_followup'`, and `variant={follow_action}`, emitting immutable proposals under class key `chain|{trigger_class_key}|{follow_action}` with independent audit holdout draws and deterministic gate decisions.
   - **Side-Effect Execution & Reversal (`executor.py`):** Implemented execution and undo against `SimWorld` for `BLOCK_TIME` (private calendar event creation/deletion), `CREATE_TASK` (task creation/deletion), and `REPLY` (draft creation).
   - **Pack Adapter & Outcome Resolver (`__init__.py`):** Registered `chains_pack` in pack registry. Unanswered situations at window expiry automatically resolve to `observed_action="NONE"` (WEAK evidence).
   - **Evidence Level Bounding:** Ensured weak similarity links contribute only to `n_all`, capping derived autonomy strictly at Level 1 (`SUGGEST`). Level 2/3 autonomy requires explicit human feedback or strong thread links.

3. **Replay, Scheduler, and CLI Integration:**
   - Wired habit and chain mining into weekly/retrain ticks and trigger situation follow-up proposal dispatch in `replay.py`.
   - Wired habit and chain mining into `scheduler.py` (`run_nightly_review`).
   - Added CLI subcommands: `probation habits mine [--as-of ISO]` and `probation chains mine [--as-of ISO]`.

4. **Testing & Quality Assurance:**
   - Implemented comprehensive unit test suite in `backend/tests/unit/test_chains_habits.py` covering all `T-HABIT` and `T-CHAIN` criteria.
   - All 9 unit tests in `test_chains_habits.py` passed.
   - Full test suite (154 tests) passed with 0 failures.
   - Mypy `--strict` and Ruff lint/format passed cleanly.
   - Frontend `npm run build` completed cleanly in 11.0s.

---

## Files changed
- `backend/src/probation/config.py`: Added tunables `model_wording`, `habit_min_support`, `habit_min_lift`, `habit_q`, `chain_min_support`, `chain_min_p`, `chain_min_lift`, `chain_link_min_sim`, `chain_window_hours`.
- `backend/src/probation/core/types.py`: Added `Habit` and `Chain` domain models matching SQLite schema.
- `backend/src/probation/engine/habits.py`: Habit mining engine, Fisher exact test, Benjamini-Hochberg FDR, and wording validator.
- `backend/src/probation/engine/replay.py`: Wired habit/chain mining in retrain ticks and follow-up situation proposal creation in situation loop.
- `backend/src/probation/packs/chains/__init__.py`: Chains pack adapter and outcome resolver.
- `backend/src/probation/packs/chains/mining.py`: Action chain sequence mining and token cosine similarity.
- `backend/src/probation/packs/chains/proposer.py`: Chain follow-up situation and proposal generation.
- `backend/src/probation/packs/chains/executor.py`: Side-effect execution and undo for `BLOCK_TIME`, `CREATE_TASK`, and `REPLY`.
- `backend/src/probation/packs/registry.py`: Registered `chains_pack` in active registry.
- `backend/src/probation/workers/scheduler.py`: Added habit and chain mining to nightly review.
- `backend/src/probation/cli.py`: Added `probation habits mine` and `probation chains mine` CLI subcommands.
- `backend/tests/unit/test_chains_habits.py`: Unit test suite covering `T-HABIT` and `T-CHAIN`.
- `build_history/phase_08_chains_habits/feature_habit_mining_and_wording.md`: Technical log for habit mining.
- `build_history/phase_08_chains_habits/feature_chains_mining_and_execution.md`: Technical log for chains mining and execution.
- `build_history/phase_08_chains_habits/phase_08_summary.md`: Summary log for Phase 8.
- `build_history/index.md`: Updated master feature registry.

---

## Tests
- **Unit & Contract Suite:**
  ```bash
  pytest -v backend/tests/unit/test_chains_habits.py
  # 9 passed in 2.68s
  ```
- **Full Backend Suite:**
  ```bash
  pytest -q backend/tests -m "not live"
  # 154 passed, 2 warnings in 50.69s
  ```
- **Type Checking:**
  ```bash
  python -m mypy --config-file backend/pyproject.toml backend/src/probation/core backend/src/probation/engine backend/src/probation/packs/chains
  # Success: no issues found in 25 source files
  ```
- **Lint & Format:**
  ```bash
  python -m ruff check backend/src backend/tests
  python -m ruff format --check backend/src backend/tests
  # All checks passed!
  ```
- **Frontend Build:**
  ```bash
  npm run build (in frontend/)
  # built in 11.03s, 0 errors
  ```
- **T- Test IDs Passing:**
  - `T-HABIT`: Planted pattern found; random noise yields 0 habits after BH FDR correction; wording validator rejects changed numbers and accepts identical numbers; denied habits excluded from active explanations.
  - `T-CHAIN`: Planted pattern discovered within 24h window ($n=25, k=20$, lift $\ge 1.5$); distinct variant situations created; weak evidence bounds autonomy to Level 1 (`SUGGEST`); unanswered situations yield `NONE` (WEAK); side-effect execution and undo for `BLOCK_TIME` and `CREATE_TASK` in `SimWorld`.
  - All previously passing test suites (`T-ID`, `T-CLOCK`, `T-LEDGER`, `T-REDACT`, `T-LLM`, `T-SEC`, `T-SYNTH`, `T-PACK`, `T-RESOLVE`, `T-NOPEEK`, `T-POLICY`, `T-NOVELTY`, `T-LB`, `T-CAPS`, `T-GATE`, `T-DRIFT`, `T-EXEC`, `T-TAVILY`, `T-FACTS`, `T-EXAM`, `T-API`) continue to pass with 0 regressions.

---

## Invariants touched
- **I-2 (Side-effects by Executor only):** Chain side-effects (`BLOCK_TIME`, `CREATE_TASK`, `REPLY`) are strictly dispatched and executed through `Executor` / `execute_chain_action`.
- **I-6 (No peeking):** Chain sequence mining only analyzes data up to `as_of` timestamp.
- **I-7 (Ledger integrity):** Every chain follow-up proposal is recorded on the hash-chained append-only ledger.
- **I-10 (Derived licences):** Chain licences are derived dynamically from evidence; weak similarity links only support Level 1 (`SUGGEST`).
- **I-16 (LLM output is data only / Code-only verdicts):** Habit mining associations are computed purely by code via Fisher's exact test and Benjamini-Hochberg FDR correction. Wording is strictly validated by number-multiset code validation. Mined habits never enter policy scoring models or grant permissions.
- **I-20 (Recallability required for Level 3):** `BLOCK_TIME` and `CREATE_TASK` have verified undo mechanisms in `SimWorld`.

---

## Deviations and assumptions
- None. Implementation strictly adheres to specifications in `docs/ENGINE_SPEC.md`, `docs/PACKS_SPEC.md`, and `docs/PROMPTS.md`.

---

## Contract change requests
- None.

---

## New dependencies
- None. Used existing `scipy.stats` (already in `pyproject.toml`).

---

## LLM cost incurred
- $0.00 in automated test runs (offline/fixtures mode with deterministic template formatting).

---

## Open questions
- None.

---

## Suggested next step
- Member 1 has completed Phase 8. Per `docs/MEMBER_SPLIT.md`, Member 1's next phase is **Phase 8b: Link substrate, Opportunity Radar, Reading Triage** (or human review by user).
