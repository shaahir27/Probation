---
feature: "Mail Pack Adapter, Clues & Resolver"
phase: "Phase 3 — Mail and Calendar Packs"
status: "Built"
---

# Feature: Mail Pack Adapter, Clues & Resolver

## 1. Overview
* **Name:** Mail Pack Adapter, Clues & Resolver
* **Phase:** Phase 3 — Mail and Calendar Packs
* **Purpose:** Implements the `mail` domain pack adapter for extracting situations from raw incoming messages, computing all 16 deterministic clues strictly via `HistoryView(as_of=t)`, resolving priority-ranked outcomes, executing/undoing actions in `SimWorld`, and running counterfactual exam perturbation operators.
* **Traces to:** `CONTRACT.md` sections 2, 5, 8; `PACKS_SPEC.md` section 1; `ENGINE_SPEC.md` sections 1.1, 8.1.

## 2. Technical Rationale
* **How we achieved it:** Built `MailPack` implementing `PackAdapter`. Deterministic clues query `HistoryView` ensuring temporal isolation (`known_at <= as_of`). Outcome resolution follows strict priority order (`REPLY` > `FORWARD` > `TRASH` > `ARCHIVE` > `LEAVE`) with right-censoring for situations within the 7-day observation window. `execute` and `undo` manipulate labels in `SimWorld`.
* **Alternatives considered:** Resolving outcomes purely by final state without thread checks. Rejected: violates CONTRACT ranking where a sent reply takes precedence over subsequent archiving.
* **Why we chose this path:** Directly satisfies invariant I-6 ("no peeking") and provides tamper-evident state transitions in `SimWorld`.

## 3. Database Schema Impact
* **Changes made:** None to DDL (populates `situations`, `features`, and reads from `raw_items`).

## 4. Core Logic & Necessary Functions
* `MailPack` (`backend/src/probation/packs/mail/__init__.py`): Core pack adapter class.
* `extract_mail_clues` (`backend/src/probation/packs/mail/clues.py`): Computes 16 deterministic clues via `HistoryView`.
* `resolve_mail_outcome` (`backend/src/probation/packs/mail/resolver.py`): Priority-ranked outcome resolver with window censoring.
* `execute_mail_action` & `undo_mail_action` (`backend/src/probation/packs/mail/executor.py`): `SimWorld` execution and label reversal.
* `apply_mail_code_operator` (`backend/src/probation/packs/mail/exam_ops.py`): 10 exam perturbation operators and validators.

## 5. Testing & Verification
* **Automated tests:** `tests/unit/test_pack_conformance.py` (`T-PACK`), `tests/unit/test_outcome_resolvers.py` (`T-RESOLVE`).
* **Manually verified:** All 7 pack conformance checks pass cleanly.

## 6. Dependencies & Deferred Work
* **Depends on:** Phase 1 core types, Phase 2 `SimWorld`.
* **Known issues/deferred:** Writer draft generation is deferred to Phase 5 when Executor hold queue is fully wired.
