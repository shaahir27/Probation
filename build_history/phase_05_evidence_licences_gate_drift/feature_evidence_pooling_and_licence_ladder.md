---
feature: "Evidence Pooling, Beta Lower Bounds, and Licence Ladder Derivation"
phase: "Phase 5 — Evidence, Licences, Gate, Executor, and Drift"
status: "Built"
---

# Feature: Evidence Pooling, Beta Lower Bounds, and Licence Ladder Derivation

## 1. Overview
* **Name:** Evidence Pooling, Beta Lower Bounds, and Licence Ladder Derivation
* **Phase:** Phase 5 — Evidence, Licences, Gate, Executor, and Drift
* **Purpose:** Collect non-auto-executed past proposals and observed user outcomes over a 180-day window, calculate Empirical Bayes Beta lower-bound success rates with hierarchical parent pooling, and derive dynamic autonomy licences cached with TTL.
* **Traces to:** `CONTRACT.md` invariants I-10, I-11, I-12, `ENGINE_SPEC.md` sections 6.1, 6.2, 6.3, 16, and `TEST_PLAN.md` T-EVIDENCE, T-LB.

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented `aggregate_evidence`: filters strictly non-auto-executed proposals (`gate IN ('SHADOW', 'SUGGEST', 'ASK')`); excludes auto-executed items (Invariant I-12) and undo outcomes from Beta counts; includes audit-holdout items; calculates $(n_{strong}, k_{strong})$, $(n_{all}, k_{all})$, and $n_{recent}$ (last 30 days).
  - Empirical Bayes hierarchical pooling: extracts parent class key; computes parent mean $p_{parent} = (k_{parent} + 1) / (n_{parent} + 2)$ if $n_{parent} \ge 20$; computes lower bounds via Beta ppf.
  - Implemented `derive_licence_level`: derives levels 0..3 based on $n_{all} \ge 20, LB_{all} \ge 0.70$ (Level 1), $n_{strong} \ge 40, n_{recent} \ge 20, LB_{strong} \ge 0.95, \text{exam\_ok}$ (Level 2), and $LB_{strong} \ge 0.98, \text{recallable}$ (Level 3).
  - Injected test double for `exam_ok` until Phase 7 exam board.
  - Appends `LedgerKind.LICENCE_CHANGE` to the hash-chained ledger upon level transitions.
* **Alternatives considered:** None; exact Beta quantiles and progression rules are specified in `ENGINE_SPEC.md`.
* **Why we chose this path:** Preserves contract invariant that licences are derived views of evidence, never asserted truth.

## 3. Database Schema Impact
* **Changes made:**
  - Populates `class_stats` table with rolling window aggregations and lower bounds.
  - Populates `licence_cache` table with derived licences and `valid_until` TTLs.

## 4. Core Logic & Necessary Functions
* `aggregate_evidence` (`backend/src/probation/engine/evidence.py`): Queries proposals and outcomes within rolling 180-day window and calculates lower bounds.
  - **Why it is called:** Recomputes evidence base on daily `LICENCE_REVIEW` ticks.
  - **How it is called & callers:** Called by `engine/replay.py` and `workers/scheduler.py`.
* `derive_licence_level` (`backend/src/probation/engine/licence.py`): Pure function deriving autonomy tier 0..3.
  - **Why it is called:** Evaluates if evidence volume, recent activity, and exam status satisfy the contract thresholds.
* `derive_and_cache_licences` (`backend/src/probation/engine/licence.py`): Updates `licence_cache` table and appends `LedgerKind.LICENCE_CHANGE` events.
* `check_exam_ok` (`backend/src/probation/engine/licence.py`): Validates that an uninvalidated passed exam run exists that is newer than both drift and family-shift alarms.

```python
def derive_licence_level(
    action: str,
    n_all: int,
    lb_all: float,
    n_strong: int,
    lb_strong: float,
    n_recent: int,
    exam_ok_fn: Callable[[int], bool] | None = None,
    cap: int | None = None,
    recallable: bool | None = None,
    current_level: int = 0,
) -> LicenceLevel: ...
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_evidence_aggregation_and_licence.py` (`T-EVIDENCE`): Verifies auto-executed items are excluded, audit holdouts are counted, weak outcomes are counted only in all, undos are excluded from Beta counts, and licence ladder progression and demotion behave as specified.
  - `backend/tests/unit/test_engine_evidence_lb.py` (`T-LB`): Validates all 10 Golden Numbers from `ENGINE_SPEC.md` Section 16.
* **Manually verified:** Verified that demotion occurs automatically when exams are invalidated or evidence decays below thresholds.

## 6. Dependencies & Deferred Work
* **Depends on:** `engine/caps.py`, `db/ledger.py`, `core/enums.py`.
* **Known issues/deferred:** Full adversarial counterfactual perturbation operators and automatic exam generation belong to Phase 7.
