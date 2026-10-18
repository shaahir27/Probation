# AGENT_PLAYBOOK

How to drive coding agents in Google Antigravity to build Probation, phase by phase. Authority: below `CONTRACT.md`.

Antigravity details below come from public guides and docs I read; menu and folder names change between versions. Items marked **(check)** need a quick look in your install.

---

## 1. Principles

1. **Contract first.** Agents read `AGENTS.md` and `CONTRACT.md` before touching code. If a rule seems wrong, the agent proposes a change and stops; it never edits the contract.
2. **Small phases, human gates.** One phase at a time (`IMPLEMENTATION_PLAN.md`). You review the plan before code and the report after.
3. **Tests are the truth.** A phase is done when its tests pass in `make check` (`TEST_PLAN.md`), not when the agent says it is.
4. **Point, don't paste.** Prompts refer to files by path. Do not paste long documents into prompts (saves credits, avoids stale copies).
5. **Synthetic data only.** Never give agents real mail, calendars or files.
6. **Parallel only where files do not overlap** (section 4).

---

## 2. Setup in Antigravity

1. Create the repo and put this `docs/` folder in it. Put `AGENTS.md` in the **repo root**. Antigravity reads `AGENTS.md` from the project root; a `GEMINI.md` in the root takes precedence if both exist **(check)**. We use `AGENTS.md` only.
2. Open the repo folder as the workspace.
3. **Workflows (optional but useful):** copy `docs/agent-kit/workflows/*.md` into the workspace workflows folder: `.agents/workflows/` in newer versions, `.agent/workflows/` in older ones **(check which your install reads; create one and look in the Rules and Workflows settings)**. You can then run them with `/run-phase` and `/verify-phase`.
4. **Mode:** use **Planning** mode for phase work (the agent writes an implementation plan and task list as artifacts you can review). Use **Fast** mode only for tiny edits **(check names in your version)**.
5. **Terminal safety:** set terminal command execution to require your review for anything that touches the network or deletes files **(check option names)**.
6. **Check the rules loaded.** Start a new chat and ask: "List the contract invariants I-1 to I-26 in one line each." If the agent cannot, `AGENTS.md` or the docs path is not being read.
7. Keep `AGENTS.md` **short** (it is loaded often). All detail stays in `docs/`.

---

## 3. The phase loop

For each phase in `IMPLEMENTATION_PLAN.md`:

1. **Branch:** `git checkout -b phase-N-name`.
2. **Kick off** with the preamble plus the phase prompt (section 5), in Planning mode.
3. **Review the plan artifact.** Check: right files, right tests, no new network calls, no contract edits, scope matches the phase. Comment and ask for changes. Approve only when satisfied.
4. **Agent implements**, committing in small steps (`phase-N: ...`).
5. **Agent runs `make check`** and fixes failures. It may not skip, weaken or delete tests.
6. **Agent writes the handoff report** (section 6) as a file `docs/reports/phase-N.md`.
7. **You verify** with `/verify-phase` or the checklist in section 7, ideally using a **second agent** (a fresh context catches what the builder missed).
8. **Merge** to `main` only if verification passes. Update the tracker in `IMPLEMENTATION_PLAN.md` section 5.
9. Record decisions and any answered open questions in `DECISIONS_AND_OPEN_QUESTIONS.md`.

---

## 4. Parallel agents

Antigravity's Manager view can run several agents at once **(check)**. Limit to **2 or 3** at a time and give each a different lane.

| Lane | Owns (may edit) | Phases |
|---|---|---|
| **A: engine** | `core/`, `db/`, `llm/`, `engine/`, `workers/`, `packs/mail/`, `packs/calendar/` | 1, 3, 4, 5, 7 |
| **B: data and packs** | `synth/`, `packs/files/`, `packs/chains/`, `packs/radar/`, `packs/reading/`, `web/`, `links/`, `workers/webfacts.py` | 2, 6, 6b, 8, 8b |
| **C: interface** | `api/`, `frontend/` | 9 |
| **D: evaluation and release** | `eval/`, `deploy/`, `docs/results/`, top-level README | 10, 11, 12 |

**Shared files** (conflict-prone): `config.py`, `cli.py`, `packs/registry.py`, `Makefile`, `pyproject.toml`. Rule: add lines only, keep them alphabetised, rebase before merging. Merge lane A first, then B, then C and D.

Good parallel pairs: Phase 1 (A) with Phase 2 (B); Phase 9 (C) alongside Phases 5 to 8 (A and B).

---

## 5. Kickoff prompts (copy and paste)

### 5.0 Common preamble (put at the top of every phase prompt)

