---
feature: "Action Autonomy Caps, Hands-off Rules, and Pure Gate Decider"
phase: "Phase 5 — Evidence, Licences, Gate, Executor, and Drift"
status: "Built"
---

# Feature: Action Autonomy Caps, Hands-off Rules, and Pure Gate Decider

## 1. Overview
* **Name:** Action Autonomy Caps, Hands-off Rules, and Pure Gate Decider
* **Phase:** Phase 5 — Evidence, Licences, Gate, Executor, and Drift
* **Purpose:** Codify immutable safety bounds, economic interruption cost bars, hands-off safety blacklists, and deterministic gate logic that calculates autonomy permission and audit holdout flags.
* **Traces to:** `CONTRACT.md` invariants I-3, I-10, I-11, I-20, `ENGINE_SPEC.md` sections 7, 8, 8.1, 8.2, 9, and `TEST_PLAN.md` T-CAPS, T-HANDSOFF, T-GATE (Golden Table 3.2).

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented immutable base action catalog `ACTION_CATALOG` specifying base cap, loss, recallable status, and derived economic bar ($p^* = 1 - 1/\text{loss}$).
  - Contextual conditional caps combinable via $\min$: lowered caps for unknown mail senders, unknown calendar organizers, money involved, and personal information requests.
  - Hard-coded hands-off rules blocking dangerous executable and script extensions (`.exe, .bat, .cmd, .msi, .ps1, ...`), double extensions (`.pdf.exe`), and Unicode right-to-left override character `\u202e`.
  - Pure, deterministic gate decider `decide_gate` implementing strict contract decision precedence: fail-closed $\to$ hands-off $\to$ effective licence cap $\to$ novelty $\to$ economic loss test ($(1-p)\cdot\text{loss} \ge 1$) $\to$ reproducible audit holdout ($10\%$) $\to$ execution dispatch.
* **Alternatives considered:** None; exact decision order and economic bar formula are mandated by `CONTRACT.md` and `ENGINE_SPEC.md`.
* **Why we chose this path:** Mathematical strictness guarantees zero LLM override over autonomy caps, strict fail-closed safety, and tamper-evident audit sampling.

## 3. Database Schema Impact
* **Changes made:** None directly to schema; proposals table fields (`gate`, `cap`, `licence_level`, `audit_holdout`) are now dynamically populated according to gate evaluation.

## 4. Core Logic & Necessary Functions
* `decide_gate` (`backend/src/probation/engine/gate.py`): Pure gate evaluator returning `GateResult(decision, reason, audit_holdout)`.
  - **Why it is called:** Evaluates situation context, model probability $p$, novelty flag, active licence level, and caps to determine whether to shadow, suggest, ask, hold, or execute.
  - **How it is called & callers:** Called by `engine/replay.py` and `workers/brain.py` during `SITUATION` processing.
* `compute_audit_draw` (`backend/src/probation/engine/gate.py`): Computes reproducible float $[0, 1)$ via `sha256(situation_id | AUDIT_SEED)[:8] / 2**32`.
  - **Why it is called:** Determines deterministic audit holdout selection for unbiased human ground truth collection.
* `get_action_cap` & `get_conditional_cap` (`backend/src/probation/engine/caps.py`): Computes $\min(\text{base\_cap}, \text{conditional\_caps}, \text{web\_cap})$.
* `is_hands_off` (`backend/src/probation/engine/handsoff.py`): Scans filename for blocked extensions, double extensions, and RLO spoofing.

```python
def decide_gate(
    *,
    action: str = "ARCHIVE",
    p: float = 1.0,
    novel: bool = False,
    licence_level: int = 0,
    cap: int = 3,
    hands_off: str | None = None,
    reader_required: bool = False,
    reader_ok: bool = True,
    deterministic_ok: bool = True,
    loss: float = 0.0,
    attention_cost: float = 1.0,
    recallable: bool = False,
    audit_draw: float = 0.5,
    audit_fraction: float = 0.10,
    budget_ok: bool = True,
) -> GateResult: ...
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_caps_and_handsoff.py` (`T-CAPS`, `T-HANDSOFF`): Validates catalog, losses, recallability, conditional caps, blocked extensions, and RLO detection.
  - `backend/tests/unit/test_gate_pure.py` (`T-GATE`): Table-driven test executing all 14 rows of Golden Table 3.2 in `docs/TEST_PLAN.md`.
* **Manually verified:** Verified that non-recallable actions (`REPLY`, `FORWARD`, `ACCEPT`, `DECLINE`) can never be assigned level 3 (`EXECUTE_SILENT`).

## 6. Dependencies & Deferred Work
* **Depends on:** `core/enums.py`, `core/types.py`, `config.py`.
* **Known issues/deferred:** LLM draft generation and draft validation for `REPLY` proposals hook in before final gate confirmation in Phase 7 / Phase 8.


## WP1 repair update - 22 October 2026

### 1. Overview
Canonical action metadata and invalid numeric gate inputs. Scope: docs/CHANGES_IMPLEMENTATION_PLAN.md section 5; CONTRACT remains unchanged.

### 2. Technical rationale
Policy labels retain case-sensitive parameters; central metadata uses the canonical type. Family and pack membership are checked. Unknown and no-op labels cannot create actions; non-finite/out-of-range gate inputs fail closed. Registry descriptors defer executable adapter imports until the Executor boundary.

### 3. Database schema impact
No persistent schema/ledger-byte migration or new dependency.

### 4. Core logic and necessary functions
backend/src/probation/core/actions.py: parse_action(label) -> ParsedAction and FAMILY_ACTIONS. backend/src/probation/engine/caps.py: get_action_cap/get_action_loss/is_recallable. backend/src/probation/engine/gate.py: decide_gate(...). backend/src/probation/workers/executor.py: create_action(...).
Why/how called: Policy labels retain case-sensitive parameters; central metadata uses the canonical type. Family and pack membership are checked. Unknown and no-op labels cannot create actions; non-finite/out-of-range gate inputs fail closed. Registry descriptors defer executable adapter imports until the Executor boundary.

### 5. Testing and verification
Test files test_wp1_actions.py, test_caps_and_handsoff.py and existing gate/pack tests (T-CAPS/T-GATE/T-SEC).
An earlier isolated full checkpoint passed 291 tests plus lint/types; later targeted results are recorded in docs/reports/wp1-progress-2026-10-22.md. Final checks remain required after all edits.

### 6. Dependencies and remaining work
WP0 committed c92131c; WP1 is in progress. See the progress report for open role/transaction, canonical-payload, clock/identity and handoff requirements. This update is not a WP1 completion claim or live-provider proof.
