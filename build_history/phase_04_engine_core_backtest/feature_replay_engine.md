# Feature: Event-Sourced Replay Engine

**Component:** `backend/src/probation/engine/replay.py`  
**Phase:** Phase 4 — Engine Core and Backtest  
**Authority:** `docs/ENGINE_SPEC.md` section 1, `docs/CONTRACT.md` section 2, invariants I-6, I-7, I-9.

---

## 1. Overview
The replay loop is the core test harness for Probation. It drives simulated past time forward monotonically, processing four primary event types on a unified chronological timeline:
1. `OUTCOME_KNOWN` (priority 0): User actions become visible to the engine.
2. `LICENCE_REVIEW` (priority 1): Daily review tick (licence evaluation in Phase 5).
3. `RETRAIN` (priority 2): Weekly retrain tick for policy and novelty models.
4. `SITUATION` (priority 3): Predicts action, evaluates novelty, and emits proposals with `gate = SHADOW`.

---

## 2. Invariants Enforced
- **Temporal Isolation (Invariant I-6)**: Retrain and situational prediction only access records where `known_at <= clock.now_iso()`. Future data cannot leak into past decisions.
- **Clock Protocol (Invariant I-9)**: Replay time strictly uses `Clock(mode=ClockMode.REPLAY)`. Wall clock calls are strictly forbidden in `engine/`.
- **Append-Only Tamper-Evident Ledger (Invariant I-7)**: Every proposal emitted is recorded into SQLite `proposals` table and hash-chained into `ledger` with sequential sequence numbers.
- **Fail-Closed Execution (Invariant I-3)**: Missing or corrupt features trigger `ABSTAIN` with reason `featurization_failed`.
