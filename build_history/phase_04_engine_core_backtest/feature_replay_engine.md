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


## WP1 repair update - 22 October 2026

### 1. Overview
Commit final proposals before dispatch. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5; CONTRACT remains unchanged.

### 2. Technical rationale
Replay scopes one clock for its roles, builds target bindings from a bounded source record, persists immutable complete proposal state and commits before Executor consumption. Missing target/draft data becomes ASK. A second DB connection proves the consumer sees durable parameters, explanation and ledger linkage. This does not complete WP2 replay chronology or WP4 model explanations.

### 3. Database schema impact
No persistent schema/ledger-byte migration or new dependency.

### 4. Core logic and necessary functions
backend/src/probation/engine/replay.py: run_replay(conn, clock=None, family=None, until=None, world=None, reader_callable=None). backend/src/probation/engine/proposal_data.py: proposal_parameters(situation, action, history, reader). backend/src/probation/db/proposals.py: persist_proposal(access, proposal, *, draft=None).
Why/how called: Replay scopes one clock for its roles, builds target bindings from a bounded source record, persists immutable complete proposal state and commits before Executor consumption. Missing target/draft data becomes ASK. A second DB connection proves the consumer sees durable parameters, explanation and ledger linkage. This does not complete WP2 replay chronology or WP4 model explanations.

### 5. Testing and verification
Test files test_wp1_replay_persistence.py, test_wp1_proposals.py and test_wp1_execution_authority.py (T-E2E/T-SEC).
An earlier isolated full checkpoint passed 291 tests plus lint/types; later targeted results are recorded in docs/reports/wp1-progress-2026-10-22.md. Final checks remain required after all edits.

### 6. Dependencies and remaining work
WP0 committed c92131c; WP1 is in progress. See the progress report for open role/transaction, canonical-payload, clock/identity and handoff requirements. This update is not a WP1 completion claim or live-provider proof.
