---
feature: "Phase 10 Evaluation & Benchmarks Summary"
phase: "Phase 10 — Evaluation & Benchmarks"
status: "Built"
---

# Phase 10 Summary: Evaluation & Benchmarks

## 1. Overview
Phase 10 delivers the complete empirical benchmark suite for the Probation system. It implements all metrics, comparison baselines B0–B3, component ablations E3, drift safety analysis E4, examination board analytics E5, cross-tool sequence metrics E6, and resource/privacy exposure metrics E7.

## 2. Completed Deliverables
1. **Core Metrics Package (`backend/src/probation/eval/metrics.py`):**
   - Pure functions for agreement, precision, autonomous error rate, harm-weighted loss, autonomous coverage, attention units ($100 \times (\text{asks} + 0.3 \times \text{suggestions}) / N$), calibration (ECE & Brier), drift metrics, and chain metrics.
   - Verified against hand-computed fixtures matching to $10^{-9}$ (acceptance test `T-EVAL`).
2. **Comparison Baselines (`backend/src/probation/eval/baselines.py`):**
   - B0: Majority class predictor (sanity check).
   - B1: Ask Always (100 attention units/100, 0% autonomous error).
   - B2: Generic static heuristics.
   - B3: KnowNo-style LLM-confidence thresholding sweeping $\tau \in \{0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99\}$ with offline caching for $\$0.00$ CI spend.
3. **Synthetic Human Study Harness (`backend/src/probation/eval/human_study.py`):**
   - Balanced 150-item pool (60 emails, 40 calendar invites, 50 files).
   - Simulation of human decision-making with configurable noise and walk-forward learning curve evaluation.
4. **Benchmark Orchestrator (`backend/src/probation/eval/run_eval.py`):**
   - Evaluates Probation and baselines on historical data and counterfactual truth.
   - Produces `docs/results/main.json` and `docs/results/tables.md`.
5. **Typer CLI Integration (`backend/src/probation/cli.py`):**
   - `probation eval run --suite <main|fast|ablations> [--db ...] [--truth ...] [--out ...]`
   - `probation eval report [--results ...]`
   - Backward-compatible callback for `make eval SUITE=main`.
6. **Acceptance Tests (`backend/tests/unit/test_eval.py`):**
   - 16 comprehensive unit and integration tests passing in $1.45$s.
   - 198 total passing tests in `backend/tests/`.

## 3. Benchmark Highlights (`docs/results/tables.md`)
- **Probation Agreement:** $80.84\%$ overall, $96.61\%$ non-abstained.
- **Autonomous Error Rate:** $0.00\%$ under fail-closed safety gating.
- **Harm-Weighted Loss:** $0.00\%$ (zero high-stakes errors).
- **Drift Detection:** Triggered in 5 days post-drift, with 0 false alarms in 60-day pre-drift window.
- **CI LLM Spend:** $\$0.0000$ using deterministic offline evaluation fixtures.
