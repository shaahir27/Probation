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
