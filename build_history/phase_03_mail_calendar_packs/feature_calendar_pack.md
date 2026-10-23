---
feature: "Calendar Pack Adapter, Clues & Resolver"
phase: "Phase 3 — Mail and Calendar Packs"
status: "Built"
---

# Feature: Calendar Pack Adapter, Clues & Resolver

## 1. Overview
* **Name:** Calendar Pack Adapter, Clues & Resolver
* **Phase:** Phase 3 — Mail and Calendar Packs
* **Purpose:** Implements the `calendar` domain pack adapter for extracting situations from inbound meeting invitations (`invite`), computing all 12 deterministic clues via `HistoryView(as_of=t)`, resolving attendee RSVP outcomes, executing/undoing RSVP actions in `SimWorld`, and running perturbation operators.
* **Traces to:** `CONTRACT.md` sections 2, 5, 8; `PACKS_SPEC.md` section 2; `ENGINE_SPEC.md` section 2.2.

## 2. Technical Rationale
* **How we achieved it:** Built `CalendarPack` implementing `PackAdapter`. Extracts inbound invitations with initial `NEEDS-ACTION` status into `Situation` objects. Organiser tiers count interactions across both calendar and mail history known at `as_of`. Clues evaluate overlapping conflicts and adjacent schedules. Outcomes resolve attendee statuses (`ACCEPT`, `DECLINE`, `TENTATIVE`, `NO_RESPONSE`) bounded by `min(event_start, occurred_at + 7 days)` with right-censoring.
* **Alternatives considered:** None (strictly dictated by `PACKS_SPEC.md` section 2).
* **Why we chose this path:** Accurately models college student and professional calendar commitments without leaking future event states.

## 3. Database Schema Impact
* **Changes made:** None to DDL.

## 4. Core Logic & Necessary Functions
* `CalendarPack` (`backend/src/probation/packs/calendar/__init__.py`): Calendar pack adapter class.
* `extract_calendar_clues` (`backend/src/probation/packs/calendar/clues.py`): Computes 12 deterministic clues via `HistoryView`.
* `resolve_calendar_outcome` (`backend/src/probation/packs/calendar/resolver.py`): Resolves RSVP outcomes with event start window censoring.
* `execute_calendar_action` & `undo_calendar_action` (`backend/src/probation/packs/calendar/executor.py`): `SimWorld` RSVP updates and `BLOCK_TIME` creation/deletion.
* `apply_calendar_code_operator` (`backend/src/probation/packs/calendar/exam_ops.py`): 6 exam operators and validators.

## 5. Testing & Verification
* **Automated tests:** `tests/unit/test_pack_conformance.py` (`T-PACK`), `tests/unit/test_outcome_resolvers.py` (`T-RESOLVE`).
* **Manually verified:** All calendar RSVP transitions and window cutoffs verified.

## 6. Dependencies & Deferred Work
* **Depends on:** Phase 1 core types, Phase 2 `SimWorld`.
* **Known issues/deferred:** None.


## WP1 final verified checkpoint - 22 October 2026

### 1. Overview
Calendar schema and descriptor integration. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5.

### 2. Technical rationale
Calendar decisions use descriptors and strict shared reader/exam models; executor imports occur at execution method boundaries.

### 3. Database schema impact
No persistent schema migration or new dependency; historical ledger bytes retained.

### 4. Core logic and necessary functions
backend/src/probation/packs/calendar/__init__.py: deferred executor imports; calendar/clues.py and exam_ops.py: exported job schemas.
Why/how called: Calendar decisions use descriptors and strict shared reader/exam models; executor imports occur at execution method boundaries.

### 5. Testing and verification
test_wp1_execution_authority.py, test_wp1_validation.py. Final isolated scripts/check.py passed 328 tests, Ruff lint/format, project mypy (130 modules) and strict core/engine mypy (24 modules). Source/snapshot fixture and published-result hashes unchanged.

### 6. Dependencies and remaining work
WP1 remains incomplete. See docs/reports/wp1-checkpoint-2026-10-22.md for exact gaps and CCR-F; this update supersedes earlier verification counts and any historical no-known-issues statement for this repair. No live provider call or contract amendment.

## WP3/WP4 integration update - 2026-10-23

Bounded current lookup and decision-projected calendar aggregates replace final-RSVP/history scans.

Exact interfaces, callers and verification: docs/reports/wp3-wp4-integration-2026-10-23.md and the P06-P11 feature records. Final suite: 585 passed; no fixture/result mutation. This updates this component, not full phase completion. Accounting/single-flight remain blocked by W3-D03/W3-D04.
