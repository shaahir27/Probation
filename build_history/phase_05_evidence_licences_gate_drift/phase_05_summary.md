# Phase 5 Summary: Evidence, Licences, Gate, Executor, and Drift

**Phase:** Phase 5 — Evidence, Licences, Gate, Executor, and Drift  
**Status:** Completed  
**Lane:** Lane A (Member 1)  

---

## 1. Executive Summary
Phase 5 implements the core autonomy and execution engine of Probation: permissions that are earned, enforced, and revoked automatically. It establishes:
1. Strict economic and safety caps (`engine/caps.py`, `engine/handsoff.py`) with complete extension blacklists and Unicode RLO detection.
2. A deterministic, pure gate function (`engine/gate.py`) implementing fail-closed precedence, economic interruption cost bars, and reproducible 10% audit holdout.
3. An evidence aggregator (`engine/evidence.py`) that filters strictly non-auto-executed proposals and computes Empirical Bayes Beta lower bounds with hierarchical parent pooling.
4. A dynamic licence ladder (`engine/licence.py`) deriving levels 0..3 with TTL caching and ledger transition logging.
5. An Executor worker (`workers/executor.py`) operating under strict process write isolation (`Role.EXECUTOR`), managing a 10-minute hold queue for irreversible actions, re-verifying licences at execution time, executing in `SimWorld`, and performing clean undos.
6. Statistical drift monitoring (`engine/drift.py`) with CUSUM error tracking ($S \ge 5.0$), the 2-undo/30-day hard rule, and weekly Population Stability Index (PSI) feature shift checks.
7. Replay timeline and scheduler worker integration (`engine/replay.py`, `workers/scheduler.py`).

---

## 2. Key Accomplishments
1. **Caps & Hands-off (`engine/caps.py`, `engine/handsoff.py`)**:
   - Codified base caps (0..3), economic losses, recallability, and economic bars ($p^* = 1 - 1/\text{loss}$) matching `ENGINE_SPEC.md` Section 8.
   - Enforced conditional caps for unknown senders/organizers, money involvement, personal info requests, and web vetoes.
   - Enforced complete blocked extension list and Unicode right-to-left override character `\u202e` (`T-CAPS`, `T-HANDSOFF`).
2. **Pure Gate & Audit Holdout (`engine/gate.py`)**:
   - Implemented `decide_gate` matching Golden Table 3.2 in `TEST_PLAN.md` (`T-GATE`).
   - Implemented reproducible audit draw formula: $\text{int}(\text{sha256}(\text{situation\_id} + | + \text{AUDIT\_SEED})[:8], 16) / 2^{32}$.
3. **Evidence & Licence Ladder (`engine/evidence.py`, `engine/licence.py`)**:
   - Filtered strictly non-auto-executed proposals (Invariant I-12).
   - Counted weak outcomes in `all` only; counted audit-holdout items; excluded undos from Beta counts.
   - Derived licence levels 0..3; strictly enforced Invariant I-20 (level 3 impossible for non-recallable actions).
   - Injected test double for `exam_ok` until Phase 7.
4. **Executor Worker (`workers/executor.py`)**:
   - Sole process with write side-effects (`Role.EXECUTOR`).
   - Implemented hold queue (10 minutes) for irreversible actions (`HOLD_THEN_EXECUTE`).
   - Re-derives licences at execution time; produces fallback `SUGGEST` on licence drop.
   - Executes and reverses actions in `SimWorld` for mail (`ARCHIVE`, `TRASH`, `REPLY`, `FORWARD`) and calendar (`ACCEPT`, `DECLINE`, `TENTATIVE`, `BLOCK_TIME`) (`T-EXEC`).
   - Emits strong disagreement outcomes on user undo.
5. **Statistical Drift & Demotion (`engine/drift.py`)**:
   - CUSUM tracking per $(c, a)$ with alarm at $S \ge 5.0$ and immediate alarm on 2 undos in 30 days (`T-CUSUM`).
   - Alarms invalidate passed exams older than the alarm, instantly demoting levels 2 and 3 to at most 1.
   - Weekly Population Stability Index calculation across top 5 features with shares floored at $1\times 10^{-4}$ (`T-PSI`).
6. **Replay & Scheduler (`engine/replay.py`, `workers/scheduler.py`)**:
   - Integrated `LICENCE_REVIEW`, `OUTCOME_KNOWN` (CUSUM update), and `SITUATION` (licence lookup, gate decision, executor dispatch) into the event-sourced timeline.

---

## 3. Verification & Compliance
* Full check command: `.\make.cmd check`:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (126 files clean).
  - `mypy`: Passed (0 errors across 92 source files in strict mode).
  - `pytest`: 114 passed in 45.43s.
* Test Suites Passing:
  - `T-CAPS`, `T-HANDSOFF`: All catalog actions, conditional caps, dangerous extensions, and RLO character verified.
  - `T-GATE`: All 14 cases of Golden Table 3.2 pass.
  - `T-EVIDENCE`: Clean non-auto-executed filtering and licence ladder progression pass.
  - `T-CUSUM`, `T-PSI`: CUSUM error bursts, 2-undo rule, exam invalidation, and PSI shift detection pass.
  - `T-EXEC`: Mail/calendar execution, hold queue delay, licence re-check cancellation, and SimWorld undo pass.
  - `T-NOPEEK`: Zero peeking differences across 50 random cuts on `tiny_synth`.
  - `T-CLOCK`: Zero direct system clock calls in engine or core modules.
