---
feature: "Ingestor Worker & Brain Featurization Pipeline"
phase: "Phase 3 — Mail and Calendar Packs"
status: "Built"
---

# Feature: Ingestor Worker & Brain Featurization Pipeline

## 1. Overview
* **Name:** Ingestor Worker & Brain Featurization Pipeline
* **Phase:** Phase 3 — Mail and Calendar Packs
* **Purpose:** Implements the worker processing pipeline to transform raw imported records (`raw_items`) into canonical `situations`, redact personal information, and compute deterministic and reader-derived features (`features`) under strict process write boundaries.
* **Traces to:** `CONTRACT.md` section 3 (Role write tables), `DATA_MODEL.md` section 1, `PROMPTS.md` sections 3-4, `TEST_PLAN.md` (T-ID).

## 2. Technical Rationale
* **How we achieved it:** Built `ingest_situations` in `workers/ingestor.py` utilizing `RoleAccess(conn, Role.INGESTOR)` to insert `situations`. Built `extract_features_for_situations` in `workers/brain.py` utilizing `RoleAccess(conn, Role.BRAIN)` to compute deterministic clues via `HistoryView` and reader fields via `StubReader` or LLM client. Features are hashed using canonical JSON for exact determinism.
* **Alternatives considered:** Writing directly without `RoleAccess`. Rejected: violates Invariant I-10 and role boundary enforcement.
* **Why we chose this path:** Clean separation of concerns ensuring that ingestor, brain, resolver, and executor operate in independent security sandboxes.

## 3. Database Schema Impact
* **Changes made:** None to DDL (populates existing `situations` and `features` tables).

## 4. Core Logic & Necessary Functions
* `ingest_situations` (`backend/src/probation/workers/ingestor.py`): Ingests unparsed `raw_items` into `situations`.
* `extract_features_for_situations` (`backend/src/probation/workers/brain.py`): Featurizes situations into `features`.
* `StubReader` (`backend/tests/stubs/stub_reader.py`): Offline deterministic reader for zero-cost testing.
* `ingest_cmd` (`backend/src/probation/cli.py`): `probation ingest` command.

## 5. Testing & Verification
* **Automated tests:** `tests/unit/test_ingestor_and_features.py`.
* **Manually verified:** Verified 100% featurization on `tiny_synth` mailbox and calendar fixtures.

## 6. Dependencies & Deferred Work
* **Depends on:** `MailPack`, `CalendarPack`, `RoleAccess`.
* **Known issues/deferred:** None.


## WP1 final verified checkpoint - 22 October 2026

### 1. Overview
Worker transaction and clock propagation. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5.

### 2. Technical rationale
Composition roots commit work, not these helpers. Failure of later caller work can roll back helper writes. Worker time comes from the scoped context clock. Full WP2 resolver chronology remains outstanding.

### 3. Database schema impact
No persistent schema migration or new dependency; historical ledger bytes retained.

### 4. Core logic and necessary functions
backend/src/probation/workers/brain.py: extract_features_for_situations; workers/ingestor.py: ingest_situations; workers/resolver.py: resolve_outcomes.
Why/how called: Composition roots commit work, not these helpers. Failure of later caller work can roll back helper writes. Worker time comes from the scoped context clock. Full WP2 resolver chronology remains outstanding.

### 5. Testing and verification
test_wp1_transaction_owners.py, test_wp1_context.py. Final isolated scripts/check.py passed 328 tests, Ruff lint/format, project mypy (130 modules) and strict core/engine mypy (24 modules). Source/snapshot fixture and published-result hashes unchanged.

### 6. Dependencies and remaining work
WP1 remains incomplete. See docs/reports/wp1-checkpoint-2026-10-22.md for exact gaps and CCR-F; this update supersedes earlier verification counts and any historical no-known-issues statement for this repair. No live provider call or contract amendment.

## WP3/WP4 integration update - 2026-10-23

Shared compute_features now provides required-reader validity and semantic provenance; stale features cannot silently authorize predictions.

Exact interfaces, callers and verification: docs/reports/wp3-wp4-integration-2026-10-23.md and the P06-P11 feature records. Final suite: 585 passed; no fixture/result mutation. This updates this component, not full phase completion. Accounting/single-flight remain blocked by W3-D03/W3-D04.
