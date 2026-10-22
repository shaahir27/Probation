---
feature: "Project Scaffold and Development Infrastructure"
phase: "Phase 0 — Foundations and Spikes"
status: "Built"
---

# Feature: Project Scaffold and Development Infrastructure

## 1. Overview
* **Name:** Project Scaffold and Development Infrastructure
* **Phase:** Phase 0 — Foundations and Spikes
* **Purpose:** Establish the canonical repository layout, strict configuration schemas, core type contracts, SQLite WAL database connection and verbatim schema, dev tooling (ruff, mypy strict, pytest), and the React 18 dashboard shell.
* **Traces to:** `CONTRACT.md` sections 2-4; `TECH_STACK_AND_REPO.md` sections 1-4; `DATA_MODEL.md` section 1; `TEST_PLAN.md` (T-ID, T-CLOCK, T-LEDGER, T-HANDSOFF, T-GATE, T-REDACT, T-WEBQ).

## 2. Technical Rationale
* **How we achieved it:** 
  - Scaffolded the strict Python package structure under `backend/src/probation/` with clean module docstrings and explicit typing.
  - Implemented core mathematical, cryptographic, and safety primitives (`Clock`, `det_id`, `canonical_json`, `ledger_hash`, `is_hands_off`, `evaluate_gate`, `redact`, `validate_tavily_query`).
  - Configured `backend/pyproject.toml` with strict `ruff` lint/format settings and `mypy` strict overrides for `core/` and `engine/`.
  - Added verbatim DDL `db/schema.sql` and SQLite connection manager in WAL mode with foreign keys enforced.
  - Configured React 18 + Vite + TypeScript + Tailwind CSS dashboard shell in `frontend/`.
* **Alternatives considered:** Monolithic single-file backend; rejected to enforce the strict boundary rules between models, workers, and executors defined in `CONTRACT.md`.
* **Why we chose this path:** Clean separation of concerns allows parallel phase implementation across Lanes A, B, C, and D without boundary leaks.

## 3. Database Schema Impact
* **Changes made:** Applied `db/schema.sql` containing all 26 core tables (`meta`, `sources`, `raw_items`, `situations`, `features`, `llm_cache`, `proposals`, `outcomes`, `drafts`, `actions`, `user_responses`, `class_stats`, `licence_cache`, `exam_runs`, `exam_cases`, `drift_state`, `family_shift`, `habits`, `chains`, `ledger`, `exposure_log`, `web_facts`, `tavily_calls`, `extractions`, `quarantine_outputs`, `clock_state`) and append-only SQLite triggers on `ledger`.

## 4. Core Logic & Necessary Functions
* **List of functions & files:**
  * `Clock` (`backend/src/probation/core/clock.py`): Monotonic simulated replay and live timekeeper.
    - **Why it is called:** Invariant I-9 prohibits calling `datetime.now()` or `time.time()` directly. All timestamps originate from this clock.
    - **How it is called & callers:** Replay engine, ledger appending, situation creation, and audit logging invoke `clock.now()` or `clock.now_iso()`.
  ```python
  class Clock:
      def __init__(self, mode: ClockMode = ClockMode.REPLAY, initial_time: Optional[datetime] = None) -> None: ...
      def now(self) -> datetime: ...
      def now_iso(self) -> str: ...
      def advance_seconds(self, seconds: float) -> None: ...
  ```

  * `det_id` (`backend/src/probation/core/hashing.py`): Deterministic SHA-256 identifier calculation.
    - **Why it is called:** Ensures identical raw items and situations generate byte-identical primary keys without auto-increment collisions.
    - **How it is called & callers:** Called by ingestor and situation extraction functions across all domain packs.
  ```python
  def det_id(*parts: str) -> str: ...
  ```

  * `append_ledger` and `verify_ledger` (`backend/src/probation/db/ledger.py`): Hash-chained append-only audit trail.
    - **Why it is called:** Invariants I-7 and I-8 require tamper-evident tracking of all proposals, outcomes, licence shifts, and audit draws.
    - **How it is called & callers:** Invoked on every state transition by workers; verified via CLI `probation ledger verify`.
  ```python
  def append_ledger(conn: sqlite3.Connection, kind: str, ref_id: str, payload: Dict[str, Any] | str, created_at: str) -> int: ...
  def verify_ledger(conn: sqlite3.Connection) -> Tuple[bool, Optional[int]]: ...
  ```

  * `evaluate_gate` (`backend/src/probation/engine/gate.py`): Pure deterministic execution decision function.
    - **Why it is called:** Decides whether to `SHADOW`, `SUGGEST`, `HOLD_THEN_EXECUTE`, `EXECUTE_IMMEDIATELY`, or `ASK`.
    - **How it is called & callers:** Called by `workers/brain.py` when generating action proposals.
  ```python
  def evaluate_gate(budget_ok: bool, reader_ok: bool, deterministic_ok: bool, hands_off_reason: Optional[str], licence_level: int, cap: int, novel: bool, p_max: float, audit_holdout: bool = False) -> GateDecision: ...
  ```

  * `validate_tavily_query` (`backend/src/probation/web/query_guard.py`): Safety and privacy validation on outbound web search queries.
    - **Why it is called:** Invariant I-23 requires that personal names, email addresses, and private tokens never leave the host machine.
    - **How it is called & callers:** Called by `web/client.py` and `workers/webfacts.py` prior to invoking Tavily HTTP endpoints.
  ```python
  def validate_tavily_query(query: str, user_name_tokens: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]: ...
  ```

