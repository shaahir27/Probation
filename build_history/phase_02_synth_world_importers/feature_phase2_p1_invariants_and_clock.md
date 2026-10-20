---
feature: "Phase 2 Remediation: P1 Invariants, Clock Uniformity, Proposal Immutability, and Explicit User Identity"
phase: "Phase 2 — Synthetic generation & calibration (Remediation)"
status: "Built"
---

# Feature: Phase 2 Remediation: P1 Invariants, Clock Uniformity, Proposal Immutability, and Explicit User Identity

## 1. Overview
* **Name:** Phase 2 Remediation: P1 Invariants, Clock Uniformity, Proposal Immutability, and Explicit User Identity
* **Phase:** Phase 2 — Synthetic generation & calibration
* **Purpose:** Address critical architectural and engine invariant violations identified during audit (H3, H4, H5, H6, H8): enforce zero wall-clock access outside `probation.core.clock.Clock`, remove forbidden proposal mutation in `workers/executor.py`, eliminate global settings coupling by propagating user addresses explicitly into packs and resolvers, and fail closed ($0$) on unknown action caps.
* **Traces to:** `docs/CONTRACT.md` §3 (no clock calls), §8 (proposals immutable; executor only performs side effects; fail closed), `docs/ENGINE_SPEC.md` §1.1 & §8, and `docs/PACKS_SPEC.md` §0.3.

## 2. Technical Rationale
* **How we achieved it:**
  - Enforced `probation.core.clock.Clock` uniformly across all workers (`executor.py`, `resolver.py`, `scheduler.py`, `webfacts.py`), packs (`files`, `radar`, `reading`, `mail`, `calendar`), web client/fixtures, and links extraction.
  - Hardened static AST test `test_t_clock_no_wall_clock_in_engine_modules` to recursively scan `engine/`, `core/`, `workers/`, and `packs/` for direct `datetime.now()` and `time.time()` calls.
  - Eliminated `cur.execute("UPDATE proposals SET gate = ?, licence_level = ? ...")` from `workers/executor.py`. Proposals are immutable records written once by the Brain; cancellations are audited exclusively into `actions` and `ledger`.
  - Replaced $O(N^2)$ mail resolution with `MailResolverIndex` and explicit `user_addresses` propagation from CLI/importers -> `meta` table -> `world.user_addresses` -> `resolve_outcomes`.
  - Enforced fail-closed return ($0$) on unknown actions in `get_action_cap` and all pack `level_cap` implementations.
* **Alternatives considered:** None; strictly mandated by `CONTRACT.md`.
* **Why we chose this path:** Preserves hash-chained replay integrity, auditability, and determinism across simulation environments.

## 3. Database Schema Impact
* **Changes made:** None. Ensured schema immutability triggers and constraints are strictly respected. `meta` table stores `user_addresses` during mailbox/calendar import for replay resolution.

## 4. Core Logic & Necessary Functions
* `Clock` (`backend/src/probation/core/clock.py`): Centralized temporal provider supporting `now()`, `now_iso()`, `today_iso()`, and timezone conversion `now(tz)`.
* `Executor.process_queue` (`backend/src/probation/workers/executor.py`): Re-evaluates licences at execution time. On licence drop, marks action `CANCELLED` and appends `action_cancelled` to the ledger without mutating the `proposals` row.
* `MailResolverIndex` (`backend/src/probation/packs/mail/resolver.py`): Pre-indexes thread IDs, in-reply-to headers, and sender buckets once per batch for $O(1)$ outcome lookups.
* `get_action_cap` (`backend/src/probation/engine/caps.py`): Enforces fail-closed autonomy (returns 0) for any unknown action string.

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_security_boundaries.py`: AST scan proves zero direct system clock calls outside `core/clock.py`.
  - `backend/tests/unit/test_executor_simworld.py`: Verifies proposal immutability and cancellation logging when licence drops.
  - `backend/tests/unit/test_caps_and_handsoff.py`: Verifies fail-closed caps ($0$) across all 6 packs.
  - `backend/tests/integration/test_backtest_e2e.py`: Verifies deterministic replay and backtest ledger hashing.
* **Manually verified:** Verified 182/182 pytest suite passing and `mypy --strict` passing on `core/` and `engine/`.

## 6. Dependencies & Deferred Work
* **Depends on:** Phase 1 core ledger and role access boundaries.
* **Known issues/deferred:** None. All Phase 2 P1 items (H3, H4, H5, H6, H8) are resolved.
