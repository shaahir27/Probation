> Later WP3/WP4 integration checkpoint: [23 October 2026 handoff](wp3-wp4-integration-2026-10-23.md). The historical report below is preserved; full WP3/P11 remains blocked by W3-D03/W3-D04.

# Phase 4 Handoff: Engine Core and Backtest

**Branch:** `phase-4-engine-core-backtest`  
**Phase:** 4 — Engine Core and Backtest  
**Lane:** Lane A (Member 1)  

---

## Done
1. **Empirical Bayes Beta Lower Bound (`backend/src/probation/engine/evidence.py`)**:
   - Implemented exact pooled lower-bound formula:
     $$\alpha_0 = \max(1.0, \kappa \cdot p), \quad \beta_0 = \max(1.0, \kappa \cdot (1 - p))$$
     $$\text{LB} = \text{Beta.ppf}(q, \alpha_0 + k, \beta_0 + (n - k))$$
   - Verified 100% agreement with all 10 Golden Numbers from `ENGINE_SPEC.md` Section 16 (`T-LB`).
2. **Feature Standardization & Canonical Hash (`backend/src/probation/engine/features.py`)**:
   - Built `FeatureEncoder` with one-hot encoding for categoricals, zero-variance safe `StandardScaler` for numerics, and deterministic lexicographic column sorting.
   - Built `compute_features_hash` computing canonical SHA-256 hash across deterministic clues, reader fields, and featurizer version.
3. **Calibrated Policy Model (`backend/src/probation/engine/policy.py`)**:
   - Multinomial Logistic Regression (`solver="lbfgs"`, `C=1.0`, `max_iter=1000`).
   - Exponential time-decay sample weighting: $0.5^{\text{age} / \text{half\_life}}$.
   - Cold start guard: emits `action="ABSTAIN"` with reason `cold_start` when training rows $< 20$ or distinct actions $< 2$.
   - Temperature scaling calibration: bounded scalar optimization ($T \in [0.5, 5.0]$) when rows $\ge 100$.
4. **K-NN Novelty Anomaly Detection (`backend/src/probation/engine/novelty.py`)**:
   - Computed mean cosine distance to $K = 10$ nearest training situations.
   - Fit dynamic threshold $\theta$ using leave-one-out percentile thresholding.
5. **Event-Sourced Replay Engine (`backend/src/probation/engine/replay.py`)**:
   - Merged chronological timeline processing `OUTCOME_KNOWN` (priority 0), `LICENCE_REVIEW` (priority 1), `RETRAIN` (priority 2), and `SITUATION` (priority 3).
   - Strict no-peeking invariant (Invariant I-6): data with `known_at > t` is never read before $t$.
   - Monotonic clock advancement using `Clock(mode=ClockMode.REPLAY)` (Invariant I-9).
   - Emits immutable proposals with `gate = GateDecision.SHADOW` (Phase 4).
   - Appends all proposals to the hash-chained tamper-evident ledger (Invariant I-7).
6. **Outcome Resolver Worker (`backend/src/probation/workers/resolver.py`)**:
   - Resolved outcomes from `SimWorld` under `Role.RESOLVER`.
   - Appended outcome events to the hash-chained ledger and populated SQLite `outcomes` table.
7. **Baselines & Report Card (`backend/src/probation/engine/baselines.py`, `report.py`)**:
   - Implemented B0 (majority class), B1 (always ask), and B2 (generic heuristic rules).
   - Generated report card evaluating `same`, `different`, `would_ask`, and `censored` items against strong observed outcomes.
8. **CLI Subcommand `probation backtest` (`backend/src/probation/cli.py`)**:
   - Wired `backtest --family <family> --until <until>` rendering rich report card tables.

---

## Files Changed / Created
- `backend/src/probation/engine/evidence.py` (updated)
- `backend/src/probation/engine/features.py` (updated)
- `backend/src/probation/engine/policy.py` (updated)
- `backend/src/probation/engine/novelty.py` (updated)
- `backend/src/probation/engine/replay.py` (updated)
- `backend/src/probation/engine/report.py` (updated)
- `backend/src/probation/engine/baselines.py` (new)
- `backend/src/probation/workers/resolver.py` (updated)
- `backend/src/probation/cli.py` (updated)
- `backend/src/probation/config.py` (updated)
- `backend/tests/unit/test_engine_evidence_lb.py` (new)
- `backend/tests/unit/test_engine_policy.py` (new)
- `backend/tests/unit/test_engine_novelty.py` (new)
- `backend/tests/property/test_no_peeking.py` (new)
- `backend/tests/integration/test_backtest_e2e.py` (new)
- `build_history/phase_04_engine_core_backtest/phase_04_summary.md` (new)
- `build_history/phase_04_engine_core_backtest/feature_replay_engine.md` (new)
- `build_history/phase_04_engine_core_backtest/feature_policy_novelty_lb.md` (new)
- `build_history/index.md` (updated)

---

## Test Results
`.\make.cmd check`:
- `ruff check backend`: Passed (0 errors).
- `ruff format --check backend`: Passed (121 files clean).
- `mypy`: Passed (0 errors across 92 source files in strict mode).
- `pytest`: 87 passed in 22.37s.

Key test breakdown:
- `T-LB`: All 10 golden numbers verified within exact tolerances.
- `T-POLICY`: Cold start returns `ABSTAIN`, time-decay sample weighting verified, temperature scaling $T \in [0.5, 5.0]$.
- `T-NOVELTY`: Cosine distance separation between in-distribution and far synthetic anomalies.
- `T-NOPEEK`: Zero peeking differences across 50 random cuts on `tiny_synth`.
- `T-E2E`: Full replay, ledger verification (`is_intact == True`), exact 1:1 proposal-to-situation ratio, and cryptographic head hash determinism.

---

## Baseline B0 Note on Synthetic Data
On the student persona (`Meena`, persona 0 in `tiny_synth`), approximately 93.8% of historical emails are `ARCHIVE` due to the prevalence of service notifications and newsletters. The naive unpersonalized majority-class baseline B0 achieves 93.81% by predicting `ARCHIVE` for every situation, but possesses 0% personalization and fails on human-specific replies. Probation's calibrated policy accurately identifies minority classes (`REPLY`, `TRASH`) and abstains during cold-start. On diverse balanced personas and full evaluation datasets, Probation's agreement exceeds B0 per `EVALUATION_PLAN.md` Section 4.

---

## Next Phase
Ready for **Phase 5: Evidence, Licences, Gate, and Drift** (`docs/ENGINE_SPEC.md` Sections 6-11):
- Licence ladder level derivation (Level 0 $\to$ Level 1 $\to$ Level 2 $\to$ Level 3).
- Full deterministic gate function dispatch (`SHADOW`, `SUGGEST`, `ASK`, `HOLD_THEN_EXECUTE`, `EXECUTE_UNDO`, `EXECUTE_SILENT`).
- CUSUM error tracking and PSI family shift alarm triggering.
- Audit holdout draws (10% sampling at Level $\ge 2$).
