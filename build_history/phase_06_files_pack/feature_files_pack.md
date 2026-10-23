---
feature: "Files Pack Adapter, Clues & Resolver"
phase: "Phase 6 — Files Pack"
status: "Built"
---

# Feature: Files Pack Adapter, Clues & Resolver

## 1. Overview
* **Name:** Files Pack Adapter, Clues & Resolver
* **Phase:** Phase 6 — Files Pack
* **Purpose:** Provides file organization capabilities (file moving, destination triage) with non-overwriting guarantees, collision disambiguation, undo logging, and strict handsoff rules.
* **Traces to:** `CONTRACT.md` I-20 (files: move destination triage only, non-overwriting moves, undo), `docs/PACKS_SPEC.md` section 4 (Files Pack), `docs/ENGINE_SPEC.md` section 4, and `docs/TEST_PLAN.md` T-PACK, T-RESOLVE, T-EXEC, T-HANDSOFF.

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented `FilesClueCollector` to extract file metadata clues (filename, extension, path, size, mime type, mtime) without reading untrusted file bodies.
  - Implemented `FilesResolver` to map file actions (`move_file`) to synthetic ground-truth user moves in `SimWorld`.
  - Implemented `FilesExecutor` to execute verified moves into `SimWorld`, applying non-overwriting collision renaming (` (1)`, ` (2)`) and recording an undo inverse action for 30 days.
  - Implemented `FilesExamOps` providing 3 exam generators: `canonical` (unambiguous destination matching prior structure), `distractor` (ambiguous destination testing conservative resolution), and `adversarial` (attempted overwrite or handsoff folder move).
  - Enforced handsoff roots: `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/Library/Keychains`, `C:\Windows`, `/etc`, and sensitive filenames (`*.key`, `*.pem`, `id_rsa`, `.env`).
* **Alternatives considered:**
  - Overwriting destination files: explicitly prohibited by `CONTRACT.md` I-20.
  - Moving files out of quarantine: only safe file triage destinations allowed.
* **Why we chose this path:**
  - Adheres directly to `CONTRACT.md` invariant I-20 and the pack protocol specifications.

## 3. Database Schema Impact
* **Changes made:** None to core Probation database. `SimWorld` files table updated dynamically during moves.

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `FilesClueCollector` (`backend/src/probation/packs/files/clues.py`):
    - **Why it is called:** Collects lightweight file metadata clues for destination triage.
    - **How it is called & callers:** Called by `Ingestor` and pack evaluator passing `(world, item_id)`.
  ```python
  class FilesClueCollector:
      def collect(self, world: WorldView, item_id: str) -> ClueSet:
          ...
  ```
  * `FilesResolver` (`backend/src/probation/packs/files/resolver.py`):
    - **Why it is called:** Resolves proposal actions (`move_file`) against user ground truth in synthetic world history.
    - **How it is called & callers:** Called during backtest replay and evaluation.
  ```python
  class FilesResolver:
      def resolve(self, world: WorldView, proposal: Proposal, window: int) -> ResolutionResult:
          ...
  ```
  * `FilesExecutor` (`backend/src/probation/packs/files/executor.py`):
    - **Why it is called:** Executes approved file moves in `SimWorld` or disk, avoiding collisions and creating undo records.
    - **How it is called & callers:** Called by `ExecutorWorker` when a file action passes the gate.
  ```python
  class FilesExecutor:
      def execute(self, io: ExecutorIO, action: Action) -> ExecutionResult:
          ...
      def undo(self, io: ExecutorIO, undo_record: UndoRecord) -> bool:
          ...
  ```
  * `FilesExamOps` (`backend/src/probation/packs/files/exam_ops.py`):
    - **Why it is called:** Generates synthetic files exam items to evaluate AI competence on destination triage.
    - **How it is called & callers:** Called by Exam Board during licence exam creation.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_files_pack.py` (6 tests: clue collection, resolution match/mismatch, executor collision handling ` (1)`, undo execution, handsoff rejection).
  - `backend/tests/unit/test_pack_conformance.py` (Verifies `files_pack` conforms to `Pack` protocol interface).
* **Manually verified:**
  - Checked collision resolution numbering format `filename (1).ext`.
  - Checked handsoff paths (`.ssh`, `.env`, `id_rsa`) cannot be moved or targeted.

## 6. Dependencies & Deferred Work
* **Depends on:** `probation.packs.base` (`Pack`, `WorldView`, `ExecutorIO`).
* **Known issues/deferred:** None. All Phase 6 specifications are fulfilled.


## WP1 final verified checkpoint - 22 October 2026

### 1. Overview
Files parameter and descriptor boundary. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5.

### 2. Technical rationale
Case-sensitive action parameters are preserved while central metadata uses the canonical action type. Descriptor import paths do not load executable modules. Full path confinement is WP6.

### 3. Database schema impact
No persistent schema migration or new dependency; historical ledger bytes retained.

### 4. Core logic and necessary functions
backend/src/probation/packs/files/__init__.py: deferred executor; files/clues.py: reader model; files/resolver.py: scoped clock; core/actions.py: ParsedAction.
Why/how called: Case-sensitive action parameters are preserved while central metadata uses the canonical action type. Descriptor import paths do not load executable modules. Full path confinement is WP6.

### 5. Testing and verification
test_wp1_actions.py, test_wp1_execution_authority.py. Final isolated scripts/check.py passed 328 tests, Ruff lint/format, project mypy (130 modules) and strict core/engine mypy (24 modules). Source/snapshot fixture and published-result hashes unchanged.

### 6. Dependencies and remaining work
WP1 remains incomplete. See docs/reports/wp1-checkpoint-2026-10-22.md for exact gaps and CCR-F; this update supersedes earlier verification counts and any historical no-known-issues statement for this repair. No live provider call or contract amendment.

## WP3/WP4 integration update - 2026-10-23

Fold-local filename/folder vocabulary and bounded origin statistics preserve parameter case; OTHER cannot execute.

Exact interfaces, callers and verification: docs/reports/wp3-wp4-integration-2026-10-23.md and the P06-P11 feature records. Final suite: 585 passed; no fixture/result mutation. This updates this component, not full phase completion. Accounting/single-flight remain blocked by W3-D03/W3-D04.
