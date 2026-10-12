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
