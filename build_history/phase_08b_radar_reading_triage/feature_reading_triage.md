---
feature: "Reading Triage Pack"
phase: "Phase 8b — Link Substrate, Opportunity Radar, Reading Triage"
status: "Built"
---

# Feature: Reading Triage Pack

## 1. Overview
* **Name:** Reading Triage Pack
* **Phase:** Phase 8b — Link Substrate, Opportunity Radar, Reading Triage
* **Purpose:** Triages and organizes web articles, research papers, and technical links into reading lists/library collections based on user reading habits.
* **Traces to:** `CONTRACT.md` I-22, `docs/TAVILY_AND_NEW_PACKS.md` section 4, `docs/PACKS_SPEC.md` section 7, `docs/TEST_PLAN.md` T-READING.

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented `ReadingClueCollector`: Ingests quarantined link metadata (title, site name, author, description, estimated reading time, topics) without raw HTML text leakage.
  - Implemented `ReadingExecutor`: Performs safe local library actions (`save_to_library`, `archive_item`, `assign_collection`, `add_tag`) on `SimWorld`'s `library` table.
  - Implemented `ReadingResolver`: Matches proposed reading actions against user ground truth within `reading_window_days` (7 days).
  - Implemented `ReadingExamOps`: Synthesizes reading list triage exam questions (`canonical`, `distractor`, `adversarial`).
  - Registered under family `link_triage` in `packs/registry.py`.
* **Alternatives considered:**
  - Parsing full body text: Disallowed by quarantine architecture (`CONTRACT.md` I-22).
* **Why we chose this path:**
  - Maintains strict quarantine boundary while providing rich reading organization.

## 3. Database Schema Impact
* **Changes made:**
  - Extended `SimWorld` schema with `library` table:
    ```sql
    CREATE TABLE IF NOT EXISTS library (
        library_id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        title TEXT NOT NULL,
        author TEXT,
        collection TEXT,
        tags TEXT,
        status TEXT NOT NULL,
        added_at TEXT NOT NULL,
        read_at TEXT
    );
    ```

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `ReadingClueCollector` (`backend/src/probation/packs/reading/clues.py`):
    - **Why it is called:** Collects metadata clues from reading link items.
    - **How it is called & callers:** Called by Ingestor for reading list candidates.
  ```python
  class ReadingClueCollector:
      def collect(self, world: WorldView, item_id: str) -> ClueSet:
          ...
  ```
  * `ReadingExecutor` (`backend/src/probation/packs/reading/executor.py`):
    - **Why it is called:** Executes library operations in `SimWorld`.
    - **How it is called & callers:** Called by `ExecutorWorker` on approved reading actions.
  ```python
  class ReadingExecutor:
      def execute(self, io: ExecutorIO, action: Action) -> ExecutionResult:
          ...
  ```
  * `ReadingResolver` (`backend/src/probation/packs/reading/resolver.py`):
    - **Why it is called:** Compares AI triage decisions to user reading history.
    - **How it is called & callers:** Called during backtest replay and evaluation.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_links_radar_reading.py` (T-READING tests: clue extraction from quarantined metadata, library CRUD in SimWorld, resolution match/mismatch).
  - `backend/tests/unit/test_pack_conformance.py` (Conforms to Pack protocol under family `link_triage`).
* **Manually verified:**
  - Verified `library` entry creation and collection assignment.

## 6. Dependencies & Deferred Work
* **Depends on:** `probation.links`, `probation.packs.base`.
* **Known issues/deferred:** None.