```
You are building the Probation project. Before anything else, read AGENTS.md and
docs/CONTRACT.md, then the documents listed for this phase.
Rules: never edit docs/CONTRACT.md (propose a change in your report instead); use synthetic
data only; fail closed; no new network calls outside llm/client.py, pack connectors and
workers/executor.py; never weaken or delete tests; do not read or print .env.
Work in Planning mode: first produce an implementation plan and a task list for THIS phase only,
then wait for my approval before writing code.
When done: run `make check`, then write docs/reports/phase-N.md using the handoff template in
docs/AGENT_PLAYBOOK.md section 6. Do not start the next phase.
```

### 5.1 Phase 0
```
PHASE 0: Foundations and spikes. Read: docs/README.md, docs/TECH_STACK_AND_REPO.md,
docs/IMPLEMENTATION_PLAN.md (Phase 0), docs/DECISIONS_AND_OPEN_QUESTIONS.md section 3.
Goal: a repo that installs and checks cleanly, plus the four spikes. Scaffold the layout in
TECH_STACK_AND_REPO.md section 2 with empty documented modules; pyproject, Makefile, ruff/mypy
config, .env.example, .gitignore, config/prices.json; a frontend scaffold that builds.
Write scripts/spike_llm.py, spike_embed.py, verify_budget.py. Do NOT run anything that needs my
API key; give me the exact commands to run and a place to paste the results.
Acceptance: `make setup` and `make check` pass on a fresh clone.
```

### 5.2 Phase 1
```
PHASE 1: Core, database, ledger, LLM client, redaction. Read: docs/CONTRACT.md,
docs/DATA_MODEL.md, docs/PROMPTS.md sections 1, 2, 10, docs/TEST_PLAN.md (T-ID, T-CLOCK,
T-LEDGER, T-REDACT, T-LLM, T-SEC), docs/IMPLEMENTATION_PLAN.md (Phase 1).
Goal: implement core/types, enums, clock, hashing, history skeleton; db/schema.sql VERBATIM from
DATA_MODEL.md section 1; connection and per-process access helpers; ledger append and verify;
LLMClient with retries, cache, budget, JSON-schema-then-fallback; redact(); exposure logging;
CLI db init, ledger verify, budget show. Write the tests first for ledger and redaction.
Acceptance: the listed T- tests pass in `make check`.
```

### 5.3 Phase 2
```
PHASE 2: Synthetic world and importers. Read: docs/EVALUATION_PLAN.md section 2,
docs/PACKS_SPEC.md sections 0.5 and 6, docs/PROMPTS.md section 9, docs/TEST_PLAN.md (T-SYNTH),
docs/IMPLEMENTATION_PLAN.md (Phase 2).
Goal: personas, habits DSL, generator for mail, invites and files with a truth file, noise and
drift; body pool via cached synth prompts with a stub for tests; renderers (mbox, ics, folder
manifest, real directory tree, world.db); idempotent importers; commit tests/fixtures/tiny_synth.
The engine must never read truth.json (add the static check).
Acceptance: T-SYNTH passes; same seed gives identical output.
```

### 5.4 Phase 3
```
PHASE 3: Mail and calendar packs. Read: docs/CONTRACT.md section 5, docs/PACKS_SPEC.md sections
0 to 2, docs/PROMPTS.md sections 3 and 4, docs/TEST_PLAN.md (T-PACK, T-RESOLVE),
docs/IMPLEMENTATION_PLAN.md (Phase 3).
Goal: PackAdapter base and registry; mail and calendar packs (situations, tiers, deterministic
clues via HistoryView ONLY, reader integration, class keys, outcome resolvers, caps, hands-off);
ingestor worker; features step; StubReader.
Acceptance: T-PACK and T-RESOLVE pass for both packs.
```

### 5.5 Phase 4
```
PHASE 4: Engine core and backtest. Read: docs/ENGINE_SPEC.md sections 1 to 5 and 17,
docs/CONTRACT.md section 7, docs/EVALUATION_PLAN.md section 4 (B1, B2),
docs/TEST_PLAN.md (T-NOPEEK, T-POLICY, T-NOVELTY, T-LB, T-E2E), docs/IMPLEMENTATION_PLAN.md (Phase 4).
Goal: event-sourced replay loop; features encoding; logistic-regression policy with decay weights,
calibration, cold start, ABSTAIN; novelty; proposals and ledger writes (gate fixed to SHADOW);
report card; baselines B1 and B2; CLI backtest. Write the T-NOPEEK property test FIRST.
Run on tiny_synth and report numbers in docs/reports/phase-4.md.
```

