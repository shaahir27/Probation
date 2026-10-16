# Phase 5 Handoff: Evidence, Licences, Gate, Executor, and Drift

**Branch / Commit:** `phase-5-evidence-licences-gate` / `8047bac`  
**Phase:** 5 — Evidence, Licences, Gate, Executor, and Drift  
**Lane:** Lane A (Member 1)  

---

## Done
1. **Caps & Hands-Off Rules (`backend/src/probation/engine/caps.py`, `handsoff.py`)**:
   - Codified complete `ACTION_CATALOG` across `email_action` and `calendar_action` families with base caps, loss matrix values, recallable flags, and derived economic interruption bars ($p^* = 1 - 1/\text{loss}$).
   - Codified contextual conditional caps: VIP sender, external recipients, bulk recipients (>5), thread lengths (>10), sensitive keywords (financial, legal, security), blocked dangerous extensions (`.exe`, `.bat`, `.cmd`, `.msi`, `.ps1`), double extensions (`.pdf.exe`), and Unicode RLO (`\u202e`).
   - Implemented `effective_cap(base, context)` using integer `min` aggregation.

2. **Pure Gate Engine (`backend/src/probation/engine/gate.py`)**:
   - Implemented pure `decide_gate` with strict fail-closed precedence order:
     1. Hands-off violation $\to$ `NEVER` / `ASK`
     2. Budget exhausted $\to$ `ASK`
     3. Licence level $\to$ bounds max permitted gate
     4. Economic interruption test: $p(\text{action}) < p^*$ $\to$ demote to `ASK`
     5. Novelty / ambiguity $\to$ demote to `ASK`
     6. Audit holdout: reproducible 10% draw $\to$ demote to `ASK`
     7. Cap reduction $\to$ demote to `min(decision, cap)`
   - Verified 100% agreement with all 14 rows of Golden Table 3.2 in `CONTRACT.md` (`T-GATE`).
   - Implemented reproducible audit draw via SHA-256 HMAC of `(audit_seed, situation_id, class_key)`.

3. **Evidence Aggregation & Hierarchical Empirical Bayes (`backend/src/probation/engine/evidence.py`)**:
   - Implemented `aggregate_evidence` filtering out auto-executed items (Invariant I-12) and undo outcomes from Beta counts.
   - Tracked weak evidence (supports Level 1 only) vs strong evidence (explicit accepts/edits/undos).
   - Tracked audit holdouts and undo counts ($n_{\text{undo}}$).
   - Applied hierarchical Empirical Bayes pooling: action-level $\to$ class-key level $\to$ global prior, computing exact lower bounds (`Beta.ppf`).

4. **Dynamic Licence Ladder & Cache (`backend/src/probation/engine/licence.py`)**:
   - Implemented `derive_licence_level` (Levels 0..3) based on lower bound thresholds ($\ge 0.70, 0.85, 0.95$), sample size thresholds ($n \ge 5, 20, 50$), exam pass status, non-recallable cap at Level 2 (Invariant I-20), and drift alarm invalidations.
   - Built `derive_and_cache_licences` with TTL caching and ledger event emission.

5. **Statistical Drift & Anomaly Monitoring (`backend/src/probation/engine/drift.py`)**:
   - Built `CUSUMTracker` tracking sequential error deviation: $S_t = \max(0, S_{t-1} + e_t - k)$, raising alarms at $S_t \ge 5.0$, with fast-path 2-undo/30-day immediate alarm.
   - Built Population Stability Index (`compute_psi`) floored at $1\times 10^{-4}$ with 10 quantiles.
   - Built `check_family_shift` running weekly checks over top 5 feature dimensions.
   - Zero direct system clock calls (Invariant I-9).

6. **Executor Worker & SimWorld Execution (`backend/src/probation/workers/executor.py`)**:
   - Implemented `Executor` strictly under `Role.EXECUTOR` (Invariant I-2).
   - Built 10-minute hold queue for irreversible and hold actions, advancing deterministically with clock.
   - Re-verified licences at execution time, falling back to `SUGGEST` if revoked.
   - Executed mutations on `SimWorld` for mail and calendar.
   - Implemented undo handling, emitting strong negative feedback outcomes to evidence.

7. **Replay Engine & Scheduler Integration (`replay.py`, `scheduler.py`)**:
   - Integrated dynamic gate dispatch, daily licence review events, weekly drift checks, and executor queue flushing into `ReplayTimeline`.

---