## 5. Testing & Verification
* **Automated tests:** `backend/tests/unit/test_scaffold.py` covering:
  - `test_clock_monotonic_and_settable` (T-CLOCK)
  - `test_det_id_deterministic` (T-ID)
  - `test_canonical_json_key_invariance` (T-LEDGER)
  - `test_schema_initialization_and_ledger_integrity` (T-LEDGER)
  - `test_hands_off_safety` (T-HANDSOFF)
  - `test_pure_gate_fail_closed` (T-GATE)
  - `test_redact_pipeline` (T-REDACT)
  - `test_query_guard_rules` (T-WEBQ)
* **Manually verified:**
  - Ran `ruff check backend` (0 errors).
  - Ran `ruff format --check backend` (96 files formatted).
  - Ran `mypy --config-file backend/pyproject.toml backend/src/probation` (0 errors across 89 files).

## 6. Dependencies & Deferred Work
* **Depends on:** Python 3.11+ stdlib, Pydantic v2, Typer, Rich, SQLite3.
* **Known issues/deferred:**
  - Full statistical policy training (logistic regression) and empirical Bayes Beta pooling are stubbed for Phase 4 & Phase 5.
  - Live LLM HTTP schema parsing is stubbed for Phase 1.


## WP0 remediation - 22 October 2026

### 1. Overview
Updated development verification and CLI infrastructure under approved WP0. Traces to
CONTRACT I-18/I-19 and section 10, TEST_PLAN foundations, and CHANGES_IMPLEMENTATION_PLAN WP0.

### 2. Technical rationale
Use the existing Python environment and a standard-library check runner so Windows and
GNU make run the same gates. A fresh working-tree snapshot excludes environment files,
private directories and local logs. Publishing outputs remains an explicit operation.
Alternative: running pytest in the source checkout was rejected because the old CLI test
rewrote published results and configuration automatically loads a local environment file.

### 3. Database schema impact
None. Existing generated fixture databases and published numerical artifacts are unchanged.

### 4. Core logic and necessary functions
- scripts/check.py: main() -> int runs Ruff, configured mypy, explicit strict core/engine
  mypy and non-live pytest. Called by Makefile check/test and make.cmd check/test.
- scripts/check.py: snapshot(workspace: Path) -> None copies only public working files;
  protected_hashes(root: Path) -> dict[str, str] checks source/snapshot fixture/result
  integrity around pytest. Test subprocess keys and private path overrides are removed.
- backend/src/probation/cli_safety.py: synthesis_target(*, persona_id: int, size: str,
  out: str, overwrite: bool, regenerate_fixture: bool) -> Path validates output before
  generation. import_source(path: str | None, source: str | None) -> str rejects ambiguous
  or missing inputs. Both are called by the CLI handlers.
- backend/src/probation/cli.py: synth_generate defaults to data/synth/<persona>;
  import_mail_cmd/import_calendar_cmd/import_files_cmd/import_links_cmd accept --source;
  serve(host, port, reload) invokes the existing FastAPI app through Uvicorn.
- backend/src/probation/cli_apps.py owns registration groups; cli_engine.py contains the
  existing exam/backtest commands; cli_eval.py owns evaluation/export/report commands;
  cli_extra.py owns existing webfacts/habit/chain commands. cli.py imports these groups
  and retains the entry point. Each CLI module is below 400 lines.
- backend/pyproject.toml enables the complete applicable strict flag set for core/engine;
  the portable gate also invokes mypy --strict explicitly.

### 5. Testing and verification
Seven CLI safety regressions failed against the baseline before repair. The first complete
portable run passed Ruff lint/format, project mypy (119 modules), strict mypy (21 core/engine
modules), and 207 tests with two existing Typer deprecation warnings. Source and snapshot
fixture/result hashes matched. Final command-form verification is recorded in the WP0 handoff.
No live calls, installations or credential access occurred. Graphify AST update succeeded;
its optional SQL parser is absent and no dependency was installed to alter that environment.

### 6. Dependencies and deferred work
No new dependency. Existing historical metrics/spike claims are qualified in PROVENANCE.md
and decision log; corrected experiments belong to later WPs. The 43 tracked build logs are
inventoried for later reviewed untracking; only future local log files are ignored now.
