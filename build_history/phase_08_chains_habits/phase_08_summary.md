# Phase 8 Summary: Chains and Habits

## Objectives Achieved
1. **Benjamini-Hochberg Habit Mining:**
   - Implemented one-vs-rest Fisher's exact test and Benjamini-Hochberg FDR correction ($q < 0.01$, $n \ge 20$, $\text{lift} \ge 1.5$).
   - Quartile binning for numeric clues.
   - Deterministic template construction and LLM wording fallback.
   - Code-side number-preserving multiset wording validator (`validate_wording_sentence`).
   - Preservation of user denials across mining runs.

2. **Cross-Tool Action Chain Mining:**
   - 24-hour window sequence tracking for `REPLY`, `BLOCK_TIME`, and `CREATE_TASK` ($n \ge 20$, $k/n \ge 0.60$, $\text{lift} \ge 1.5$).
   - Dual linking mechanism: explicit thread links (STRONG) and token cosine similarity $\ge 0.45$ (WEAK).
   - Base rates evaluated across all active historical raw item days.

3. **Chains Pack & Proposal Generation:**
   - Emits distinct `variant` situations (`pack='chains'`, `family='chain_followup'`, `variant={follow_action}`).
   - Gated independently with class key `chain|{trigger_class_key}|{follow_action}`.
   - Strict evidence rule: weak similarity links support Level 1 only (`SUGGEST`); autonomous execution (Level 2/3) strictly requires strong human evidence.
   - Fallback outcome resolution: unanswered situations yield `observed_action="NONE"` (WEAK).

4. **Execution & Undo in SimWorld:**
   - `BLOCK_TIME`: Creates and deletes private calendar event in `SimWorld`.
   - `CREATE_TASK`: Creates and deletes task in `SimWorld`.
   - `REPLY`: Creates draft message in `SimWorld`.

5. **Integration & CLI:**
   - Integrated into `replay.py` (weekly/retrain ticks and trigger situation follow-up proposal dispatch).
   - Integrated into `scheduler.py` (`run_nightly_review`).
   - Added CLI subcommands: `probation habits mine` and `probation chains mine`.

6. **Quality & Verification:**
   - 100% pass on 9 unit tests in `backend/tests/unit/test_chains_habits.py`.
   - 100% pass across full test suite (154 tests passed).
   - Mypy `--strict` passed with 0 issues.
   - Ruff lint and formatting passed with 0 issues.
   - Frontend `npm run build` completed cleanly.
