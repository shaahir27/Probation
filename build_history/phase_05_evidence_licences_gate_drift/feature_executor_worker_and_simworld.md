---
feature: "Executor Worker, Hold Queue, Licence Re-check, and SimWorld Undo"
phase: "Phase 5 — Evidence, Licences, Gate, Executor, and Drift"
status: "Built"
---

# Feature: Executor Worker, Hold Queue, Licence Re-check, and SimWorld Undo

## 1. Overview
* **Name:** Executor Worker, Hold Queue, Licence Re-check, and SimWorld Undo
* **Phase:** Phase 5 — Evidence, Licences, Gate, Executor, and Drift
* **Purpose:** Implement the single process boundary holding write side-effect credentials (`Role.EXECUTOR`), managing hold delays (10 minutes for irreversible actions), performing runtime licence re-checks, executing actions in SimWorld, and executing clean undos that feed strong disagreement outcomes.
* **Traces to:** `CONTRACT.md` section 3, section 8, invariants I-2, I-10, I-20, `ENGINE_SPEC.md` section 10, and `TEST_PLAN.md` T-EXEC.

## 2. Technical Rationale
* **How we achieved it:**
  - Implemented `Executor` class restricted to `Role.EXECUTOR` (`ROLE_ALLOWED_WRITE_TABLES = {"actions", "outcomes", "ledger"}`).
  - `create_action`: Enforces status `HELD` with `hold_until = created_at + 10m` for `HOLD_THEN_EXECUTE`, and `PENDING` for `EXECUTE_UNDO` / `EXECUTE_SILENT`.
  - `process_queue`: Polls executable actions; **re-derives licence level at execution time**; if licence fell below requirement, cancels action and produces fallback `SUGGEST` item; executes side-effect via pack adapter (`mail_pack.execute`, `calendar_pack.execute`); stores `undo_json` and updates status to `DONE`.
  - `process_undo`: Idempotently reverses action in `SimWorld` via `pack.undo(action, io)`; marks action `UNDONE`; records strong disagreement outcome (`source = 'undo'`); updates CUSUM drift tracker.
* **Alternatives considered:** None; write isolation in the Executor process is an unbreachable invariant of `CONTRACT.md`.
* **Why we chose this path:** Complete side-effect safety and user control with guaranteed reversibility.

## 3. Database Schema Impact
* **Changes made:** Manages rows in `actions` table (`status` transitions `HELD` $\to$ `DONE` $\to$ `UNDONE` or `CANCELLED`), `outcomes` table (undo outcomes), and hash-chained `ledger` events (`LedgerKind.ACTION`, `LedgerKind.OUTCOME`).

## 4. Core Logic & Necessary Functions
* `Executor.create_action` (`backend/src/probation/workers/executor.py`): Creates an action record from a gated proposal.
  - **Why it is called:** Queues side-effects when the gate approves autonomous execution.
  - **How it is called & callers:** Called by `engine/replay.py` during `SITUATION` processing.
* `Executor.process_queue` (`backend/src/probation/workers/executor.py`): Executes ready actions after licence re-verification.
  - **Why it is called:** Advances hold queue and executes actions once hold delay elapses.
  - **How it is called & callers:** Called during `SITUATION` processing and daily `LICENCE_REVIEW` ticks.
* `Executor.process_undo` (`backend/src/probation/workers/executor.py`): Reverses action in external world and logs disagreement.
  - **Why it is called:** Triggered when the user invokes undo on an automatic action.
  - **How it is called & callers:** Called by API worker (`POST /actions/{id}/undo`).

```python
class Executor:
    def __init__(
        self,
        conn: sqlite3.Connection,
        world: ExecutorIO | None = None,
        licence_checker: Callable[[str, str, str], int] | None = None,
    ) -> None: ...

    def process_queue(self, as_of: str | None = None) -> list[ExecResult]: ...
    def process_undo(self, action_id: str, as_of: str | None = None) -> ExecResult: ...
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_executor_simworld.py` (`T-EXEC`): Tests ARCHIVE execution and undo in SimWorld; verifies INBOX label restoration; tests 10-minute hold queue delay for calendar ACCEPT; tests licence-lost cancellation fallback to `SUGGEST`; tests idempotency.
* **Manually verified:** Verified that executing an already completed action twice produces zero side-effects.

## 6. Dependencies & Deferred Work
* **Depends on:** `packs/mail/executor.py`, `packs/calendar/executor.py`, `synth/world.py`, `db/ledger.py`.
* **Known issues/deferred:** File move side-effects and directory safety checks will be integrated in Phase 6 (Files Pack).
