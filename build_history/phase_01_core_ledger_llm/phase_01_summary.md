# Phase 1 Summary: Core, Database, Ledger, LLM Client, and Redaction

**Status:** Completed  
**Branch:** `phase-1-core-db-ledger`  
**Date:** 2026-10-10  

---

## 1. High-Level Summary
Phase 1 established the trusted foundation of the Probation engine (Lane A):
1. **Domain Data Models**: Defined complete Pydantic v2 domain models in `core/types.py` adhering to `CONTRACT.md` section 4 and `DATA_MODEL.md`.
2. **Cryptographic Ledger & Hashing**: Refactored `det_id` (32-char SHA-256), `canonical_json` (sorted keys, 6-decimal rounding, ISO-8601 UTC Z formatting), and `ledger_hash`. Verified that SQLite triggers abort direct `UPDATE` and `DELETE` on the `ledger` table.
3. **Temporal Isolation & Actor Boundaries**: Implemented `HistoryView(as_of=t)` prohibiting future data leakage (I-6). Built `RoleAccess` connection wrappers enforcing role-based table write boundaries (CONTRACT section 3).
4. **PII Redaction Engine**: Implemented full local deterministic regex pipeline in `llm/redact.py` with Luhn card verification, Aadhaar boundary checks, UPI differentiation, and quoted history/signature stripping (I-14).
5. **Resilient LLM Client**: Implemented `LLMClient` with exponential backoff on HTTP 429/5xx, `Retry-After` header parsing, JSON-schema structured output with fallback and 1 repair retry, deterministic SQLite caching (I-16), `BudgetGuard` hard cap enforcement ($20.00 USD), and exposure logging.
6. **CLI Operations**: Implemented CLI subcommands: `probation db init`, `probation ledger verify`, and `probation budget show`.
7. **Verification**:
   - `ruff check backend`: 0 errors.
   - `ruff format --check backend`: 101 files formatted.
   - `mypy --config-file backend/pyproject.toml backend/src/probation`: 0 errors across 89 source files.
   - `pytest -q backend/tests -m "not live"`: 36 passed tests in 0.51s.

---

## 2. Feature Logs in this Phase
- [`feature_core_types_ledger.md`](feature_core_types_ledger.md): Core Pydantic types, hashing, ledger integrity, role-based database access, and temporal history views.
- [`feature_redaction_llm_client.md`](feature_redaction_llm_client.md): Local PII redaction pipeline, resilient LLM client, budget guard, and deterministic caching.
