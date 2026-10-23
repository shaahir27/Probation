---
feature: "Synthetic World Generator and Habits DSL"
phase: "Phase 2 — Synthetic World, Personas, Habits DSL, Generator, Renderers, Importers"
status: "Built"
---

# Feature: Synthetic World Generator and Habits DSL

## 1. Overview
* **Name:** Synthetic World Generator and Habits DSL
* **Phase:** Phase 2 — Synthetic World, Personas, Habits DSL, Generator, Renderers, Importers
* **Purpose:** Implements 20 rich personas, the conditional habit rule DSL, 180-day timeline generation, offline template pool, and the hidden ground-truth answer key (`truth.json`).
* **Traces to:** `EVALUATION_PLAN.md` section 2, `PACKS_SPEC.md` section 6, `CONTRACT.md` invariant I-6.

## 2. Technical Rationale
* **How we achieved it:** 
  - Constructed 20 Indian student profiles in `synth/personas.py` (15 dev, 5 test) with writing styles, contact lists, and folder hierarchies.
  - Implemented `PersonaHabits` in `synth/habits_dsl.py` evaluating rules R1 to R14, applying $0.07$ noise, and simulating a temporal drift at day 120 (R8 shifts early invites to accept, R2 alters newsletter retention).
  - Developed `SyntheticGenerator` in `synth/generator.py` simulating 180 days of activity and generating `truth.json`.
  - Built offline `BodyPool` in `synth/body_pool.py` providing rich templates with deterministic slot substitution for zero-cost testing.
* **Alternatives considered:** Calling live LLM generation during tests; rejected due to non-determinism and budget constraints.
* **Why we chose this path:** Provides reproducible synthetic ground truth with mathematical calibration guarantees.

## 3. Database Schema Impact
* **Changes made:** Outputs isolated `world.db` SQLite schema (messages, events, files, tasks) completely isolated from engine schema.

## 4. Core Logic & Necessary Functions
* `Persona`, `list_personas`, `get_persona` (`backend/src/probation/synth/personas.py`): Structured persona records.
* `evaluate_habit` (`backend/src/probation/synth/habits_dsl.py`): Evaluates ground-truth action given situation attributes, applying noise and drift.
* `SyntheticGenerator.generate` (`backend/src/probation/synth/generator.py`): Generates full synthetic timeline, answers, and artifacts.
* `BodyPool` (`backend/src/probation/synth/body_pool.py`): Offline deterministic email and invite templates.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_synth.py::test_personas_structure_and_isolation`
  - `backend/tests/unit/test_synth.py::test_t_synth_determinism`
  - `backend/tests/unit/test_synth.py::test_t_synth_habit_calibration_and_noise`
  - `backend/tests/unit/test_synth.py::test_t_synth_temporal_drift`
  - `backend/tests/unit/test_synth.py::test_t_synth_static_isolation_check`
* **Calibration verified:** Full persona generation (2,900 situations) observed adherence is $0.9328$ (expected $0.9300$).

## 6. Dependencies & Deferred Work
* **Depends on:** `core/hashing.py`.
* **Deferred to later phases:** Domain packs consuming raw items (Phase 3).

## WP3/WP4 integration update - 2026-10-23

Opt-in registered synthesis adapter added; no tracked fixture regeneration performed.

Exact interfaces, callers and verification: docs/reports/wp3-wp4-integration-2026-10-23.md and the P06-P11 feature records. Final suite: 585 passed; no fixture/result mutation. This updates this component, not full phase completion. Accounting/single-flight remain blocked by W3-D03/W3-D04.