### 5.6 Phase 5
```
PHASE 5: Evidence, licences, gate, executor, drift. Read: docs/ENGINE_SPEC.md sections 6 to 11,
docs/CONTRACT.md sections 3, 7, 8, docs/TEST_PLAN.md (T-EVIDENCE, T-CAPS, T-GATE, T-CUSUM,
T-PSI, T-EXEC, golden tables), docs/IMPLEMENTATION_PLAN.md (Phase 5).
Goal: evidence, lower bound with clipped pooling, licence derivation (exam_ok via an injectable
test double for now), hard-coded caps and hands-off, pure gate, audit holdout, Executor with
hold queue and undo for mail and calendar in SimWorld, resolver and scheduler workers, CUSUM
and PSI. Implement the golden numbers exactly.
```

### 5.7 Phase 6
```
PHASE 6: Files pack. Read: docs/PACKS_SPEC.md section 3, docs/ENGINE_SPEC.md sections 4 and 8.2,
docs/TEST_PLAN.md (T-PACK, T-RESOLVE, T-EXEC, T-HANDSOFF), docs/IMPLEMENTATION_PLAN.md (Phase 6).
Goal: files pack: situations from the manifest, hands-off detection, clues, top-K folder policy,
outcome resolver, Executor move and undo inside FILES_ALLOWED_ROOTS (no overwrite, no folder
creation), class keys. Reader stays off by default.
```

### 5.7b Phase 6b
```
PHASE 6b: Entity Facts Service (Tavily vetting). Read: docs/TAVILY_AND_NEW_PACKS.md sections 3 to 6,
11, 12, docs/CONTRACT.md I-21 to I-26, docs/PROMPTS.md section 15, docs/TEST_PLAN.md (T-WEBQ,
T-WEBISO, T-VET), docs/IMPLEMENTATION_PLAN.md (Phase 6b).
Goal: query guard, deterministic EntityFacts derivation, WebFactsView with restriction-only types,
a Tavily client with budget accounting, the webfacts worker, fixtures, brands.json (verify every
entry; do not guess domains). Web facts must never feed the policy, evidence or licences.
Do not call Tavily from tests; use recorded fixtures. Give me the exact command to record fixtures
with my own key.
```

### 5.8 Phase 7
```
PHASE 7: Exam board. Read: docs/ENGINE_SPEC.md section 15, docs/PACKS_SPEC.md exam operator
tables, docs/PROMPTS.md section 8, docs/TEST_PLAN.md (T-EXAM), docs/IMPLEMENTATION_PLAN.md (Phase 7).
Goal: exam orchestration and queueing (ENGINE_SPEC 15.0); operators for mail, calendar and files (code and LLM) with validators;
verdicts computed by code only (never an LLM); integrate exam_ok into licence derivation; CLI
exam run; a deliberately cheating policy fixture that must FAIL the exam.
```

### 5.9 Phase 8
```
PHASE 8: Chains and habits. Read: docs/ENGINE_SPEC.md sections 13 and 14, docs/PACKS_SPEC.md
section 4, docs/PROMPTS.md section 7, docs/TEST_PLAN.md (T-HABIT, T-CHAIN),
docs/IMPLEMENTATION_PLAN.md (Phase 8).
Goal: habit mining with BH correction and the number-preserving wording validator; chain mining,
proposer and Executor actions (BLOCK_TIME, CREATE_TASK, REPLY draft); weak evidence supports
level 1 only; explicit accepts and rejects are strong evidence.
```

### 5.9b Phase 8b
```
PHASE 8b: Link substrate, Opportunity Radar, Reading Triage. Read: docs/TAVILY_AND_NEW_PACKS.md
sections 6 to 9, docs/PACKS_SPEC.md section 5b, docs/PROMPTS.md sections 11 to 14,
docs/ENGINE_SPEC.md section 8, docs/TEST_PLAN.md (T-LINK, T-QUAR, T-PACK, T-RESOLVE, T-EXEC),
docs/IMPLEMENTATION_PLAN.md (Phase 8b).
Goal: URL sanitiser and hands-off rules, Extract wrapper (never for mail-body links), quarantined
extractors with code validators, Radar (out-of-band official-page lookup, TRACK and DISMISS,
tracker in SimWorld), Reading (FILE_TO_COLLECTION, ARCHIVE_LINK, library in SimWorld), exam
operators including page_injection. Page text must never reach the writer. Radar first; Reading
only if time remains.
```

