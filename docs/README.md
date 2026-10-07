# Probation: Project Docs

Status: v1 · 3 Oct 2026 · NVIDIA Global AI Hackathon, Personal AI track
Submission target: **29 Oct 2026** (hard deadline 30 Oct 2026, 10:00 am PDT = 10:30 pm IST).

This folder is the single source of truth for building **Probation**: a personal AI that earns permission to act for you, one small task type at a time, by proving on your own history that it would have done what you did.

---

## 1. Reading order

Humans read top to bottom. Agents read what their phase needs (see `AGENT_PLAYBOOK.md`).

| Order | File | Read it to learn |
|---|---|---|
| 1 | `SYSTEM_DESIGN.md` | The idea and the process, in plain words (explanatory) |
| 2 | `CONTRACT.md` | The rules and interfaces that must never be broken |
| 3 | `DATA_MODEL.md` | Database tables and the tamper-evident ledger |
| 4 | `ENGINE_SPEC.md` | Exact algorithms, thresholds and formulas |
| 5 | `PACKS_SPEC.md` | What each domain pack does (mail, calendar, files, chains) |
| 6 | `PROMPTS.md` | Every LLM prompt and output schema |
| 7 | `TECH_STACK_AND_REPO.md` | Tools, repo layout, settings, commands |
| 8 | `IMPLEMENTATION_PLAN.md` | The build phases, one by one |
| 9 | `TEST_PLAN.md` | What must pass at each phase |
| 10 | `EVALUATION_PLAN.md` | Synthetic data, baselines, metrics |
| 11 | `SECURITY_PRIVACY.md` | Threats and defences |
| 12 | `DECISIONS_AND_OPEN_QUESTIONS.md` | Why we chose what we chose, and what is still unchecked |
| 13 | `DEMO_AND_SUBMISSION.md` | Demo script and submission checklist |
| 13b | `TAVILY_AND_NEW_PACKS.md` | Tavily web grounding, the Radar and Reading packs, and the contract change CCR-1 |
| 14 | `USER_FLOW.md` | What the user sees and does, screen by screen |
| 15 | `AGENT_PLAYBOOK.md` | How to drive Antigravity agents phase by phase |
| 16 | `agent-kit/` | Workflow files to copy into the Antigravity workflows folder |

---

## 2. Which document wins in a conflict

1. `CONTRACT.md` (highest)
2. `ENGINE_SPEC.md`, `DATA_MODEL.md`, `PACKS_SPEC.md`, `PROMPTS.md`
3. `TECH_STACK_AND_REPO.md`, `IMPLEMENTATION_PLAN.md`, `TEST_PLAN.md`, `EVALUATION_PLAN.md`, `SECURITY_PRIVACY.md`
4. `SYSTEM_DESIGN.md` (explains the idea; it may lag behind the specs)

Where a spec deliberately differs from `SYSTEM_DESIGN.md`, the difference is listed in `DECISIONS_AND_OPEN_QUESTIONS.md` under "Changes from the system design".

**Changing a document:** only by explicit human approval. Agents must never edit `CONTRACT.md` on their own. They propose a change in their report and stop.

---

## 3. One-paragraph summary

Probation reads the traces your tools already keep (mail, calendar, files you download, and the follow-up steps you take after them). It predicts what you would do with each new item, records that prediction **before** it knows the answer, then checks what you really did. Per (task type, action) pair it counts how often it agreed with you, and computes a pessimistic estimate of its true accuracy. Only when that estimate clears a bar, and a trick-question exam passes, does it get a licence: suggest (level 1), act with undo (level 2), or act silently for easily reversible things (level 3). Licences expire and are removed automatically if mistakes appear or your habits change. Web facts from Tavily can only lower autonomy or inform the user ("the web can warn you; only your history can trust"); two more packs, Opportunity Radar and Reading Triage, use Tavily Search and Extract to verify and read opportunities and saved links. The AI models (NVIDIA Nemotron, hosted on Nebius Token Factory) only read text and write drafts. They never hold keys and never decide permissions.

---

## 4. Repo layout (target)

```
probation/
  AGENTS.md                  <- standing rules for agents (repo root)
  docs/                      <- this folder
  backend/                   <- Python engine, workers, API
  frontend/                  <- React dashboard
  deploy/                    <- docker-compose, VM setup, sandbox policy
  scripts/                   <- helper scripts
  data/                      <- gitignored: databases and synthetic data
```

Details: `TECH_STACK_AND_REPO.md`.

---

## 5. Day-1 checklist

1. Create the repo, add this `docs/` folder, put `AGENTS.md` in the repo root.
2. Create the `.env` file from the template in `TECH_STACK_AND_REPO.md` section 4 and add your Nebius Token Factory key.
3. Open the repo as a workspace in Antigravity and confirm `AGENTS.md` is picked up (see `AGENT_PLAYBOOK.md` section 2).
4. Run **Phase 0** from `IMPLEMENTATION_PLAN.md`.
5. Work through `DECISIONS_AND_OPEN_QUESTIONS.md` section 3 ("Verify on day 1") and tick items off.

---

## 6. Conventions used in all docs

- **MUST / MUST NOT / NEVER** are binding. **SHOULD** is a strong default.
- **(check)** means unverified. Verify before relying on it.
- **(assumption)** means a guess to be measured.
- All timestamps in storage are ISO-8601 UTC strings ending in `Z`.
- Names in `code font` are exact identifiers.
