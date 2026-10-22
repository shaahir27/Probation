# Phase 1 Handoff: Core, Database, Ledger, LLM Client, and Redaction

> Historical report. The later WP1 remediation checkpoint and its outstanding role
> requirement are in [wp1-checkpoint-2026-10-22.md](wp1-checkpoint-2026-10-22.md).
> This historical phase report does not establish completion of WP1 remediation.

> Final WP1 remediation handoff after the user's CCR-F approval:
> [wp1-closure-2026-10-22.md](wp1-closure-2026-10-22.md).

**Branch:** `phase-1-core-db-ledger`  
**Phase:** 1 — Core, Database, Ledger, LLM Client, Redaction  

---

## Done
1. **Domain Data Models & Enums**: Defined complete, binding Pydantic v2 schemas in `backend/src/probation/core/types.py` (`Situation`, `Features`, `Proposal`, `Outcome`, `Action`, `LicenceView`, `UserResponse`, `LedgerEntry`, `ExposureRecord`, `RawItem`, `Source`, `RedactionResult`) and aligned `backend/src/probation/core/enums.py` (`GateDecision`, `ActionStatus`, `EvidenceStrength`, `LedgerKind`, `UserResponseKind`, `LicenceLevel`).
2. **Cryptographic Ledger & Deterministic Utilities**: Implemented `det_id` (32-character SHA-256 slice), `canonical_json` (sorted keys, 6-decimal float rounding, ISO-8601 UTC Z formatting), and `ledger_hash` matching `DATA_MODEL.md` sections 2 and 4. Enforced append-only immutability via SQLite triggers aborting `UPDATE` and `DELETE`.
3. **Temporal Isolation & Actor Boundaries**: Implemented `HistoryView(as_of=t)` in `core/history.py` prohibiting future data leakage (invariant I-6). Built `RoleAccess` connection wrappers in `db/access.py` strictly enforcing role-based table write boundaries (CONTRACT section 3).
4. **PII Redaction Pipeline**: Implemented multi-stage regex pipeline in `llm/redact.py` with quoted history and signature stripping, Luhn checksum card validation, Aadhaar boundary checks, UPI vs email differentiation, URL classification, and numbered `<TYPE_n>` placeholder mappings with strictly local restore maps (invariant I-14).
5. **Resilient LLM Client**: Built `LLMClient` with exponential backoff on HTTP 429/5xx, `Retry-After` header parsing, OpenAI-compatible JSON-schema structured output with automatic fallback to JSON-only mode and exactly 1 repair retry, deterministic SQLite caching (invariant I-16), `BudgetGuard` hard cap enforcement ($20.00 USD; invariant I-15), and `exposure_log` auditing.
6. **CLI Subcommands**: Implemented `probation db init`, `probation ledger verify`, and `probation budget show` in `backend/src/probation/cli.py`.
7. **Build Logging**: Generated comprehensive build history logs in `build_history/phase_01_core_ledger_llm/` and updated `build_history/index.md`.

---

## Files Changed / Created
- `backend/src/probation/core/enums.py` (updated)
- `backend/src/probation/core/types.py` (updated)
- `backend/src/probation/core/hashing.py` (updated)
- `backend/src/probation/core/history.py` (updated)
- `backend/src/probation/db/ledger.py` (updated)
- `backend/src/probation/db/access.py` (updated)
- `backend/src/probation/llm/budget.py` (updated)
- `backend/src/probation/llm/client.py` (updated)
- `backend/src/probation/llm/redact.py` (updated)
- `backend/src/probation/cli.py` (updated)
- `backend/tests/unit/test_scaffold.py` (updated)
- `backend/tests/unit/test_hashing_and_id.py` (new)
- `backend/tests/unit/test_ledger_integrity.py` (new)
- `backend/tests/unit/test_redaction_pipeline.py` (new)
- `backend/tests/unit/test_llm_client_and_budget.py` (new)
- `backend/tests/unit/test_security_boundaries.py` (new)
- `build_history/phase_01_core_ledger_llm/feature_core_types_ledger.md` (new)
- `build_history/phase_01_core_ledger_llm/feature_redaction_llm_client.md` (new)
- `build_history/phase_01_core_ledger_llm/phase_01_summary.md` (new)
- `build_history/index.md` (updated)
- `docs/reports/phase-1.md` (new)

---

## Tests
- `.\make.cmd check`:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (101 files already formatted).
  - `mypy --config-file backend/pyproject.toml backend/src/probation`: Passed (0 errors across 89 source files).
  - `pytest -q backend/tests -m "not live"`: 36 passed in 0.51s.
- **Contract Tests Satisfied**:
  - `T-ID`: Deterministic 32-character ID generation and stability across repeated calls.
  - `T-CLOCK`: Monotonic replay clock, prohibits backward movement, and AST check verifies zero wall-clock calls in engine/core.
  - `T-LEDGER`: 1,000-row append, tamper detection at sequence level, SQLite trigger aborts on update/delete, canonical JSON key invariance and float/datetime normalization.
  - `T-REDACT`: Comprehensive positive and negative fixtures across all 10 PII patterns, Luhn check, UPI vs email differentiation, Aadhaar sequence boundary checks, and restore map isolation.
  - `T-LLM`: Exponential backoff retries on 429/500, `Retry-After` handling, JSON-schema rejection fallback, 1 repair retry, cache hit avoiding HTTP calls, `BudgetExceeded` fail-closed, and exposure logging.
  - `T-SEC (partial)`: Role-based table write access checks preventing unauthorized process writes.

---

## Invariants Touched
- **I-1 (LLM output is data only)**: Validated against strict schemas and Pydantic types.
- **I-3 (Fail closed)**: Budget exhaustion, invalid schemas, and repair exhaustion raise typed exceptions that fail closed to `ASK`.
- **I-6 (No peeking)**: `HistoryView(as_of=t)` encapsulates queries and strictly filters records by `known_at <= as_of` or `occurred_at <= as_of`.
- **I-7, I-8 (Tamper-evident ledger)**: SQLite triggers block update/delete, hash chain verified.
- **I-9 (Clock)**: AST scan confirms no unapproved wall-clock calls exist in engine/core.
- **I-14 (Redaction before egress)**: Local regex pipeline strips quoted text, signatures, and PII before transmission.
- **I-15 (Budget guard)**: Pre-flight cost checks raise `BudgetExceeded`.
- **I-16 (Deterministic caching)**: Cache key `(content_hash, prompt_id, prompt_version, model_id)` ensures identical prompts make 0 network calls.

---

## Deviations and Assumptions
- None. All implementations adhere strictly to the contracts and specifications.

---

## Contract Change Requests
- None.

---

## New Dependencies
- None. All implementations utilize previously installed dependencies (`pydantic`, `httpx`, `rich`, `typer`, `pytest`).

---

## LLM Cost Incurred
- $0.00 USD (All automated tests use deterministic mock transports; real API calls are reserved for manual smoke testing).

---

## Open Questions
- None.

---

## Suggested Next Step
- Phase 1 is complete and verified. Await human review and merge into `main` at Merge Point 1 (alongside Member 2's Phase 2), then proceed to **Phase 3: Mail and calendar packs**.
