---
feature: "Opportunity Radar Pack & Out-of-Band Vetting"
phase: "Phase 8b — Link Substrate, Opportunity Radar, Reading Triage"
status: "Built"
---

# Feature: Opportunity Radar Pack & Out-of-Band Vetting

## 1. Overview
* **Name:** Opportunity Radar Pack & Out-of-Band Vetting
* **Phase:** Phase 8b — Link Substrate, Opportunity Radar, Reading Triage
* **Purpose:** Detects, scores, and tracks relevant professional opportunities (grants, fellowships, jobs, CFPs) while enforcing strict out-of-band vetting against scam patterns and capping autonomy when fees or sensitive documents are involved.
* **Traces to:** `CONTRACT.md` I-21, I-23, I-25, `docs/TAVILY_AND_NEW_PACKS.md` section 3, `docs/PACKS_SPEC.md` section 6, `docs/TEST_PLAN.md` T-RADAR.

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented `RadarClueCollector` to extract opportunity metadata clues: entity name, title, description, deadline, compensation, requirements, and risk flags (`fee_required`, `sensitive_docs_requested`).
  - Integrated `RadarOutOfBandVerifier`: Cross-checks opportunity sponsor domain using `WebFactsView` / `EntityFacts`. If domain has `reports_found`, `lookalike`, or `no_web_presence`, flags opportunity as high risk and sets autonomy cap = 1.
  - Implemented conditional cap in `engine/caps.py`: Any opportunity triage action that involves upfront fees or personal identity documents is hard-capped at rank 1 (`PROPOSAL_ONLY`).
  - Implemented `RadarExecutor`: Executes approved actions (`track_opportunity`, `dismiss_opportunity`, `flag_opportunity`) into `SimWorld`'s `tracker` table with status tracking (`tracked`, `dismissed`, `applied`).
  - Implemented `RadarResolver`: Resolves backtest proposals against ground-truth user actions within `radar_window_days` (14 days) or `radar_min_window_days` (3 days).
  - Implemented `RadarDigestGenerator`: Formats prioritized opportunity digests with source citations and safety annotations.
  - Implemented `RadarExamOps`: Synthesizes canonical, distractor, and adversarial opportunity triage exam cases.
* **Alternatives considered:**
  - Auto-submitting applications: explicitly prohibited by `CONTRACT.md` (no external applications, write actions restricted to internal tracker).
* **Why we chose this path:**
  - Strictly follows `CONTRACT.md` safety guarantees while delivering rich opportunity tracking.

## 3. Database Schema Impact
* **Changes made:**
  - Extended `SimWorld` schema with `tracker` table:
    ```sql
    CREATE TABLE IF NOT EXISTS tracker (
        tracker_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        source_url TEXT,
        organization TEXT,
        status TEXT NOT NULL,
        deadline TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    ```

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `RadarClueCollector` (`backend/src/probation/packs/radar/clues.py`):
    - **Why it is called:** Collects structured clues from opportunity candidates.
    - **How it is called & callers:** Called by `Ingestor` for opportunity items.
  ```python
  class RadarClueCollector:
      def collect(self, world: WorldView, item_id: str) -> ClueSet:
          ...
  ```
  * `RadarOutOfBandVerifier` (`backend/src/probation/packs/radar/out_of_band.py`):
    - **Why it is called:** Evaluates sponsor legitimacy and sets web safety veto.
    - **How it is called & callers:** Called during clue collection and vetting.
  ```python
  class RadarOutOfBandVerifier:
      def verify_sponsor(self, domain: str) -> OutOfBandResult:
          ...
  ```
  * `RadarExecutor` (`backend/src/probation/packs/radar/executor.py`):
    - **Why it is called:** Manages tracker items in `SimWorld`.
    - **How it is called & callers:** Called by `ExecutorWorker` for radar actions.
  ```python
  class RadarExecutor:
      def execute(self, io: ExecutorIO, action: Action) -> ExecutionResult:
          ...
  ```
  * `RadarResolver` (`backend/src/probation/packs/radar/resolver.py`):
    - **Why it is called:** Resolves proposal actions against user tracker history.
    - **How it is called & callers:** Called during replay and evaluation.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_links_radar_reading.py` (T-RADAR tests: clue extraction, out-of-band domain vetting, conditional fee cap 1, executor CRUD on tracker).
  - `backend/tests/unit/test_pack_conformance.py` (Conformance to Pack protocol under family `opportunity_triage`).
* **Manually verified:**
  - Verified that opportunity with fee requirement drops autonomy cap to 1.

## 6. Dependencies & Deferred Work
* **Depends on:** `probation.links`, `probation.web`, `probation.packs.base`.
* **Known issues/deferred:** None.


## WP1 final verified checkpoint - 22 October 2026

### 1. Overview
Radar descriptor and schema integration. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5.

### 2. Technical rationale
Read/decision paths defer executable modules and use shared strict schemas and scoped time. This does not establish complete Radar connector behavior.

### 3. Database schema impact
No persistent schema migration or new dependency; historical ledger bytes retained.

### 4. Core logic and necessary functions
backend/src/probation/packs/radar/__init__.py, clues.py and resolver.py; llm/jobs.py: opportunity reader/extraction and digest models.
Why/how called: Read/decision paths defer executable modules and use shared strict schemas and scoped time. This does not establish complete Radar connector behavior.

### 5. Testing and verification
test_wp1_validation.py, test_wp1_execution_authority.py. Final isolated scripts/check.py passed 328 tests, Ruff lint/format, project mypy (130 modules) and strict core/engine mypy (24 modules). Source/snapshot fixture and published-result hashes unchanged.

### 6. Dependencies and remaining work
WP1 remains incomplete. See docs/reports/wp1-checkpoint-2026-10-22.md for exact gaps and CCR-F; this update supersedes earlier verification counts and any historical no-known-issues statement for this repair. No live provider call or contract amendment.
