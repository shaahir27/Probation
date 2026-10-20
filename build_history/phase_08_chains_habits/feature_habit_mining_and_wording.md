---
feature: "Habit Pattern Mining & Number-Preserving Wording Validation"
phase: "Phase 8 — Chains and Habits"
status: "Built"
---

# Feature: Habit Pattern Mining & Number-Preserving Wording Validation

## 1. Overview
* **Name:** Habit Pattern Mining & Number-Preserving Wording Validation
* **Phase:** Phase 8 — Chains and Habits
* **Purpose:** Discovers statistically significant user habits across strong-outcome historical situations, formats them into deterministic explanatory statements with optional LLM rewording (`wording.v1`), enforces strict number preservation, and honors user denials without affecting predictive policy scoring.
* **Traces to:** `docs/ENGINE_SPEC.md` section 13, `docs/PROMPTS.md` section 7, `docs/CONTRACT.md` invariant I-16, and `docs/TEST_PLAN.md` T-HABIT.

## 2. Technical Rationale
* **How we achieved it:**
  - Discrete clues and quartile-binned numeric clues are grouped into `(clue_name, clue_value, action)` contingency tables.
  - Calculated conditional probabilities, support counts ($n \ge 20$), and lift against action base rates ($\text{lift} \ge 1.5$).
  - One-vs-rest Fisher's exact test (`scipy.stats.fisher_exact(alternative="greater")`) computes exact p-values for all candidate associations.
  - Benjamini-Hochberg false discovery rate control (`scipy.stats.false_discovery_control(method="bh")`) controls family-wise false discoveries at $q < 0.01$.
  - Statements are constructed deterministically with action verbs ("You declined 24 of 25 invites..."). LLM rewording via Nemotron 3 Super is checked by code-side multiset number validation (`validate_wording_sentence`) ensuring no numbers are added, dropped, or modified, and sentence length stays within 20–160 characters.
  - User denials (`status = 'denied'`) are recorded in the database, excluded from active explanations, and never reactivated on subsequent mining runs.
* **Alternatives considered:**
  - *LLM rule extraction:* Rejected per `CONTRACT.md` invariant I-16 (LLM output is data only, statistical policy and habit discovery must be computed by code).
  - *Standard unadjusted p-value cutoff:* Rejected due to high multiple-testing false alarm rates across hundreds of clue combinations; BH FDR correction is required.
* **Why we chose this path:**
  - Guarantees rigorous statistical guardrails against false pattern discovery while presenting human-readable, verifiable explanations to the user.

## 3. Database Schema Impact
* **Changes made:**
  - Utilizes existing `habits` table in `backend/src/probation/db/schema.sql`:
    `id`, `family`, `clue`, `clue_value`, `action`, `k`, `n`, `lift`, `q_value`, `statement`, `examples_json`, `status CHECK (status IN ('active','denied'))`, `created_at`.
  - Added duplicate detection and user denial preservation (`status = 'denied'` retained across mining ticks).

## 4. Core Logic & Necessary Functions
* `backend/src/probation/engine/habits.py`:
  - `extract_numbers(text: str) -> list[str]`: Extracts number tokens for multiset verification.
  - `validate_wording_sentence(template: str, candidate: str) -> bool`: Verifies character length bounds (20–160 chars) and exact equality of number multisets.
  - `build_habit_template(family: str, clue: str, clue_value: str, action: str, k: int, n: int) -> str`: Deterministically formats habit statement.
  - `reword_statement(template: str, llm_client: Any, clock: Clock) -> str`: Calls LLM wording prompt with fallback on validation error.
  - `mine_habits(conn: sqlite3.Connection, as_of: str | None, clock: Clock | None, ...) -> list[Habit]`: Performs quartile binning, Fisher exact tests, BH FDR correction, and DB upserts.

```python
def validate_wording_sentence(template: str, candidate: str) -> bool:
    if not candidate or len(candidate) < 20 or len(candidate) > 160:
        return False
    t_nums = extract_numbers(template)
    c_nums = extract_numbers(candidate)
    return Counter(t_nums) == Counter(c_nums)
```

## 5. Testing & Verification
* **Automated tests:**
  - `backend/tests/unit/test_chains_habits.py`:
    - `test_wording_validator_preserves_numbers`: Asserts validation rejects changed/omitted/added numbers and out-of-bound string lengths.
    - `test_habit_mining_discovers_planted_rule`: Tests pattern discovery on planted dataset ($n=25, k=24$, lift $\ge 1.5, q < 0.01$).
    - `test_habit_mining_bh_fdr_rejects_noise`: Asserts 0 habits mined on random noise.
    - `test_habit_denial_state`: Asserts denied habits remain denied across mining passes.
* **Manually verified:**
  - CLI command `python -m probation.cli habits mine` runs cleanly with Rich table formatting.

## 6. Dependencies & Deferred Work
* **Depends on:** `scipy.stats.fisher_exact`, `scipy.stats.false_discovery_control`, `probation.core.types.Habit`.
* **Known issues/deferred:** None.
