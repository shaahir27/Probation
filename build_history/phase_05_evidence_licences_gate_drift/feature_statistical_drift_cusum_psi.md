---
feature: "Statistical Drift Monitoring (CUSUM) and Family Shift (PSI)"
phase: "Phase 5 — Evidence, Licences, Gate, Executor, and Drift"
status: "Built"
---

# Feature: Statistical Drift Monitoring (CUSUM) and Family Shift (PSI)

## 1. Overview
* **Name:** Statistical Drift Monitoring (CUSUM) and Family Shift (PSI)
* **Phase:** Phase 5 — Evidence, Licences, Gate, Executor, and Drift
* **Purpose:** Monitor model performance degradation per $(c, a)$ using cumulative sum (CUSUM) error tracking and weekly population feature distribution shifts via Population Stability Index (PSI), automatically raising alarms and revoking autonomous licences.
* **Traces to:** `CONTRACT.md` section 7, section 8, `ENGINE_SPEC.md` sections 11.1, 11.2, and `TEST_PLAN.md` T-CUSUM, T-PSI.

## 2. Technical Rationale
* **How we achieved it:**
  - `CUSUMTracker`: Tracks $S_t = \max(0, S_{t-1} + x_t - (\text{baseline\_err} + 0.02))$ where $x_t = 1$ for disagreements or undos/overrides; raises alarm at $S_t \ge 5.0$.
  - Hard rule: $\ge 2$ undos or overrides within 30 days triggers an immediate alarm.
  - On CUSUM alarm: sets `last_alarm_at = now`, resets $S_t = 0$, logs `LedgerKind.DRIFT_ALARM` to the ledger, and invalidates passed exams older than the alarm (instantly demoting levels 2 and 3 to at most 1).
  - `compute_psi`: Calculates $PSI = \sum (a_i - e_i) \cdot \ln(a_i / e_i)$ with shares floored at $1\times 10^{-4}$ to prevent division by zero or log singularities.
  - `check_family_shift`: Evaluates feature shifts between 90-day reference window $[t-120\text{d}, t-30\text{d}]$ and current window $[t-30\text{d}, t]$ across top features; alarms if $\max PSI > 0.25$.
* **Alternatives considered:** None; exact formula and thresholds are mandated by `ENGINE_SPEC.md` section 11.
* **Why we chose this path:** Statistical guarantees ensure silent failures or concept drift never go undetected.

## 3. Database Schema Impact
* **Changes made:**
  - Updates `drift_state` table with $S_t$, baseline error, and `last_alarm_at`.
  - Updates `family_shift` table with weekly PSI scores and alarm flags.

## 4. Core Logic & Necessary Functions
* `CUSUMTracker.update` (`backend/src/probation/engine/drift.py`): Updates CUSUM score on observations and evaluates alarm conditions.
  - **Why it is called:** Tracks performance degradation upon new outcome arrival or user undo.
  - **How it is called & callers:** Called by `engine/replay.py` on `OUTCOME_KNOWN` and by `workers/executor.py` on undo.
* `compute_psi` (`backend/src/probation/engine/drift.py`): Pure function calculating PSI between two probability distributions.
  - **Why it is called:** Measures distribution distance between baseline and current populations.
* `check_family_shift` (`backend/src/probation/engine/drift.py`): Executes weekly feature shift check per family.
  - **Why it is called:** Triggers weekly in replay and scheduler ticks.
  - **How it is called & callers:** Called by `engine/replay.py` and `workers/scheduler.py`.

```python
class CUSUMTracker:
    def __init__(
        self,
        baseline_err: float = 0.03,
        allowance: float = 0.02,
        threshold: float = 5.0,
        last_alarm_at: str | None = None,
        initial_s: float = 0.0,
    ) -> None: ...

    def update(self, is_error: bool, is_undo: bool = False, timestamp: str = "") -> bool: ...
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_drift_cusum_psi.py` (`T-CUSUM`, `T-PSI`):
    - Verifies run of successes keeps $S=0$.
    - Verifies burst of errors accumulates and alarms at threshold 5.0.
    - Verifies hard rule: 2 undos within 30 days triggers immediate alarm.
    - Verifies undos spaced > 30 days apart do not trigger immediate alarm.
    - Verifies identical distributions yield PSI near 0.
    - Verifies shifted distributions exceed 0.25.
    - Verifies floored shares prevent NaN / inf.
* **Manually verified:** Verified that exams completed before a drift alarm no longer qualify for level 2 or 3 licences.

## 6. Dependencies & Deferred Work
* **Depends on:** `db/ledger.py`, `core/enums.py`.
* **Known issues/deferred:** None.