## Files Changed / Created
- `backend/src/probation/config.py` (updated: audit seed)
- `backend/src/probation/engine/__init__.py` (updated: exported caps, gate, licence, drift)
- `backend/src/probation/engine/caps.py` (updated: catalog, loss matrix, conditional caps)
- `backend/src/probation/engine/drift.py` (updated: CUSUM tracker, PSI, shift check)
- `backend/src/probation/engine/evidence.py` (updated: aggregation, filtering, pooling)
- `backend/src/probation/engine/gate.py` (updated: pure decide_gate, audit draw)
- `backend/src/probation/engine/handsoff.py` (updated: dangerous & double extensions, Unicode RLO)
- `backend/src/probation/engine/licence.py` (updated: ladder derivation, cache, exam check)
- `backend/src/probation/engine/replay.py` (updated: licence reviews, drift checks, gate dispatch)
- `backend/src/probation/packs/base.py` (updated: runtime_checkable protocol)
- `backend/src/probation/workers/__init__.py` (updated: exported Executor)
- `backend/src/probation/workers/executor.py` (updated: queue, simworld execution, undo)
- `backend/src/probation/workers/scheduler.py` (updated: nightly review, weekly shifts)
- `build_history/index.md` (updated: Phase 5 entries)
- `build_history/phase_05_evidence_licences_gate_drift/feature_caps_handsoff_pure_gate.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/feature_evidence_pooling_and_licence_ladder.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/feature_executor_worker_and_simworld.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/feature_statistical_drift_cusum_psi.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/phase_05_summary.md` (new)
- `backend/tests/unit/test_caps_and_handsoff.py` (new: T-CAPS, T-HANDSOFF)
- `backend/tests/unit/test_gate_pure.py` (new: T-GATE Golden Table 3.2)
- `backend/tests/unit/test_drift_cusum_psi.py` (new: T-CUSUM, T-PSI)
- `backend/tests/unit/test_evidence_aggregation_and_licence.py` (new: T-EVIDENCE)
- `backend/tests/unit/test_executor_simworld.py` (new: T-EXEC)
- `docs/reports/phase-5.md` (new: handoff report)

---

## Tests
`.\make.cmd check`:
- `ruff check backend`: Passed (0 errors).
- `ruff format --check backend`: Passed (126 files clean).
- `mypy`: Passed (0 errors across 92 source files in strict mode).
- `pytest`: 114 passed in 45.43s.

Acceptance Tests Passing:
- `T-CAPS`: Base caps, loss matrix, and context condition caps combinable by min.
- `T-HANDSOFF`: Extension blocking, double extensions, Unicode RLO, VIP/external demotions.
- `T-GATE`: All 14 rows of CONTRACT Table 3.2 Golden Gate decisions tested and matching.
- `T-EVIDENCE`: Beta counts, auto-action filtering (I-12), undo exclusion, weak evidence constraints.
- `T-CUSUM`: Sequential error accumulation, $S_t \ge 5.0$ alarm, fast-path 2-undo alarm.
- `T-PSI`: Flooring at $10^{-4}$, 10 quantiles, sensitive to feature shifts $> 0.25$.
- `T-EXEC`: Role.EXECUTOR gating, 10-minute hold queue, SimWorld email & calendar mutations, undo handling.

---

## Invariants Touched
- `I-2` (Only the Executor acts): Maintained. All mutations in `SimWorld` are dispatched solely via `Executor` requiring `Role.EXECUTOR`.
- `I-3` (Fail closed): Maintained. Precedence order in gate fails closed to `ASK` or `SUGGEST` on anomaly, drift, missing licence, or economic bar.
- `I-6` (No peeking): Maintained. Replay timeline and history view strictly restrict queries to `known_at <= as_of`.
- `I-7` (Tamper-evident ledger): Maintained. All proposals, gate decisions, executions, and undos append to the cryptographic ledger.
- `I-9` (Clock): Maintained. Zero direct calls to `datetime.now()` or `time.time()` in `core/` or `engine/`. Replay timestamps injected everywhere.
- `I-10` (Caps are hard-coded): Maintained. Action catalog caps and loss matrices are immutable code constants, never overridden by model weights.
- `I-11` (Derived licences): Maintained. Licences are derived purely from aggregated evidence on demand; never stored as independent ground truth.
- `I-12` (Independent evidence): Maintained. Automatic executions without human validation are excluded from Beta evidence updates.
- `I-13` (Audit holdouts): Maintained. 10% deterministic audit draws demote Level $\ge 2$ actions to `ASK` and tag them for evaluation.
- `I-20` (Non-recallable actions capped at Level 2): Maintained. Actions marked `recallable=False` cannot attain Level 3 (`EXECUTE_SILENT`).

---

## Deviations and Assumptions
None. All components were built in strict compliance with `CONTRACT.md` and `ENGINE_SPEC.md`.

---

## Contract Change Requests
None.

---

## New Dependencies
None.

---

## LLM Cost Incurred
$0.00 (0 calls). All Phase 5 components are deterministic code and statistical computations.

---

## Open Questions
None.

---

## Suggested Next Step
Proceed to **Phase 6: Files Pack** (`docs/PACKS_SPEC.md` Section 3, `docs/ENGINE_SPEC.md` Sections 4 and 8.2, `docs/IMPLEMENTATION_PLAN.md`).
