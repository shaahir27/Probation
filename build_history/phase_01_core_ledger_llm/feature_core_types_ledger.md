---
feature: "Core Types and Hash-Chained Ledger"
phase: "Phase 1 — Core, Database, Ledger, LLM Client, Redaction"
status: "Built"
---

# Feature: Core Types and Hash-Chained Ledger

## 1. Overview
* **Name:** Core Types and Hash-Chained Ledger
* **Phase:** Phase 1 — Core, Database, Ledger, LLM Client, Redaction
* **Purpose:** Implements binding Pydantic v2 domain models, temporal isolation (`HistoryView`), cryptographic hashing utilities (`det_id`, `canonical_json`, `ledger_hash`), role-based database access boundaries (`db/access.py`), and the append-only SQLite ledger with triggers.
* **Traces to:** `CONTRACT.md` sections 2, 3, 4 (invariants I-6, I-7, I-8, I-9), `DATA_MODEL.md` sections 1, 2, 4.

## 2. Technical Rationale
* **How we achieved it:** Implemented immutable Pydantic v2 models matching the data contract. Developed deterministic ID generation using SHA-256 with unit separator slicing (`[:32]`). Built canonical JSON serializer enforcing sorted keys, 6-decimal float rounding, and ISO-8601 UTC Z formatting. Ledger hashing chains the previous SHA-256 hash across sequence rows with SQLite triggers aborting any `UPDATE` or `DELETE` attempt. Implemented `RoleAccess` connection wrapper restricting table write access per worker role.
* **Alternatives considered:** None. The specification strictly dictated SQLite WAL mode and hash-chain structure.
* **Why we chose this path:** Adheres to the core contract and provides mathematical, tamper-evident proof of system decisions.

## 3. Database Schema Impact
* **Changes made:** Applied verbatim 26-table DDL (`db/schema.sql`) including triggers `ledger_no_update` and `ledger_no_delete`.

## 4. Core Logic & Necessary Functions
* `Situation`, `Proposal`, `Outcome`, `Action`, `LicenceView` (`backend/src/probation/core/types.py`): Binding domain representations for engine decisions and lifecycle tracking.
  - **Why it is called:** Used across all worker and engine modules as structured data containers.
  - **How it is called & callers:** Instantiated by packs, engine, and database access layers.
* `det_id` (`backend/src/probation/core/hashing.py`): Computes 32-char SHA-256 deterministic ID.
  - **Why it is called:** Ensures idempotency across repeated source imports and replay steps.
  - **How it is called & callers:** Called by packs, ingestors, and resolvers.
* `canonical_json` (`backend/src/probation/core/hashing.py`): Deterministic JSON serialization.
  - **Why it is called:** Provides stable material for hashing regardless of dictionary key ordering or float precision noise.
  - **How it is called & callers:** Called by ledger append and hash calculation.
* `append_ledger`, `verify_ledger` (`backend/src/probation/db/ledger.py`): Hash-chained ledger append and integrity audit.
  - **Why it is called:** Records immutable timeline of proposals, outcomes, actions, and licence events.
  - **How it is called & callers:** Called by brain, resolver, executor, examiner, and CLI `ledger verify`.
* `RoleAccess` (`backend/src/probation/db/access.py`): Role-based database write boundary enforcer.
  - **Why it is called:** Prevents unauthorized workers from modifying restricted database tables (CONTRACT section 3).
  - **How it is called & callers:** Instantiated via `get_role_access(conn, role)` before performing writes.

```python
def append_ledger(
    conn: sqlite3.Connection,
    kind: str,
    ref_id: str,
    payload: dict[str, Any] | str,
    created_at: str,
) -> int: ...

def verify_ledger(conn: sqlite3.Connection) -> tuple[bool, int | None]: ...
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_hashing_and_id.py` (`T-ID`, `T-LEDGER`)
  - `backend/tests/unit/test_ledger_integrity.py` (`T-LEDGER`: 1000-row append, tamper detection, trigger aborts)
  - `backend/tests/unit/test_security_boundaries.py` (`T-CLOCK`, `T-SEC`: Role access boundaries)
* **Manually verified:** Ran `python -m probation.cli db init` and `python -m probation.cli ledger verify`.

## 6. Dependencies & Deferred Work
* **Depends on:** `core/enums.py`, `core/clock.py`.
* **Known issues/deferred:** None.


## WP1 repair update - 22 October 2026

### 1. Overview
Ledger, roles and UTC clock foundation. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5; CONTRACT remains unchanged.

### 2. Technical rationale
Replay, proposal persistence and other role repositories append without committing their parent; API/CLI consume one ledger snapshot. Entry points scope a single clock; history comparisons use UTC instants. This fixes transaction escape, head allocation, corrupt-head reporting, precision loss and backwards-time handling.

### 3. Database schema impact
No persistent schema/ledger-byte migration or new dependency.

### 4. Core logic and necessary functions
backend/src/probation/db/ledger.py: append_ledger(conn, kind, ref_id, payload, created_at) -> int; ledger_snapshot(conn) -> LedgerSnapshot. backend/src/probation/db/access.py: RoleAccess.transaction() and execute_write(table, query, params). backend/src/probation/db/guards.py: statement_guard and read-only capabilities. backend/src/probation/core/clock.py: get_clock(), use_clock(clock), parse_timestamp/format_timestamp and UTC_TIMESTAMP collation.
Why/how called: Replay, proposal persistence and other role repositories append without committing their parent; API/CLI consume one ledger snapshot. Entry points scope a single clock; history comparisons use UTC instants. This fixes transaction escape, head allocation, corrupt-head reporting, precision loss and backwards-time handling.

### 5. Testing and verification
test_wp1_storage.py; test_wp1_ledger_views.py; test_wp1_clock.py; test_wp1_time_boundaries.py (T-LEDGER/T-SEC/T-CLOCK/T-ID).
An earlier isolated full checkpoint passed 291 tests plus lint/types; later targeted results are recorded in docs/reports/wp1-progress-2026-10-22.md. Final checks remain required after all edits.

### 6. Dependencies and remaining work
WP0 committed c92131c; WP1 is in progress. See the progress report for open role/transaction, canonical-payload, clock/identity and handoff requirements. This update is not a WP1 completion claim or live-provider proof.


## WP1 final verified checkpoint - 22 October 2026

### 1. Overview
Durable action and typed chain storage. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5.

### 2. Technical rationale
Executor calls persist_action before effects; chain proposer uses the restricted insertion helper. Savepoints preserve caller rollback, immutable retries preserve completed actions. SQL authorizers guard actual targets, including triggers.

### 3. Database schema impact
No persistent schema migration or new dependency; historical ledger bytes retained.

### 4. Core logic and necessary functions
backend/src/probation/db/actions.py: persist_action; db/access.py: insert_chain_situation; db/proposals.py: persist_proposal.
Why/how called: Executor calls persist_action before effects; chain proposer uses the restricted insertion helper. Savepoints preserve caller rollback, immutable retries preserve completed actions. SQL authorizers guard actual targets, including triggers.

### 5. Testing and verification
test_wp1_action_storage.py, test_wp1_chain_storage.py, test_wp1_storage.py. Final isolated scripts/check.py passed 328 tests, Ruff lint/format, project mypy (130 modules) and strict core/engine mypy (24 modules). Source/snapshot fixture and published-result hashes unchanged.

### 6. Dependencies and remaining work
WP1 remains incomplete. See docs/reports/wp1-checkpoint-2026-10-22.md for exact gaps and CCR-F; this update supersedes earlier verification counts and any historical no-known-issues statement for this repair. No live provider call or contract amendment.
