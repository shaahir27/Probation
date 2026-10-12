# Phase 3 Summary: Mail and Calendar Packs

**Phase:** Phase 3 — Mail and Calendar Packs  
**Status:** Completed  
**Lane:** Lane A (Member 1)  

---

## 1. Executive Summary
Phase 3 establishes the primary domain packs for Probation: `mail` and `calendar`. It bridges raw imported footprints from Phase 2 into canonical, redacted `situations` and computes deterministic and reader-derived `features` strictly bounded by `HistoryView(as_of=t)`. Priority-ranked outcome resolution with right-censoring, `SimWorld` execution and undo, counterfactual exam perturbation operators, and offline `StubReader` test harness were fully implemented and verified.

---

## 2. Key Accomplishments
1. **Domain Pack Protocol & Registry**:
   - Aligned `PackAdapter`, `WorldView`, `ExecutorIO`, `ActionSpec`, `ReaderSpec`, `ExamOperator`, and `ExecResult` with `CONTRACT.md` Section 5.
   - Built `PackRegistry` with automated validation and registration.
2. **Mail Domain Pack (`packs/mail/`)**:
   - Situation extraction for incoming emails (`email_action`).
   - Normalisation and tiers (`automated`, `frequent`, `known`, `unknown`).
   - All 16 deterministic clues strictly via `HistoryView(as_of=s.occurred_at)`.
   - Priority-ranked outcome resolution: `REPLY` > `FORWARD` > `TRASH` > `ARCHIVE` > `LEAVE` with 7-day right-censoring.
   - Execution and undo in `SimWorld` for labels.
   - 10 exam perturbation operators and validators.
3. **Calendar Domain Pack (`packs/calendar/`)**:
   - Situation extraction for inbound meeting invites (`invite_rsvp`).
   - Organiser tier counting calendar and mail interactions.
   - All 12 deterministic clues strictly via `HistoryView`.
   - Outcome resolution: `ACCEPT`, `DECLINE`, `TENTATIVE`, `NO_RESPONSE` with event start cutoff.
   - Execution and undo in `SimWorld` for RSVP status and `BLOCK_TIME`.
   - 6 exam perturbation operators and validators.
4. **Worker Pipeline Integration**:
   - `workers/ingestor.py` extracting situations under `Role.INGESTOR`.
   - `workers/brain.py` featurizing situations under `Role.BRAIN`.
   - `probation ingest` CLI subcommand.
5. **Contract Test Suites**:
   - `T-PACK` (7 conformance checks for registered packs).
   - `T-RESOLVE` (priority tables, window cutoffs, censoring).
   - End-to-end ingestion and featurization test on `tiny_synth`.

---

## 3. Verification & Compliance
* `.\make.cmd check`:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (111 files clean).
  - `mypy`: Passed (0 errors across 91 source files).
  - `pytest`: 52 passed in 7.37s.