### 5.10 Phase 9
```
PHASE 9: API and dashboard. Read: docs/CONTRACT.md section 9, docs/USER_FLOW.md,
docs/FRONTEND_IMPLEMENTATION_PLAN.md (required design brief), docs/DEMO_AND_SUBMISSION.md section 2,
docs/TEST_PLAN.md (T-API), docs/IMPLEMENTATION_PLAN.md (Phase 9), and the Member 2 handoff in
docs/MEMBER_SPLIT.md. Goal: implement the contract endpoints over fixtures first, then build the
responsive React dashboard using the navigation, screen grouping, visual, and accessibility decisions
in FRONTEND_IMPLEMENTATION_PLAN.md. Use USER_FLOW.md for journeys and microcopy.

Primary destinations: Home, Queue, Actions, Permissions, and More. Keep report card, metrics,
habits, chains, and exams together under Insights/More; Radar is available only when its pack and API
are active; Reading is cut first. Keep all scores scoped to the task/action they measure and never
show an overall trust/accuracy score. The current report-card API is family-scoped; surface the
task-score API gap and follow contract change control before claiming or fabricating task-level
historical scores. Do not change `CONTRACT.md` without approval.

Preserve plain-language UI, evidence and undo/cancel on automatic actions, phone-sized layouts,
loading/empty/error/stale states, and the Phase 9 T-API acceptance. If an API is missing something,
report the gap and its user impact.
```

### 5.11 Phase 10
```
PHASE 10: Evaluation. Read: docs/EVALUATION_PLAN.md (all), docs/TEST_PLAN.md (T-EVAL),
docs/IMPLEMENTATION_PLAN.md (Phase 10).
Goal: baseline B3, ablations, main run on all personas with the budget guard on, results.json,
tables and figures under docs/results/ (aggregates only). Tune only on the 15 development
personas. Report negative results honestly.
```

### 5.12 Phase 11
```
PHASE 11: Deploy. Read: docs/TECH_STACK_AND_REPO.md section 6, docs/SECURITY_PRIVACY.md section 5,
docs/IMPLEMENTATION_PLAN.md (Phase 11).
Goal: Dockerfiles, compose, vm-setup.sh, HTTPS, replay demo service using cached LLM answers,
per-IP rate limits, budget kill-switch. Do not run any command that deploys or needs my cloud
credentials; give me exact commands and a checklist instead.
```

### 5.13 Phase 12
```
PHASE 12: Polish and submission. Read: docs/DEMO_AND_SUBMISSION.md, docs/IMPLEMENTATION_PLAN.md
(Phase 12). Goal: README with architecture diagram and results, fresh-clone test script, secrets
scan instructions, submission text drafts (title, tagline, description), tools feedback draft.
```

---

## 6. Handoff report template (`docs/reports/phase-N.md`)

```
# Phase N handoff
Branch / commit:
## Done
(what was built, in plain words)
## Files changed
(list)
## Tests
(commands run and results; which T- ids pass)
## Invariants touched
(I-n list, and how each is still satisfied)
## Deviations and assumptions
(anything not exactly as the docs say)
## Contract change requests
(none, or: what / why / which invariants / alternatives)
## New dependencies
(name, purpose, licence)
## LLM cost incurred
(USD, calls)
## Open questions
## Suggested next step
```

---

## 7. Human review checklist (use after every phase)

- [ ] `make check` is green on a clean checkout of the branch.
- [ ] The phase's T- tests are present and meaningful (not trivially passing).
- [ ] No edits to `docs/CONTRACT.md`.
- [ ] Search finds no `datetime.now(`, `time.time(` outside `core/clock.py`; no network libraries outside the allowed modules.
- [ ] No secrets, no real data, no large generated files committed.
- [ ] New code follows the pure-function-at-the-core rule (engine logic has no I/O).
- [ ] Handoff report matches reality (spot-check one claim).
- [ ] Decisions and answered questions recorded.

---

## 8. Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Agent invents a field or table | It did not read the spec | Re-point it at `DATA_MODEL.md` and `CONTRACT.md`; ask it to quote the relevant lines |
| Tests pass but behaviour is wrong | Tests mock too much | Ask for table-driven tests from `TEST_PLAN.md` and the golden numbers |
| Two agents edit the same file | Lanes overlapped | Section 4 ownership; rebase; merge A before B |
| Agent "fixes" a test by loosening it | Pressure to finish | Reject; require the code fix; note in the report |
| LLM-dependent tests are flaky | Live calls in tests | Use `StubReader` and the fake server |
| Plan is too big | Phase scope creep | Tell it to cut to the listed tasks only |
| Agent adds a network call | Convenience | Reject; route through `llm/client.py` or the Executor |
| Credits drain | Long prompts, many agents | Point to docs by path; at most 3 agents; stop idle ones |

---

## 9. Stop and ask (agents must stop in these cases)

- A rule in `CONTRACT.md` seems to conflict with another document or with what is needed.
- A change would add a network destination, credential, or file-system write outside the allowed set.
- Two documents disagree (the higher-authority one wins; report the conflict).
- A test cannot pass without weakening it.
- Anything would involve real personal data or a secret.
