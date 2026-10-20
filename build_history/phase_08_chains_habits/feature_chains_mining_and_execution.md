---
feature: "Cross-Tool Action Chain Mining, Proposer, and Execution"
phase: "Phase 8 — Chains and Habits"
status: "Built"
---

# Feature: Cross-Tool Action Chain Mining, Proposer, and Execution

## 1. Overview
* **Name:** Cross-Tool Action Chain Mining, Proposer, and Execution
* **Phase:** Phase 8 — Chains and Habits
* **Purpose:** Discovers cross-tool sequence patterns within 24-hour windows (`REPLY`, `BLOCK_TIME`, `CREATE_TASK`), emits independently gated chain follow-up situations (`family=chain_followup`, `variant={follow_action}`), enforces evidence level bounding (WEAK similarity links support Level 1 only; Level 2/3 strictly requires strong human evidence), and executes/undoes side effects in `SimWorld`.
* **Traces to:** `docs/ENGINE_SPEC.md` section 14, `docs/PACKS_SPEC.md` section 4, `docs/CONTRACT.md` section 8, and `docs/TEST_PLAN.md` T-CHAIN.

## 2. Technical Rationale
* **How we achieved it:**
  - Track user-initiated events across a 24-hour observation window `(t, t + 24h]`.
  - Link follow-ups using explicit thread links (STRONG) or token cosine similarity between trigger text/subject and follow-up title $\ge 0.45$ (WEAK).
  - Compute daily base rates across the entire timeline of raw item activity and evaluate conditional association lift $\ge 1.5$, support $n \ge 20$, and probability $k/n \ge 0.60$.
  - Generate distinct `Situation` records with `pack='chains'`, `family='chain_followup'`, and `variant={follow_action}`, paired with independent proposals under class key `chain|{trigger_class_key}|{follow_action}`.
  - Bound derived licence level: weak similarity links contribute only to `n_all`, leaving `n_strong = 0`, capping autonomy strictly at Level 1 (`SUGGEST`). Level 2/3 autonomy requires explicit human accept/reject feedback or explicit strong links.
  - Implement execution and reversal for `BLOCK_TIME` (private calendar event), `CREATE_TASK` (todo task entry), and `REPLY` (draft creation) in `SimWorld`.
* **Alternatives considered:**
  - *Unified situation mutation:* Proposing follow-ups directly on the original situation was rejected by `docs/PACKS_SPEC.md` §4.2; multi-step workflows require separate, immutable proposal records for independent gating, audit holdouts, and revocable licences.
* **Why we chose this path:**
  - Satisfies `CONTRACT.md` invariants I-2 (side-effects by Executor only), I-7 (immutable ledger sequence), I-10 (derived licences from evidence), and I-20 (recallability required for execution levels).

## 3. Database Schema Impact
* **Changes made:**
  - Utilizes existing `chains` table in `backend/src/probation/db/schema.sql`:
    `id`, `trigger_class_key`, `follow_action`, `k`, `n`, `base_rate`, `lift`, `status CHECK (status IN ('active','retired'))`, `created_at`, `UNIQUE (trigger_class_key, follow_action)`.
  - Generates chain situation rows with `variant` populated as `follow_action`.

## 4. Core Logic & Necessary Functions
* `backend/src/probation/packs/chains/mining.py`:
  - `compute_text_similarity(text1: str, text2: str) -> float`: Evaluates token cosine similarity between trigger subject/body and follow-up event title.
  - `mine_chains(conn: sqlite3.Connection, as_of: str | None, ...) -> list[Chain]`: Scans 24-hour windows, evaluates lift against base rates, and upserts into `chains`.
* `backend/src/probation/packs/chains/proposer.py`:
  - `create_chain_situations_and_proposals(conn: sqlite3.Connection, trigger_sit: Situation, trigger_class_key: str, as_of: str, ...) -> list[tuple[Situation, Proposal]]`: Instantiates deterministic chain follow-up situations, computes audit draws, evaluates gate decisions, and logs proposals to the hash-chained ledger.
* `backend/src/probation/packs/chains/executor.py`:
  - `execute_chain_action(action: Action, world: ExecutorIO) -> ExecResult`: Performs `add_event`, `add_task`, or `add_message` against `SimWorld`.
  - `undo_chain_action(undo_data: dict[str, Any], world: ExecutorIO) -> ExecResult`: Reverses actions via `delete_event` and `delete_task`.
* `backend/src/probation/packs/chains/__init__.py`:
  - `ChainsPack`: Implements `PackAdapter` protocol for `chains`, resolving expired unanswered situations to `observed_action="NONE"` (WEAK).

```python
def execute_chain_action(action: Action, world: ExecutorIO) -> ExecResult:
    act_type = action.type.upper()
    if act_type == "BLOCK_TIME":
        ...
        world.add_event(...)
        return ExecResult(success=True, action_id=action.id, undo_data={"uid": uid, "type": "BLOCK_TIME"})
    elif act_type == "CREATE_TASK":
        ...
        world.add_task(...)
        return ExecResult(success=True, action_id=action.id, undo_data={"task_id": task_id, "type": "CREATE_TASK"})
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_chains_habits.py`:
    - `test_chain_mining_planted_pattern`: Verifies sequence mining detects planted trigger $\rightarrow$ `BLOCK_TIME` patterns ($n=25, k=20$, lift $\ge 1.5$).
    - `test_chain_proposer_and_variant`: Confirms generation of distinct variant situations and proposals with parsed deadlines.
    - `test_chain_weak_evidence_level_1_cap`: Asserts weak similarity links bound derived autonomy to Level 1 (`SUGGEST`).
    - `test_chain_unanswered_yields_none_outcome`: Asserts unanswered situations yield `NONE` (WEAK).
    - `test_chain_executor_and_undo`: Verifies side-effect execution and reversal in `SimWorld`.
* **Manually verified:**
  - CLI command `python -m probation.cli chains mine` runs cleanly with Rich table formatting.

## 6. Dependencies & Deferred Work
* **Depends on:** `probation.core.types.Chain`, `probation.synth.world.SimWorld`, `probation.packs.base.ExecutorIO`.
* **Known issues/deferred:** None.
