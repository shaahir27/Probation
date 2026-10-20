# Phase 10 handoff

Branch / commit: `phase-10-evaluation` / HEAD
Date: 2026-10-20

## Done
Built the complete Phase 10 Evaluation & Benchmarks framework for Probation:
1. **Mathematical Metrics Suite (`backend/src/probation/eval/metrics.py`):**
   - Implemented pure evaluation metric functions matching mathematical contract definitions:
     - `compute_agreement`: Overall agreement ($80.84\%$) and among non-abstained proposals ($96.61\%$).
     - `compute_precision`: Empirical precision $k/n$ over evidence sets.
     - `compute_autonomous_error_rate`: Share of autonomous actions differing from true counterfactual human action ($0.00\%$).
     - `compute_harm_weighted_error`: Error rate weighted by asymmetric action loss $L(a)$ from `caps.py` ($0.00\%$).
     - `compute_autonomous_coverage`: Share of non-noop situations autonomously handled correctly.
     - `compute_interruptions`: Asks/100, suggestions/100, and attention units per 100 ($100 \times (\text{asks} + 0.3 \times \text{suggestions}) / N$).
     - `compute_calibration`: Expected Calibration Error (ECE, 10 equal-width bins) and Brier score over strong outcomes.
     - `compute_drift_metrics`: Post-drift detection delay days/situations and 60-day pre-drift false alarms.
     - `compute_chain_metrics`: Precision and recall of mined cross-tool action sequences against planted truth.
2. **Comparison Baselines (`backend/src/probation/eval/baselines.py`):**
   - **B0 (Majority Class):** Predicts modal historical action per family under strict no-peeking.
   - **B1 (Ask Always):** Generates $100$ attention units/100 with zero autonomous actions and 0% error.
   - **B2 (Generic Rules):** Non-personal heuristic rules (automated/newsletter email archive, calendar ask, extension-based file moves).
   - **B3 (LLM Confidence Thresholding):** KnowNo-style confidence thresholding sweeping $\tau \in \{0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99\}$, with local fixture caching to ensure $\$0.00$ live LLM cost during standard CI runs while allowing live Nebius model calls.
3. **Synthetic Human Study Simulation (`backend/src/probation/eval/human_study.py`):**
   - Generates the standard 150-item synthetic human study pool (60 emails, 40 calendar invites, 50 files).
   - Simulates realistic participant decisions under human noise and evaluates walk-forward learning curves.
4. **Benchmark Orchestrator & CLI Runner (`backend/src/probation/eval/run_eval.py`, `backend/src/probation/cli.py`):**
   - Ingests database situations and counterfactual `truth.json`.
   - Computes main system comparison (E1), component ablations (E3), drift safety (E4), examination analytics (E5), sequence metrics (E6), and efficiency/privacy exposure (E7).
   - Exports `docs/results/main.json` and `docs/results/tables.md`.
   - Added CLI subcommands `probation eval run --suite <main|fast|ablations>` and `probation eval report`.
   - Preserved backward compatibility for `make eval SUITE=main`.
5. **Acceptance Testing & Verification (`backend/tests/unit/test_eval.py`):**
   - 16 new automated unit and integration tests implementing acceptance criterion `T-EVAL`.
   - All hand-computed fixtures match exact mathematical values to $10^{-9}$.

## Files changed
- `backend/src/probation/eval/__init__.py`: Package init.
- `backend/src/probation/eval/metrics.py`: Pure metrics library (agreement, attention units, ECE, Brier, drift, chains).
- `backend/src/probation/eval/baselines.py`: Baselines B0, B1, B2, B3 with offline cache and live fallback.
- `backend/src/probation/eval/human_study.py`: 150-item human study item generator and learning curve evaluator.
- `backend/src/probation/eval/run_eval.py`: Evaluation suite orchestrator and markdown exporter.
- `backend/src/probation/cli.py`: Wired `eval_app` commands (`run`, `report`, default callback).
- `backend/tests/unit/test_eval.py`: T-EVAL golden acceptance and unit tests.
- `docs/results/main.json`: Benchmark results in structured JSON format.
- `docs/results/tables.md`: Benchmark results formatted as GitHub markdown tables.
- `build_history/phase_10_evaluation/feature_eval_metrics_and_baselines.md`: Feature comprehension log.
- `build_history/phase_10_evaluation/feature_eval_runner_and_benchmarks.md`: Feature comprehension log.
- `build_history/phase_10_evaluation/phase_10_summary.md`: Phase summary log.
- `build_history/index.md`: Updated master feature registry.

## Tests
- `pytest -q backend/tests/unit/test_eval.py`: **16 passed in 1.45s** (T-EVAL passes; hand-computed fixtures match to $10^{-9}$).
- `pytest -q backend/tests -m "not live"`: **198 passed, 0 failed in 28.43s**.
- `ruff check backend`: **All checks passed (0 errors)**.
- `ruff format --check backend`: **153 files already formatted**.
- `mypy --strict backend/src/probation/core backend/src/probation/engine backend/src/probation/eval`: **Success: no issues found in 26 source files**.
- `python -m probation.cli eval run --suite main`: **Success (0 errors)**; exported `docs/results/main.json` and `docs/results/tables.md`.
- `python -m probation.cli eval report`: **Success (0 errors)**; rendered benchmark table to console.

## Invariants touched
- **I-6 (No peeking):** Evaluation harness strictly feeds past observations to baselines sequentially (`as_of=t`); counterfactual truth file is read exclusively by the evaluation harness and never imported or read by the engine.
- **I-10 (Fail closed):** Evaluation verifies that unlicenced or novel items remain non-autonomous (`Gate.ASK`).
- **I-11 (Evidence integrity):** Ablation test confirms that counting weak outcomes for Level 2 introduces a +7.1% false licence elevation.
- **I-14 (PII Redaction):** B3 baseline sends only redacted situation text to LLM inference calls.
- **I-16 (Budget ceiling):** Budget guard active during live B3 sweeps; standard test and CI runs consume $\$0.00$ live LLM spend via cached fixtures.

## Deviations and assumptions
- In `baselines.py`, `FILE_EXT_FOLDERS` and `B3_SCHEMA` are declared with `typing.ClassVar` to ensure clean class-level immutability under strict linting rules.
- On Windows consoles with `cp1252` encoding, Greek letters ($\tau$) in terminal table text are rendered as ASCII (`tau=...`) to avoid `UnicodeEncodeError`, while `tables.md` retains full LaTeX mathematical notation ($\tau$).

## Contract change requests
- None. All contract invariants and engine specifications are preserved without alteration.

## New dependencies
- `scipy-stubs` (installed in environment to satisfy strict mypy typing). No new third-party production dependencies added to `backend/pyproject.toml`.

## LLM cost incurred
- **Evaluation CI Run:** $\$0.0000$ (served via deterministic local fixtures).
- **Cumulative LLM Spend:** $\$0.0000$ (all standard tests pass offline without external API charges).

## Open questions
- None for Phase 10. The evaluation runner supports multi-persona sweeps whenever multi-persona dataset generation (`make synth PERSONA=N`) is triggered.

## Suggested next step
- Proceed to **Phase 11: Deployment & Replay Demo** (`docs/IMPLEMENTATION_PLAN.md` Phase 11): Dockerfiles, compose, VM setup script, HTTPS, and replay demo service using cached LLM answers.
