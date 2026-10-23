# Phase 3 Handoff: Reader & Writer LLM Pipeline (WP3)

**Branch:** `phase-3-wp3-reader-pipeline`  
**Phase:** 3 — Mail, Calendar, and LLM Reader/Writer Pipeline (WP3)  
**Commits:**
- `2db263d`: `phase-3: reader pipeline, strict requirements, header conflict enforcement, and provenance persistence` (P06/P07)
- `69832fc`: `phase-3: reply writer, draft validation, consumers migration, and executor hydration` (P08–P10)

---

## 1. Done

1. **Reader Requirement Single Source of Truth (P06 #1)**:
   - `reader_required(pack)` in `backend/src/probation/llm/reader.py` is the only authority the gate reads. `reader_spec() is None` alone is not the contract: `READER_READINESS` names the packs whose required read is not a reader job, and an unregistered pack fails closed instead of skipping the read.
   - `reading` (external quarantine readiness) and `chains` (inherited trigger context) are therefore `required=True`. Absent their evidence they return `ReaderStatus.FAILED` with `FailureCode.CLUES_INVALID` and reason `quarantine_unavailable` / `inherited_unavailable`; supplied evidence returns `VALIDATED` carrying exactly those fields. Neither absence is reported as `OPTIONAL_DISABLED`/`ok=True` (W3-T03).
   - `files` remains the only optional-disabled case, and only while `files_reader_enabled` is false.
   - `packs/chains/proposer.py` no longer hardcodes `reader_required=False, reader_ok=True`; it passes the reader authority and `reader_ok=bool(reader_features)`, adding reason `inherited_unavailable` when the trigger's validated form was not supplied.
   - `engine/prediction.py` reads `__reader_required` from the feature row with a fail-closed default of `True` and no longer re-derives it from `pack.reader_spec()`; it also no longer imports `llm.catalog`/`llm.reader`, keeping the pure seam pure. Strict form validation stays in the reader seam, which every live, cached and injected path passes through.

2. **Authoritative Header Conflict Enforcement (P06 #4)**:
   - Implemented real mail header consistency check in `read_situation`: validates `data["looks_automated"] == (clues["sender_tier"] == "automated")`.
   - On mismatch, emits `ReaderOutcome.failed` with `FailureCode.HEADER_CONFLICT` and `reason="reader_header_conflict"`.
   - In `feature_pipeline.py`, a header conflict is a reader-side fact: it clears `reader_ok` and sets `__reader_failure_reason = "reader_header_conflict"`, and the contradicted form is dropped rather than stored as a validated read. It does not mark `__deterministic_ok = False`, because the deterministic clues were sound; misattributing the failure would hide which input actually failed.
   - In `engine/prediction.py`, `evaluate_prediction` appends `__reader_failure_reason` and gates to `ASK`.
   - Scope note (W3-D02): the implemented check is the single authoritative comparison between the deterministic `sender_tier` clue and the form's `looks_automated`. It is not yet the "deterministic, reviewed set of checks" P06 #4 describes; no speculative header heuristic is used to infer semantic intent.

3. **Features Provenance Persistence & Migration (P06 #5/#6)**:
   - Added `provenance_json TEXT CHECK (provenance_json IS NULL OR json_valid(provenance_json))` to `CREATE TABLE features` in `schema.sql`.
   - Documented the column in `docs/DATA_MODEL.md`.
   - Added additive schema migration `migrate_features_provenance` in `migrations.py` and hooked into `connection.py` schema initialization.
   - Attached event cutoff (`situation.occurred_at`), template hash, schema fingerprint, transport, and redaction counts into `provenance_json`.
   - In `replay.py`, a stored row is reused only when its provenance cutoff **equals** the situation's `occurred_at`. The earlier `cutoff <= occurred_at` test accepted an earlier cutoff, which counted fewer outcomes and so proved nothing about this row; a row with absent or unparsable provenance is now also refused. Consequence: feature rows written before `provenance_json` existed are not reusable and fall closed to `ASK` until re-featurized, which is the intended fail-closed behaviour and does not mutate them.

4. **Catalog and Pack Version Alignment**:
   - Aligned `mail_pack.reader_spec().prompt_version` to `"v3"` matching `READER_JOBS[("reader.mail", "v3")]`.
   - Aligned `calendar_pack.reader_spec().prompt_version` to `"v2"` matching `READER_JOBS[("reader.invite", "v2")]`.
   - Aligned `radar_pack.reader_spec().redaction_profile` to `"mail"`.

5. **Fail-Closed Context Validation (P06 #5)**:
   - Eliminated silent fallback defaults (`"other"`, `0`, `"unknown"`) in `reader.py`.
   - Mandatory context clues (`sender_domain_class` for mail; `organizer_domain_class`, `duration_min`, `start_hour_bucket` for calendar) are strictly validated before reader dispatch.
   - Missing clues return `ReaderOutcome.failed` with `FailureCode.CLUES_INVALID` and specific reasons (`"missing_mail_context"` / `"missing_calendar_context"`).

6. **Worker Hygiene and Bounded Extraction**:
   - Hoisted per-row internal imports to top-level in `workers/brain.py`.
   - Added `until: str | None = None` parameter to `extract_features_for_situations` with bounded SQL filter `AND s.occurred_at <= ?` to eliminate future materialization via CLI/worker paths.

7. **Reply Writer & Draft Persistence (P08–P10)**:
   - Implemented bounded reply writer in `llm/writer.py` with style example extraction (`reply_examples.py`), draft schema validation (`draft_validation.py`), and atomic storage (`draft_persistence.py`).
   - Wired `persist_proposal(..., draft=)` in `db/proposals.py` and Executor draft hydration in `workers/executor.py`.

8. **Unified Registered Consumers Migration (P09)**:
   - Replaced ad-hoc LLM calls with `RegisteredConsumer` across exam operators, resolvers, habit mining wording, radar digest, links quarantine extractor, synthetic data jobs, and evaluation baselines.

---

## 2. Files Changed / Created

### New Files Created
- `backend/src/probation/llm/reader.py`: Strict reader seam with header conflict enforcement and clue validation.
- `backend/src/probation/llm/feature_pipeline.py`: Bounded feature extraction adapter and semantic version digest.
- `backend/src/probation/engine/prediction.py`: Pure prediction evaluation and reason assembly.
- `backend/src/probation/engine/exam_prediction.py`: Counterfactual prediction evaluation.
- `backend/src/probation/workers/prediction.py`: Role-level composition for live ticks.
- `backend/src/probation/llm/writer.py`: Prompted reply writer with strict schema validation.
- `backend/src/probation/llm/draft_validation.py`: Draft recipient, length, and content constraints.
- `backend/src/probation/llm/reply_examples.py`: Historical style examples bounded by HistoryView.
- `backend/src/probation/llm/consumers.py`: Registered typed LLM consumers.
- `backend/src/probation/llm/draft_persistence.py`: Draft persistence and verification.
- `backend/src/probation/db/reply_payload.py`: Reply payload data structures.
- `backend/src/probation/links/extractor_jobs.py`: Quarantined link extraction consumer.
- `backend/src/probation/synth/llm_jobs.py`: Synthetic generator LLM jobs.
- `backend/tests/unit/test_wp3_reader_prediction.py`: 12 regression tests for reader requirements, header conflict, provenance, and clue validation.
- `backend/tests/unit/test_wp3_writer_component.py`: Writer and draft persistence tests.
- `backend/tests/unit/test_wp3_consumer_migration.py`: Consumer migration tests across packs.

### Modified Files
- `backend/src/probation/core/types.py`: Added `provenance_json` to `Features`.
- `backend/src/probation/db/schema.sql`: Added `provenance_json` column to `features` table DDL.
- `backend/src/probation/db/migrations.py`: Added `migrate_features_provenance` migration.
- `backend/src/probation/db/connection.py`: Integrated provenance migration in schema application.
- `backend/src/probation/db/proposals.py`: Added draft parameter to proposal persistence.
- `backend/src/probation/engine/replay.py`: Added cutoff validation and stale featurizer rejection.
- `backend/src/probation/engine/habits.py`: Migrated wording to RegisteredConsumer.
- `backend/src/probation/engine/exam.py`: Migrated exam generation to RegisteredConsumer.
- `backend/src/probation/eval/baselines.py`: Migrated baselines to RegisteredConsumer.
- `backend/src/probation/llm/results.py`: Added reason property alias on `ReaderOutcome`.
- `backend/src/probation/llm/gateway.py`: Updated error mappings and transport authority.
- `backend/src/probation/packs/mail/__init__.py`: Aligned prompt_version to "v3".
- `backend/src/probation/packs/mail/exam_ops.py`: Migrated to RegisteredConsumer.
- `backend/src/probation/packs/mail/resolver.py`: Migrated to RegisteredConsumer.
- `backend/src/probation/packs/calendar/__init__.py`: Aligned prompt_version to "v2".
- `backend/src/probation/packs/calendar/exam_ops.py`: Migrated to RegisteredConsumer.
- `backend/src/probation/packs/calendar/resolver.py`: Migrated to RegisteredConsumer.
- `backend/src/probation/packs/radar/__init__.py`: Aligned redaction_profile to "mail".
- `backend/src/probation/packs/radar/digest.py`: Migrated to RegisteredConsumer.
- `backend/src/probation/packs/radar/out_of_band.py`: Migrated to RegisteredConsumer.
- `backend/src/probation/workers/brain.py`: Hoisted imports, rewired to compute_features, added bounded until query.
- `backend/src/probation/workers/executor.py`: Implemented draft hydration.
- `docs/DATA_MODEL.md`: Documented `provenance_json` on `features` table.

---

## 3. Tests

- **Command Run**: `python scripts/check.py`
- **Result**:
  - `ruff check backend scripts/check.py`: Passed (0 errors).
  - `ruff format --check backend scripts/check.py`: Passed (261 files already formatted).
  - `mypy --config-file backend/pyproject.toml backend/src/probation`: Passed (0 issues across 164 source files).
  - `mypy --strict --config-file backend/pyproject.toml backend/src/probation/core backend/src/probation/engine`: Passed (0 issues across 34 source files).
  - `pytest -q -c backend/pyproject.toml backend/tests -m "not live"`: **591 passed**, 2 warnings in 107.65s (ruff lint/format clean; mypy 0 issues over 164 source files and 0 over the 34 strict core/engine files; fixture/result hashes unchanged).
  - Fixture and result hashes: Verified unchanged.
- **Contract Test IDs Satisfied**:
  - `T-LLM`: Registered catalog resolution, schema validation, and typed failures pass.
  - `T-REDACT`: Bounded request context and redaction before LLM egress pass.
  - `T-NOPEEK`: HistoryView cutoff enforcement and replay cutoff checks pass.
  - `T-GATE`: Header conflict, clue absence, and missing reader fail closed to `ASK`.
  - `T-PACK`: Conformance and reader specifications pass for all packs.
  - `T-RESOLVE`: Priority order and observation window cutoffs verified.
  - `T-LEDGER`: Hash-chained append-only ledger untouched; proposal/draft persistence verified.

---

## 4. Invariants Touched

- **I-1 (LLM output is data only)**: Every reader and writer response is schema-validated before entering features or drafts.
- **I-2 (Executor authority)**: Only the Executor performs side-effects; writer drafts require Executor hydration.
- **I-6 (Temporal Isolation / No peeking)**: HistoryView(as_of=t) bounds all feature extraction and style example queries; `extract_features_for_situations(until=...)` bounds its situation query with `occurred_at COLLATE UTC_TIMESTAMP <= ?` like every other timestamp comparison in the codebase; replay reuses a stored feature row only when its provenance cutoff equals the situation's `occurred_at`.
- **I-7 (Fail closed)**: Missing reader, header conflict, or missing mandatory clues immediately yield `ASK`.
- **I-10 (Role write boundaries)**: Brain worker writes strictly to `features` and `proposals`.
- **I-14 (Redaction before egress)**: Message text and names are redacted via approved profiles before transport dispatch.
- **I-16 (Ledger immutability)**: The ledger remains append-only and hash-chained; additive schema change on `features` avoids any ledger modifications.

---

## 5. Deviations and Assumptions

- **W3-D03 (Durable spend accounting / failed attempt exposure)**: Kept marked as deferred per WP3 plan; full physical reservation storage requires the multi-process supervisor scheduled for Phase 12.
- **W3-D04 (Cross-worker single flight)**: Single-flight concurrency locking across separate worker processes is deferred to Phase 12 runtime supervision.

---

## 6. Contract Change Requests (CCRs)

### CCR-001: Additive `features.provenance_json` Column
- **Document Affected**: `docs/DATA_MODEL.md` (and SQLite `features` table).
- **Proposal**: Add nullable `provenance_json TEXT CHECK (provenance_json IS NULL OR json_valid(provenance_json))` to `features`.
- **Rationale**: Durable storage of template hash, schema fingerprint, model ID, transport mode, redaction counts, and the event-time cutoff is required to verify counterfactual reproducibility and prevent feature reuse across temporal horizons without mutating the immutable hash-chained ledger.
- **Contract Impact**: Invariant I-16 is strictly preserved; no ledger schema or transaction logic is modified.

### CCR-002: Formal Sign-off on Context Limits and Role Max Tokens (W3-D07)
- **Document Affected**: `docs/ENGINE_SPEC.md` and `docs/PACKS_SPEC.md`.
- **Limits** (as implemented; `llm/context.py` and `llm/catalog.py:_ROLE_MAX_TOKENS`):
  - `FILE_SNIPPET_MAX_CHARS`: 600 characters.
  - `MAX_REPLY_EXAMPLES`: 3 examples.
  - Per-role max output tokens: `READER`: 200, `WRITER`: 400, `WORDING`: 120, `EXAM_EDIT`: 500, `SYNTH`: 800, `QUARANTINE`: 500, `BASELINE`: 200. There is no `DIGEST` or `HABIT` model role; `docs/PROMPTS.md` section 2 names exactly the seven roles above.
- **Rationale**: Bounding request sizes guarantees that LLM egress stays strictly within token budget guards and prevents context overflow. Sign-off is requested on the values the code already enforces, not on new ones.

---

## 7. New Dependencies

- **For Phase 3 (WP3)**: None. All components use standard library, Pydantic, and existing SQLite/Pytest tooling.
- **Scope Item for User Review (WP4 Artifacts)**:
  - WP4 exploration brought an uncommitted 88 MB MiniLM model into `data/` and several uncommitted files (`core/history_wp4.py`, `history_statistics.py`, `training_labels.py`, `engine/{training,calibration,vocabulary}.py`, `local_embeddings.py`).
  - These files are kept completely uncommitted and separate from Phase 3 commits `2db263d` and `69832fc`.

---

## 8. LLM Cost Incurred

- **$0.00 USD**: All automated tests execute offline using deterministic test doubles, synthetic fixtures, and registered stub consumers.

---

## 9. Open Questions

1. **WP4 Branch Segregation**: Confirm that WP4 files and the downloaded MiniLM model should be branched into `phase-4-wp4-embeddings` rather than committed to the Phase 3 pipeline.

---

## 10. Suggested Next Step

- Obtain human sign-off on CCR-001, CCR-002, and the WP4 scope decision.
- Proceed to Phase 4 policy, calibration, and backtest implementation on branch `phase-4-engine-backtest`.
