---
feature: "Data Importers and SimWorld Renderers"
phase: "Phase 2 — Synthetic World, Personas, Habits DSL, Generator, Renderers, Importers"
status: "Built"
---

# Feature: Data Importers and SimWorld Renderers

## 1. Overview
* **Name:** Data Importers and SimWorld Renderers
* **Phase:** Phase 2 — Synthetic World, Personas, Habits DSL, Generator, Renderers, Importers
* **Purpose:** Implements RFC standard renderers (`.mbox`, `.ics`, files manifest), `SimWorld` environment management, and idempotent source data ingestion into `sources` and `raw_items`.
* **Traces to:** `PACKS_SPEC.md` section 6, `DATA_MODEL.md` sections 1-2, `CONTRACT.md` invariant I-19.

## 2. Technical Rationale
* **How we achieved it:**
  - Standard RFC-822 email rendering using Python's `EmailMessage` and `From ` envelope line writing.
  - RFC-5545 iCalendar generation with UTC compact timestamps.
  - Snapshot manifest generation with content SHA-256 and relative paths.
  - Ingestion functions (`import_mail`, `import_calendar`, `import_files`, `import_links`) using `det_id(source_id, source_ref)` and `canonical_json` for idempotent storage.
* **Alternatives considered:** None. Re-import idempotency is mathematically strictly required.

## 3. Database Schema Impact
* **Changes made:** Populates `sources` and `raw_items` tables. Implements `SimWorld` with `messages`, `events`, `files`, and `tasks`.

## 4. Core Logic & Necessary Functions
* `render_mbox`, `render_ics`, `render_files` (`backend/src/probation/synth/render.py`): Standard serialization utilities.
* `SimWorld` (`backend/src/probation/synth/world.py`): SQLite simulation world manager.
* `import_mail`, `import_calendar`, `import_files`, `import_links` (`backend/src/probation/synth/importers.py`): Idempotent source importers.
* CLI commands `probation synth generate` and `probation import mail|calendar|files|links` (`backend/src/probation/cli.py`).

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_synth.py::test_t_id_importer_idempotency` (T-ID: Repeated imports produce 0 new raw items and 0 duplicates).
* **CLI verified:** `python -m probation.cli synth generate --size tiny` produces byte-identical files.

## 6. Dependencies & Deferred Work
* **Depends on:** `core/hashing.py`, `db/connection.py`.
* **Deferred to later phases:** Live readers/watchers (Phase 8b).
