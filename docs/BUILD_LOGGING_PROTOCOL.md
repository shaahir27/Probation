# Build Logging Protocol

This protocol governs how coding agents document their work in `build_history/` as features are implemented or updated.
It is distinct from `docs/`:
- `docs/` is the **specification suite** (the authoritative requirements and algorithms, defined before code exists).
- `build_history/` is the **construction and comprehension record** (what was actually built, exact file paths, key functions, why and how they are called, written as you build).

`build_history/` is **strictly local** and gitignored. It exists to enable human developers and subsequent agents to quickly navigate the codebase, understand which files and functions implement a feature, and comprehend execution flow without reverse-engineering thousands of lines of code.

---

## 1. When This Applies

Log as you build, not as an afterthought:
1. For every distinct feature or major component built within a phase.
2. Whenever an existing feature is modified, fixed, or extended in a later phase.
3. At the conclusion of every phase (writing `phase_XX_summary.md` and refreshing `build_history/index.md`).

A feature is **not done** until its log exists or is updated.

---

## 2. Directory Structure

```text
build_history/
├── index.md                                      # Master index of all features and statuses
├── phase_00_foundations_spikes/
│   ├── feature_[name].md                         # Individual feature logs
│   └── phase_00_summary.md                       # Phase aggregate summary
├── phase_01_core_ledger_llm/
├── phase_02_synth_world_importers/
├── phase_03_mail_calendar_packs/
├── phase_04_engine_core_backtest/
├── phase_05_evidence_licences_gate_drift/
├── phase_06_files_pack/
├── phase_06b_entity_facts_tavily/
├── phase_07_exam_board/
├── phase_08_chains_habits/
├── phase_08b_radar_reading_triage/
├── phase_09_api_dashboard/
├── phase_10_evaluation/
├── phase_11_deploy_demo/
└── phase_12_polish_submission/
```

- **Folder Names are Fixed**: Match the exact phase names from `docs/IMPLEMENTATION_PLAN.md`.
- **Flat Feature Hierarchy**: Feature files sit directly inside their respective phase folder.
- **Naming Convention**: `feature_[snake_case_name].md` (e.g., `feature_hash_chained_ledger.md`, `feature_pii_redaction.md`).

---

## 3. Template — Non-Negotiable Structure

Every feature log must strictly adhere to [`docs/templates/log_schema.md`](file:///d:/Desktop/project/Probation/docs/templates/log_schema.md).
Do not omit sections. Section 4 (**Core Logic & Necessary Functions**) is mandatory:
- Exact file paths must be specified.
- Function and class signatures must be detailed.
- **Why it is called** and **How it is called & callers** must be explicitly explained to demystify code flow.

---

## 4. Updating vs. Creating New Logs

- **Feature Modified / Extended Later**: Update the **original file** in its original phase directory. Do not spawn duplicate files (e.g., if Phase 5 adds drift alarms to the ledger, update `feature_hash_chained_ledger.md` in `phase_01_core_ledger_llm/`). Append or revise the section with a clear note explaining the update.
- **Distinct Dependent Feature**: Create a **new file** in the current phase folder, cross-referencing the dependent feature in Section 6.
- **Corrections**: If a previous log was inaccurate, mark the correction explicitly in the revised section rather than silently altering history.

---

## 5. Master Index Management (`build_history/index.md`)

Whenever a feature file is created or updated, update the table in `build_history/index.md`:

| Feature | Phase | File | Status | Last Updated |
|---|---|---|---|---|
| Hash-Chained Ledger | Phase 1 | `phase_01_core_ledger_llm/feature_hash_chained_ledger.md` | Built | Phase 1 |

*Status values*:
- `Built`: Fully implemented and verified against unit/contract tests.
- `Updated`: Originally built earlier, modified or extended in the current phase.
- `Deferred`: Started but deliberately incomplete (rationale documented in Section 6 of the log).

---

## 6. Phase Summaries (`phase_XX_summary.md`)

At the conclusion of each phase, write `phase_XX_summary.md` in that phase's folder summarizing:
1. High-level capabilities delivered.
2. All checkpoint acceptance items passed from `docs/IMPLEMENTATION_PLAN.md`.
3. Test IDs verified from `docs/TEST_PLAN.md`.
4. Any deferred items or known limitations.

---

## 7. Confidentiality & Git Isolation

- **Never Commit `build_history/`**: This directory is included in `.gitignore` to prevent pushing internal scratch logs or personal notes to public GitHub remotes.
- **No Secrets**: Never write API keys, tokens, or credentials into any markdown log. Use environment variable names only (`LLM_API_KEY`, `TAVILY_API_KEY`).

---

## 8. Definition of Done

A task/feature is complete only if:
1. The code is written and type-checked (`mypy --strict` on engine and core).
2. The relevant automated tests pass (`make check`).
3. Its `feature_[name].md` log exists or is updated per Section 4.
4. `build_history/index.md` is updated.
5. Invariants in `docs/CONTRACT.md` are upheld.
