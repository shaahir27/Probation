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
