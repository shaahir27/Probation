# Phase 4 Summary: Engine Core and Backtest

**Phase:** Phase 4 — Engine Core and Backtest  
**Status:** Completed  
**Lane:** Lane A (Member 1)  

---

## 1. Executive Summary
Phase 4 builds the core event-sourced backtest replay loop for Probation (the "driving test on your own history"). It integrates feature standardization, calibrated time-decay logistic regression policy models, leave-one-out K-NN novelty anomaly detection, Empirical Bayes Beta lower-bound confidence intervals (matching all 10 golden numbers), immutable proposal emission into SQLite and the hash-chained ledger, and comprehensive report card generation against baselines B0 (majority class), B1 (always ask), and B2 (generic heuristic rules).

---

## 2. Key Accomplishments
1. **Event-Sourced Replay Timeline (`engine/replay.py`)**:
   - Replays history over a merged chronological timeline of `OUTCOME_KNOWN` (priority 0), `LICENCE_REVIEW` (priority 1), `RETRAIN` (priority 2), and `SITUATION` (priority 3).
   - Enforces strict no-peeking invariant (Invariant I-6): data with `known_at > t` is never visible at time `t`.
   - Advances simulated `Clock` monotonically.
   - Emits immutable proposals with `gate = GateDecision.SHADOW` (Phase 4).
   - Appends all proposals and resolved outcomes to the hash-chained tamper-evident ledger.
2. **Empirical Bayes Beta Lower Bound (`engine/evidence.py`)**:
   - Implemented exact formula: $\alpha_0 = \max(1.0, \kappa \cdot p)$, $\beta_0 = \max(1.0, \kappa \cdot (1 - p))$, $\text{LB} = \text{Beta.ppf}(q, \alpha_0 + k, \beta_0 + (n - k))$.
   - Verified 100% agreement with all 10 Golden Numbers from `ENGINE_SPEC.md` Section 16 (`T-LB`).
3. **Feature Encoding & Featurization Hash (`engine/features.py`)**:
   - `FeatureEncoder`: Standardizes numeric features and one-hot encodes categoricals. Handles cold start, missing values, and unseen categorical levels gracefully without crashing.
   - `compute_features_hash`: Returns canonical SHA-256 hash over deterministic clues, reader output, and featurizer version.
4. **Calibrated Policy Model (`engine/policy.py`)**:
   - Multinomial Logistic Regression with time-decay sample weighting: $0.5^{\text{age} / \text{half\_life}}$.
   - Cold start: returns `ABSTAIN` with reason `cold_start` when training rows $< 20$ or $< 2$ distinct actions.
   - Temperature scaling calibration: bounded scalar optimization ($T \in [0.5, 5.0]$) when training rows $\ge 100$.
5. **Novelty Anomaly Detector (`engine/novelty.py`)**:
   - Computes mean cosine distance to the $K$-nearest training situations.
   - Sets dynamic threshold $\theta$ using leave-one-out percentile thresholding.
6. **Baselines & Report Card (`engine/baselines.py`, `engine/report.py`)**:
   - Baselines B0 (majority class), B1 (always ask), and B2 (generic rules).
   - Generates report card evaluating `same`, `different`, `would_ask`, and `censored` items against strong observed outcomes.
7. **CLI `probation backtest` (`cli.py`)**:
   - Interactive command executing replay and rendering rich report card tables.

---

## 3. Verification & Compliance
* `.\make.cmd check`:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (121 files clean).
  - `mypy`: Passed (0 errors across 92 source files in strict mode).
  - `pytest`: 87 passed in 22.37s.
* Key Test Suites:
  - `T-LB`: All 10 golden numbers pass within tolerance.
  - `T-POLICY`: Cold start, time decay, temperature calibration ($T \in [0.5, 5.0]$).
  - `T-NOVELTY`: In-distribution vs out-of-distribution cosine distance separation.
  - `T-NOPEEK`: Zero peeking differences across 50 random cuts on `tiny_synth`.
  - `T-E2E`: Full replay, verified hash-chained ledger, and cryptographic determinism.
