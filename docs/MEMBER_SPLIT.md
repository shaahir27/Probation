# MEMBER_SPLIT: Multi-Member Branch Strategy & Execution Roadmap

Authority: Below [`docs/CONTRACT.md`](CONTRACT.md). Extends [`docs/IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) and [`docs/AGENT_PLAYBOOK.md`](AGENT_PLAYBOOK.md) section 4.

---

## 1. Executive Summary

Probation uses a **4-Lane Architecture** that permits two team members (or two coding agents) to develop simultaneously on isolated branches without merge conflicts.

- **Lane A (Engine & Core)**: Models, database, cryptographic ledger, statistical policy, gate, and execution.
- **Lane B (Data & Packs & Tavily)**: Synthetic data generator, domain packs, link substrate, and Tavily vetting.
- **Lane C (Interface)**: API endpoints and React dashboard.
- **Lane D (Evaluation & Release)**: Evaluation harness, VM deployment, and final submission.

---

## 2. Master Parallel Roadmap

```
                    [ Phase 0: Foundations & Spikes ] (Merged to main)
                                    │
               ┌────────────────────┴────────────────────┐
               ▼                                         ▼
      [ Member 1: Lane A ]                      [ Member 2: Lane B ]
      Branch: phase-1-core-ledger               Branch: phase-2-synth-world
      Phase 1: Core, DB, Ledger, LLM            Phase 2: Personas, World, Importers
      Files:   core/, db/, llm/                 Files:   synth/, fixtures/
               └────────────────────┬────────────────────┘
                                    │
                        ★ MERGE BOTH TO MAIN ★
                                    │
               ┌────────────────────┴────────────────────┐
               ▼                                         ▼
      [ Member 1: Lane A ]                      [ Member 2: Lane B / C ]
      Branch: phase-3-mail-cal                  Branch: phase-9-api-ui
      Phase 3: Mail & Calendar packs            Phase 9: API & React Dashboard (fixtures)
               │                                         │
               ▼                                         ▼
      Phase 4: Engine Replay & Backtest         Phase 6b: Tavily Entity Facts
               │                                         │
               ▼                                         │
      Phase 5: Licences, Gate, Executor                  │
               └────────────────────┬────────────────────┘
                                    │
                        ★ MERGE BOTH TO MAIN ★
                                    │
               ┌────────────────────┴────────────────────┐
               ▼                                         ▼
      Phase 7: Exam Board                       Phase 6: Files Pack
      Phase 8: Chains & Habits                  Phase 8b: Radar & Reading Packs
               └────────────────────┬────────────────────┘
                                    │
                    [ Phase 10: Evaluation & Results ]
                                    │
                    [ Phase 11 & 12: Deploy & Submission ]
```

---

## 3. Member Ownership & Folder Boundaries

| Lane | Assigned Member | Folders Owned (Exclusive Write) | Phases |
|---|---|---|---|
| **Lane A (Engine)** | **Member 1** | `backend/src/probation/core/`<br>`backend/src/probation/db/`<br>`backend/src/probation/llm/`<br>`backend/src/probation/engine/`<br>`backend/src/probation/workers/`<br>`backend/src/probation/packs/mail/`<br>`backend/src/probation/packs/calendar/` | 1, 3, 4, 5, 7, 8 |
| **Lane B (Data & Packs)** | **Member 2** | `backend/src/probation/synth/`<br>`backend/tests/fixtures/`<br>`backend/src/probation/packs/files/`<br>`backend/src/probation/packs/chains/`<br>`backend/src/probation/packs/radar/`<br>`backend/src/probation/packs/reading/`<br>`backend/src/probation/web/`<br>`backend/src/probation/links/`<br>`backend/src/probation/workers/webfacts.py` | 2, 6, 6b, 8, 8b |
| **Lane C (Interface)** | **Member 2 (Parallel)** | `backend/src/probation/api/`<br>`frontend/` | 9 |
| **Lane D (Evaluation)** | **Both (Sequential)** | `backend/src/probation/eval/`<br>`deploy/`<br>`docs/results/` | 10, 11, 12 |

---

## 4. Phase-by-Phase Split & Merge Sequence

### Step 1: The Initial Split (Phases 1 & 2)
- **Member 1**: Creates `phase-1-core-db-ledger` from `main`. Implements `core/`, `db/schema.sql`, `db/ledger.py`, `llm/client.py`, and `llm/redact.py`.
- **Member 2**: Creates `phase-2-synth-world` from `main`. Implements `synth/personas.py`, `synth/generator.py`, `synth/render.py`, and `tests/fixtures/tiny_synth`.
- **Merge Point 1**: Both members run `make check`. Once green, merge Lane A into `main`, rebase Lane B onto `main`, and merge Lane B.

### Step 2: The Core Engine & Interface Split (Phases 3, 4, 5 & 9, 6b)
- **Member 1**: Takes `phase-3-mail-calendar` (depends on Phases 1 and 2). Implements mail and calendar clue extraction and resolvers. Then proceeds directly to `phase-4-engine-backtest` and `phase-5-licences-gate`.
- **Member 2**: While Member 1 builds the engine replay, Member 2 builds `phase-9-api-ui` (the FastAPI routes and React dashboard using `tiny_synth` fixtures) and `phase-6b-entity-facts-tavily` (Tavily search/extract vetting service).
- **Merge Point 2**: Both branches converge into `main`.

### Step 3: Generality, Autonomy & New Packs (Phases 7, 8 & 6, 8b)
- **Member 1**: Takes `phase-7-exam-board` and `phase-8-chains-habits`.
- **Member 2**: Takes `phase-6-files-pack` and `phase-8b-radar-reading-triage`.
- **Merge Point 3**: Both converge into `main`.

### Step 4: Final Evaluation, Deployment & Submission (Phases 10, 11, 12)
- Handled sequentially or collaboratively:
  - Phase 10: Benchmark runs on all synthetic personas.
  - Phase 11: Docker containerization and Nebius VM deployment.
  - Phase 12: Final documentation, demo video recording, and Devpost submission.

---

## 5. Conflict Prevention & Shared Files Rules

Three files are shared across lanes:
1. `backend/src/probation/config.py` (configuration tunables)
2. `backend/src/probation/cli.py` (CLI commands)
3. `backend/pyproject.toml` (dependencies)

### Rules:
- **Append-Only**: Always append new config fields or CLI subcommands to the bottom of the file or maintain strict alphabetical sorting.
- **Never Refactor Shared Signatures**: Do not rename existing helper functions or settings without coordination.
- **Rebase Before PR**: Always run `git fetch origin && git rebase origin/main` before requesting a merge.
- **Strict Verification Gate**: Run `make check` (or `.\make.cmd check`) locally before every commit and pull request.
