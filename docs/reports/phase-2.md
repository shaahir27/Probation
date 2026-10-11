# Phase 2 Handoff: Synthetic World, Personas, Habits DSL, Generator, and Importers

**Branch:** `feature/phase-2`  
**Phase:** 2 — Synthetic World, Personas, Habits DSL, Generator, Renderers, Importers  

---

## Done
1. **20 Indian Student Personas**: Implemented rich hand-crafted profiles in `backend/src/probation/synth/personas.py` (15 development personas for tuning, 5 isolated test personas) with writing styles, contacts across university roles, origin download sites, courses, and target folder directories matching `EVALUATION_PLAN.md` section 2.1.
2. **Habits DSL with Temporal Drift**: Built rule evaluation engine in `backend/src/probation/synth/habits_dsl.py` covering email actions, calendar invite RSVPs, file destinations, opportunities, and link triage. Implemented default baseline distributions, sequence chain triggers, $0.07$ noise rate, and planned temporal habit drift at day 120 (R8 shifts early invites from 93% DECLINE to 80% ACCEPT; R2 alters newsletter retention).
3. **Deterministic 180-Day Timeline Generator**: Implemented `SyntheticGenerator` in `backend/src/probation/synth/generator.py` generating realistic email threads, calendar invites, downloaded files, and tasks. Generated `truth.json` ground truth file capturing true actions, rule IDs, and noise application.
4. **Offline Cached Body Pool**: Built zero-cost offline template library in `backend/src/probation/synth/body_pool.py` for mails, invites, and files with deterministic slot substitutions for names, courses, and deadlines.
5. **Standard RFC Renderers & SimWorld State**: Built export pipelines in `backend/src/probation/synth/render.py` generating RFC-822 `.mbox` archives, RFC-5545 `.ics` calendars, and folder snapshot manifests with relative directory trees. Built SQLite-backed `SimWorld` in `backend/src/probation/synth/world.py` providing isolated simulation database state.
6. **Idempotent Source Importers**: Built ingestion pipelines in `backend/src/probation/synth/importers.py` for mail, calendar, files, and links with SHA-256 deduplication inserting into `sources` and `raw_items` (satisfies invariant I-19 and T-ID idempotency).
7. **CLI Integration**: Wired up `probation synth generate` and `probation import mail|calendar|files|links` subcommands in `backend/src/probation/cli.py`.
8. **Generated and Committed Fixture**: Generated baseline `backend/tests/fixtures/tiny_synth/` (200 situations, 169 messages, 47 events, 50 files) with deterministic seed.

---

## Files Changed / Created
- `backend/src/probation/synth/__init__.py` (updated)
- `backend/src/probation/synth/personas.py` (updated)
- `backend/src/probation/synth/habits_dsl.py` (updated)
- `backend/src/probation/synth/generator.py` (updated)
- `backend/src/probation/synth/body_pool.py` (new)
- `backend/src/probation/synth/render.py` (updated)
- `backend/src/probation/synth/world.py` (updated)
- `backend/src/probation/synth/importers.py` (new)
- `backend/src/probation/cli.py` (updated)
- `backend/pyproject.toml` (updated)
- `backend/tests/unit/test_synth.py` (new)
- `backend/tests/fixtures/tiny_synth/` (new)
- `docs/reports/phase-2.md` (new)

---

## Tests
- `.\make.cmd check`:
  - `ruff check backend`: Passed (0 errors).
  - `ruff format --check backend`: Passed (104 files formatted).
  - `mypy --config-file backend/pyproject.toml backend/src/probation`: Passed (0 errors across 91 source files).
  - `pytest -q backend/tests -m "not live"`: 42 passed in 19.26s.
- **Contract Tests Satisfied**:
  - `T-SYNTH (Determinism)`: Identical seed produces byte-identical `.mbox`, `.ics`, `files_manifest.json`, `truth.json`, `persona.json`, `habits.json`, and `world.db`.
  - `T-SYNTH (Calibration)`: Observed habit adherence on full persona generation (2,900 situations) is $0.9328$, matching $1 - \text{noise} = 0.93$ well within 2 percentage points.
  - `T-SYNTH (Drift)`: Verified early invite actions change distribution after day 120 (DECLINE $\ge 70\%$ pre-drift; ACCEPT $\ge 60\%$ post-drift).
  - `T-SYNTH (Static Isolation)`: AST scan verifies core, engine, workers, and packs NEVER import or inspect `truth.json`.
  - `T-ID`: Repeated imports of mail, calendar, and file manifests yield 0 duplicate rows in `raw_items`.

---

## Invariants Touched
- **I-6 (No Peeking / Temporal Isolation)**: Ensured synthetic generation produces clear timestamp order and `known_at` timestamps for replay backtesting.
- **I-17 (World Isolation)**: `SimWorld` database state is completely decoupled from the Probation engine ledger/schema.
- **I-19 (Source Idempotency)**: Re-running source imports alters nothing in `raw_items`.

---

## Deviations and Assumptions
- Offline template pool was utilized in lieu of live Nemotron/LLM generation calls during testing, saving LLM budget and ensuring 100% deterministic, zero-latency reproducibility.

---

## Contract Change Requests
- None.

---

## New Dependencies
- None.

---

## LLM Cost Incurred
- $0.00 USD (All synthetic data generation and testing executed deterministically offline).

---

## Open Questions
- None.

---

## Suggested Next Step
- Phase 2 is complete, fully verified, and ready to merge into `main` at Merge Point 1.
- Proceed to **Phase 3: Mail and calendar packs** (Member 1) and **Phase 9: API & Dashboard** (Member 2).
