# Feature: Policy, Novelty, and Lower-Bound Evidence

**Components:** `backend/src/probation/engine/policy.py`, `novelty.py`, `evidence.py`, `features.py`  
**Phase:** Phase 4 — Engine Core and Backtest  
**Authority:** `docs/ENGINE_SPEC.md` sections 3, 4, 5, 6.2, 16.

---

## 1. Feature Encoding (`engine/features.py`)
- Standardizes numeric features and one-hot encodes categorical levels.
- Ensures deterministic, lexicographically sorted column ordering.
- Handles unseen categories and missing values cleanly without crashing.
- `compute_features_hash`: Canonical SHA-256 hash over deterministic features, reader fields, and featurizer version.

---

## 2. Calibrated Policy Model (`engine/policy.py`)
- Multinomial Logistic Regression (`solver="lbfgs"`, `C=1.0`, `max_iter=1000`).
- Exponential time-decay sample weighting: $w_i = 0.5^{(\text{age\_days} / 90.0)}$.
- Cold start protection: If training rows $< 20$ or distinct actions $< 2$, returns `action="ABSTAIN"`, `reasons=["cold_start"]`.
- Temperature scaling calibration: Fits bounded temperature $T \in [0.5, 5.0]$ using `scipy.optimize.minimize_scalar` to minimize cross-entropy loss on validation data when rows $\ge 100$.

---

## 3. Novelty Detection (`engine/novelty.py`)
- Extracts text representations of situations.
- Computes mean cosine distance to $K = 10$ nearest training situations.
- Calibrates decision threshold $\theta$ using the 95th percentile of leave-one-out distances on the training set.

---

## 4. Empirical Bayes Beta Lower Bound (`engine/evidence.py`)
- Implements Beta lower-bound formula:
  $$\alpha_0 = \max(1.0, \kappa \cdot p), \quad \beta_0 = \max(1.0, \kappa \cdot (1 - p))$$
  $$\text{LB} = \text{Beta.ppf}(q, \alpha_0 + k, \beta_0 + (n - k))$$
- Reproduces all 10 Golden Numbers from `ENGINE_SPEC.md` section 16 within specified tolerances.

## WP3/WP4 integration update - 2026-10-23

WP4 cohort eligibility, fold-local encoder/vocabularies, chronological calibration, full policy hashing, strict local MiniLM novelty and aligned explanations are integrated.

Exact interfaces, callers and verification: docs/reports/wp3-wp4-integration-2026-10-23.md and the P06-P11 feature records. Final suite: 585 passed; no fixture/result mutation. This updates this component, not full phase completion. Accounting/single-flight remain blocked by W3-D03/W3-D04.
