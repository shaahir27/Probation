---
feature: "Evaluation Metrics and Comparison Baselines (B0-B3)"
phase: "Phase 10 — Evaluation & Benchmarks"
status: "Built"
---

# Feature: Evaluation Metrics and Comparison Baselines (B0-B3)

## 1. Overview
* **Name:** Evaluation Metrics and Comparison Baselines (B0-B3)
* **Phase:** Phase 10 — Evaluation & Benchmarks
* **Purpose:** Provides pure mathematical implementations of evaluation metrics (agreement, autonomous error rate, harm-weighted error, autonomous coverage, attention units, calibration ECE/Brier, drift delay, chain metrics) and standardized comparison baselines B0, B1, B2, and B3.
* **Traces to:** `docs/EVALUATION_PLAN.md` sections 3 and 4, `docs/TEST_PLAN.md` T-EVAL, `docs/CONTRACT.md`.

## 2. Technical Rationale
* **How we achieved it:** Implemented `backend/src/probation/eval/metrics.py` as pure functions with exact mathematical formulations matching hand-calculated golden fixtures to $10^{-9}$. Implemented `backend/src/probation/eval/baselines.py` containing `MajorityBaseline` (B0), `AskAlwaysBaseline` (B1), `GenericRulesBaseline` (B2), and `LLMConfidenceBaseline` (B3) supporting confidence threshold sweeps $\tau \in \{0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.99\}$ with offline caching to guarantee $\$0.00$ live spend during CI.
* **Alternatives considered:** Relying on scikit-learn metrics was rejected because Probation's specialized safety metrics (e.g. attention units with $0.3$ suggestion weight, harm-weighted loss per action class, equal-width ECE over strong outcomes) require exact alignment with contract invariants.
* **Why we chose this path:** Mathematical precision, deterministic execution without network I/O in unit tests, and adherence to the no-peeking principle (`HistoryView(as_of=t)`).

## 3. Database Schema Impact
* **Changes made:** None. The evaluation metrics and baseline predictors are pure in-memory functions and classes.

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `compute_agreement` (`backend/src/probation/eval/metrics.py`): Computes empirical agreement rate overall and non-abstained.
  * `compute_autonomous_error_rate` (`backend/src/probation/eval/metrics.py`): Measures mistake rate among autonomously executed proposals.
  * `compute_harm_weighted_error` (`backend/src/probation/eval/metrics.py`): Weights autonomous errors by action loss $L(a)$ from `caps.py`.
  * `compute_autonomous_coverage` (`backend/src/probation/eval/metrics.py`): Computes percentage of non-noop tasks autonomously handled correctly.
  * `compute_interruptions` (`backend/src/probation/eval/metrics.py`): Calculates asks/100, suggestions/100, and attention units per 100 ($100 \times (\text{asks} + 0.3 \times \text{suggestions}) / N$).
  * `compute_calibration` (`backend/src/probation/eval/metrics.py`): Computes 10-bin ECE and Brier score over strong outcomes.
  * `compute_drift_metrics` (`backend/src/probation/eval/metrics.py`): Calculates detection delay and pre-drift false alarms.
  * `compute_chain_metrics` (`backend/src/probation/eval/metrics.py`): Computes precision and recall of mined cross-tool action sequences against planted truth.
  * `MajorityBaseline` (`backend/src/probation/eval/baselines.py`): B0 baseline predicting modal past action per family.
  * `AskAlwaysBaseline` (`backend/src/probation/eval/baselines.py`): B1 baseline yielding $100\%$ interruptions and zero autonomy.
  * `GenericRulesBaseline` (`backend/src/probation/eval/baselines.py`): B2 non-personal static heuristic baseline.
  * `LLMConfidenceBaseline` (`backend/src/probation/eval/baselines.py`): B3 KnowNo-style confidence thresholding baseline over sweeps of $\tau$.

```python
def compute_interruptions(
    asks: int,
    suggestions: int,
    total_situations: int,
    suggestion_weight: float = 0.3,
) -> InterruptionMetrics:
    if total_situations <= 0:
        return InterruptionMetrics(0.0, 0.0, 0.0, asks, suggestions, total_situations)
    n = float(total_situations)
    return InterruptionMetrics(
        asks_per_100=100.0 * float(asks) / n,
        suggestions_per_100=100.0 * float(suggestions) / n,
        attention_units_per_100=100.0 * (float(asks) + suggestion_weight * float(suggestions)) / n,
        asks=asks,
        suggestions=suggestions,
        total=total_situations,
    )
```

## 5. Testing & Verification
* **Automated tests:** `backend/tests/unit/test_eval.py` (T-EVAL).
  * `test_t_eval_precision_hand_computed`: Verified $k/n$ precision matches hand calculation to $10^{-9}$.
  * `test_t_eval_agreement_hand_computed`: Verified agreement with/without abstentions.
  * `test_t_eval_autonomous_error_rate_hand_computed`: Verified autonomous error rate.
  * `test_t_eval_harm_weighted_error_hand_computed`: Verified loss-weighted mistake scoring.
  * `test_t_eval_autonomous_coverage_hand_computed`: Verified non-noop coverage.
  * `test_t_eval_interruptions_hand_computed`: Verified attention units formula.
  * `test_t_eval_calibration_ece_and_brier_hand_computed`: Verified 10-bin ECE and Brier score against hand calculations.
  * `test_t_eval_drift_metrics_hand_computed`: Verified 60-day false alarm and post-drift detection delay.
  * `test_t_eval_chain_metrics_hand_computed`: Verified mined chain precision/recall.
  * `test_baselines_b0_majority`, `test_baselines_b1_ask_always`, `test_baselines_b2_generic_rules`, `test_baselines_b3_llm_confidence_sweeps`: Verified all 4 baseline behaviors.
* **Manually verified:** Evaluated against `tiny_synth/truth.json` counterfactual data.

## 6. Dependencies & Deferred Work
* **Depends on:** `probation.core.types.Situation`, `probation.core.enums.Gate`, `probation.engine.caps.get_action_loss`.
* **Known issues/deferred:** None. All required metrics in `docs/EVALUATION_PLAN.md` section 3 are fully implemented.

## WP3/WP4 integration update - 2026-10-23

Unavailable B3 stays ABSTAIN/ASK/not-run; reporting exposes real denominators and missing baseline coverage.

Exact interfaces, callers and verification: docs/reports/wp3-wp4-integration-2026-10-23.md and the P06-P11 feature records. Final suite: 585 passed; no fixture/result mutation. This updates this component, not full phase completion. Accounting/single-flight remain blocked by W3-D03/W3-D04.
