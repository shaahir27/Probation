# IMPLEMENTATION_PLAN

The build, phase by phase. Day 1 is **3 Oct 2026**. Target submission: **29 Oct 2026** (hard deadline 30 Oct 2026, 10:00 am PDT = 10:30 pm IST). If Phase 0 starts later, shift every date by the same amount and apply the slip rules in section 3.

Read with: `CONTRACT.md` (rules), `TEST_PLAN.md` (what must pass), `AGENT_PLAYBOOK.md` (how to run agents).

---

## 1. Overview

| Phase | Name | Dates | Depends on | Lane |
|---|---|---|---|---|
| 0 | Foundations and spikes | 3-4 Oct | none | A |
| 1 | Core, database, ledger, LLM client, redaction | 4-7 Oct | 0 | A |
| 2 | Synthetic world and importers | 4-10 Oct | 0 | B |
| 3 | Mail and calendar packs | 7-11 Oct | 1, 2 | A |
| 4 | Engine core and backtest | 10-14 Oct | 3 | A |
| 5 | Evidence, licences, gate, executor, drift | 13-17 Oct | 4 | A |
| 6 | Files pack | 15-19 Oct | 5, 2 | B |
| 6b | Entity Facts Service (Tavily vetting) | 13-17 Oct | 1, 3 | B |
| 7 | Exam board | 17-21 Oct | 5, 6 | A |
| 8 | Chains and habits | 19-23 Oct | 7 | A |
| 8b | Link substrate, Opportunity Radar, Reading Triage | 20-25 Oct | 6b, 7, 8 | B |
| 9 | API and dashboard | 14-25 Oct | 1 (build over fixtures), 5 | C |
| 10 | Evaluation | 22-26 Oct | 8 | D |
| 11 | Deploy on Nebius and demo build | 24-27 Oct | 9, 10 | D |
| 12 | Polish and submission | 26-29 Oct | 11 | D |
| S | (GitHub stretch pack dropped; replaced by 6b and 8b) | | | |

**Lanes** (can run in parallel by different agents): A engine, B data and packs, C interface, D evaluation and release.
**Critical path:** 0 -> 1 -> 3 -> 4 -> 5 -> 7 -> 10 -> 11 -> 12. Lane B (6b, then 8b) runs beside it; Phase 8b must finish before Phase 10 so the evaluation includes it.

Every phase follows the same loop (`AGENT_PLAYBOOK.md`): plan, implement, `make check`, write a handoff report, human review, commit.

---

## 2. Phases

### Phase 0: Foundations and spikes (3-4 Oct)

**Goal:** a repo that installs and checks cleanly, and the four unknowns resolved.
**Read:** `README.md`, `TECH_STACK_AND_REPO.md`, `DECISIONS_AND_OPEN_QUESTIONS.md` section 3.

Tasks:
- [ ] Create the repo; copy `docs/`; put `AGENTS.md` in the root; add `LICENSE` (choose one, see `DEMO_AND_SUBMISSION.md`).
- [ ] Scaffold the layout in `TECH_STACK_AND_REPO.md` section 2 (empty modules with docstrings).
- [ ] `pyproject.toml`, `Makefile`, ruff and mypy configuration, `.env.example`, `.gitignore`, `config/prices.json`.
- [ ] Frontend scaffold (Vite + React + TypeScript + Tailwind) that builds.
- [ ] Spike: LLM call (`scripts/spike_llm.py`).
- [ ] Spike: local embeddings (`scripts/spike_embed.py`).
- [ ] Spike: sandbox (time-box 3 hours).
- [ ] Spike: budget estimate versus the Nebius console.
- [ ] Spike: Tavily (`scripts/spike_tavily.py`): one Search and one Extract call; record credits used and latency. **Do this in the first week**: a functional runtime call is the eligibility condition for the Tavily bonus.
- [ ] Record every spike outcome and the exact model names in `DECISIONS_AND_OPEN_QUESTIONS.md`.

Deliverables: runnable scaffold; spike scripts; updated open-questions table.
Acceptance:
- `make setup` works on a fresh clone; `make check` passes.
- One schema-valid reader-prompt response from Nebius, with latency and tokens printed.
- Decision recorded for JSON-schema mode (works or fallback), sandbox (use or skip) and embeddings (fastembed or fallback).

Cut line: skip the sandbox spike if it exceeds 3 hours.

### Phase 1: Core, database, ledger, LLM client, redaction (4-7 Oct)

**Goal:** the trusted foundation everything else stands on.
**Read:** `CONTRACT.md` sections 2, 3, 6; `DATA_MODEL.md`; `PROMPTS.md` sections 1-2, 10.

Tasks:
- [ ] `core/types.py`, `enums.py`, `clock.py`, `hashing.py` (`det_id`, `canonical_json`, `ledger_hash`), `history.py` skeleton.
- [ ] `db/schema.sql` **verbatim** from `DATA_MODEL.md` section 1; `connection.py`; `access.py` with per-process write helpers.
- [ ] `db/ledger.py`: `append`, `verify`.
- [ ] `llm/client.py` (retries, backoff, JSON-schema first then fallback, one repair retry), `cache.py`, `budget.py`, price table loading.
- [ ] `llm/redact.py` per `PROMPTS.md` section 1.
- [ ] `exposure_log` writes.
- [ ] CLI: `db init`, `ledger verify`, `budget show`.

Deliverables: the modules above and their tests.
Acceptance: **T-ID, T-CLOCK, T-LEDGER, T-REDACT, T-LLM, T-SEC (partial)** pass; one `@live` smoke test passes against Nebius.
Cut line: none. This phase is non-negotiable.

### Phase 2: Synthetic world and importers (4-10 Oct, parallel with 1)

**Goal:** realistic, reproducible practice data with a hidden answer key.
**Read:** `EVALUATION_PLAN.md` section 2; `PACKS_SPEC.md` sections 0.5, 6; `PROMPTS.md` section 9.

Tasks:
- [ ] `synth/personas.py`: load personas (Nemotron-Personas-India; fall back to 5 hand-written personas if loading is slow).
- [ ] `synth/habits_dsl.py`: hidden habit rules (conditions on situation attributes giving action probabilities).
- [ ] `synth/generator.py`: events for mail, invites and files across 180 days; noise; one habit drift at day 120; **truth file** with the persona's true action for every situation.
- [ ] Body pool via `synth.*` prompts, cached; code-side substitutions.
- [ ] `synth/render.py` and `world.py`: output `.mbox`, `.ics`, folder manifest, a real directory tree, and `world.db`.
- [ ] Importers: `import mail|calendar|files` (idempotent).
- [ ] Commit `tests/fixtures/tiny_synth` (about 200 situations).

Deliverables: `probation synth generate`, importers, fixture.
Acceptance: **T-SYNTH** passes; re-import changes nothing (T-ID); one full persona generated (about 2,000 mails, 300 invites, 600 files) and its habit adherence matches `1 - noise` within 2 points.
Cut line: reduce to 10 personas and a smaller body pool if the cost approaches the budget guard.

### Phase 3: Mail and calendar packs (7-11 Oct)

**Goal:** situations, clues and outcomes for the two most important packs.
**Read:** `CONTRACT.md` section 5; `PACKS_SPEC.md` sections 0-2; `PROMPTS.md` sections 3-4.

Tasks:
- [ ] `packs/base.py`, `registry.py`.
- [ ] Mail: situations, tiers, deterministic clues (history only through `HistoryView`), reader integration, class key, outcome resolver, `level_cap`, `hands_off`.
- [ ] Calendar: same.
- [ ] `workers/ingestor.py` and the `brain` features step (writes `features`).
- [ ] `StubReader` for tests.

Deliverables: two packs registered; features computed for the tiny persona.
Acceptance: **T-PACK** and **T-RESOLVE** pass for mail and calendar.

### Phase 4: Engine core and backtest (10-14 Oct)

**Goal:** the "driving test on your own past" runs end to end and produces a report card.
**Read:** `ENGINE_SPEC.md` sections 1-5, 17; `CONTRACT.md` section 7.

Tasks:
- [ ] `engine/replay.py` (event-sourced loop, tie order).
- [ ] `engine/features.py` (encoding), `policy.py` (logistic regression, decay weights, calibration, cold start, `ABSTAIN`), `novelty.py`.
- [ ] Proposal writing and ledger entries (gate fixed to `SHADOW` until Phase 5).
- [ ] `engine/report.py` (report card).
- [ ] Baselines B1 (ask always) and B2 (generic rules), `EVALUATION_PLAN.md` section 4.
- [ ] CLI `backtest`.
- [ ] Run on `tiny_synth` and one full persona; save numbers to `docs/results/phase4.md` (aggregates only).

Acceptance: **T-NOPEEK, T-POLICY, T-NOVELTY, T-LB, T-E2E (backtest only)** pass; on the full persona the agreement for each family clearly exceeds the majority-class baseline B0 (`EVALUATION_PLAN.md` section 4); if not, document why before proceeding.

### Phase 5: Evidence, licences, gate, executor, drift (13-17 Oct)

**Goal:** permissions that are earned, enforced, and revoked automatically.
**Read:** `ENGINE_SPEC.md` sections 6-11; `CONTRACT.md` sections 3, 7, 8.

Tasks:
- [ ] `engine/evidence.py`, `licence.py` (with a test double for `exam_ok` until Phase 7), `caps.py`, `handsoff.py`, `gate.py` (pure), audit holdout.
- [ ] `workers/executor.py`: hold queue, `execute`/`undo` for mail and calendar in `SimWorld`; licence re-check at action time; idempotency.
- [ ] `workers/resolver.py`, `scheduler.py` (nightly review, retrain ticks).
- [ ] `engine/drift.py`: CUSUM and PSI.
- [ ] Ledger events for licence changes and drift alarms.

Acceptance: **T-EVIDENCE, T-CAPS, T-GATE, T-CUSUM, T-PSI, T-EXEC (mail, calendar)** pass; in a backtest, level 1 licences appear for high-volume classes and the executor actions are undoable.

### Phase 6: Files pack (15-19 Oct)

**Goal:** the second kind of work, proving the engine is general.
**Read:** `PACKS_SPEC.md` section 3; `ENGINE_SPEC.md` sections 4 (files family), 8.2.

Tasks:
- [ ] Situations from the manifest; hands-off detection; deterministic clues; top-K folder policy; outcome resolver; executor (move/undo inside allowed roots, no overwrite, no folder creation); class keys.
- [ ] Optional reader (off by default).

Acceptance: **T-PACK, T-RESOLVE, T-EXEC, T-HANDSOFF** pass for files; a backtest shows the files family earning licences for recurring origins.

### Phase 6b: Entity Facts Service (13-17 Oct, lane B, parallel with Phase 5)

**Goal:** Tavily-backed sender and link vetting that can only restrict and inform.
**Read:** `TAVILY_AND_NEW_PACKS.md` sections 3 to 6, 11, 12; `CONTRACT.md` I-21 to I-26; `PROMPTS.md` section 15.

Tasks:
- [ ] `web/query_guard.py`, `web/derive.py` (EntityFacts rules), `web/view.py` (`WebFactsView`, restriction-only types), `web/client.py` (Tavily client with timeouts, retries, credit accounting).
- [ ] `workers/webfacts.py`; tables `web_facts`, `tavily_calls`; `config/brands.json` (about 150 entries, **each verified against the brand's own site**).
- [ ] Fixture generator: run Tavily once per catalog entity (real organisations plus fictional lookalikes) and store fixtures (`origin=fixture`).
- [ ] Brain integration: web cap into the cap computation; `proposals.web_json`; reasons; item-detail data.

Acceptance: **T-WEBQ, T-WEBISO, T-VET** pass; a live demo run vets one real domain and one fictional lookalike and shows sources.
Cut line: reduce the brand list to 50 entries.

### Phase 7: Exam board (17-21 Oct)

**Goal:** a licence cannot be issued without passing the trick-question exam.
**Read:** `ENGINE_SPEC.md` section 15; `PACKS_SPEC.md` operator tables; `PROMPTS.md` section 8.

Tasks:
- [ ] `engine/exam.py` orchestration; operator implementations (mail, calendar, files) with validators; LLM operators through `MODEL_EXAM_EDITS`.
- [ ] Integrate `exam_ok(c, a, as_of, level)` into `licence.py`; exam queueing at review ticks capped by `EXAM_MAX_PER_DAY` (ENGINE_SPEC 15.0); `exam_runs.level_tested`; ledger entries; CLI `exam run`.
- [ ] A deliberately cheating policy fixture to prove the exam can fail.

Acceptance: **T-EXAM** passes; a backtest now yields level 2 licences for the highest-volume classes, or documents why not (data volume, exam failures).

### Phase 8: Chains and habits (19-23 Oct)

**Goal:** the "something more": follow-up steps across tools, and readable habits.
**Read:** `ENGINE_SPEC.md` sections 13-14; `PACKS_SPEC.md` section 4; `PROMPTS.md` section 7.

Tasks:
- [ ] `engine/habits.py` plus wording and number validator.
- [ ] `packs/chains`: mining, proposer, executor for `BLOCK_TIME`, `CREATE_TASK`, and chain `REPLY` drafts.
- [ ] Weak versus strong evidence rules; explicit accept and reject writing strong outcomes.

Acceptance: **T-HABIT, T-CHAIN** pass; the demo persona's planted "deadline mail -> reply + block time" chain is discovered with the correct counts.

### Phase 8b: Link substrate, Opportunity Radar, Reading Triage (20-25 Oct, lane B)

**Goal:** the new packs that make Tavily essential (Search to find the official page, Extract to read it).
**Read:** `TAVILY_AND_NEW_PACKS.md` sections 6 to 9; `PACKS_SPEC.md` section 5b; `PROMPTS.md` sections 11 to 14; `ENGINE_SPEC.md` section 8.

Tasks:
- [ ] `links/sanitise.py`, `links/extract.py`; tables `extractions`, `quarantine_outputs`; quarantined extractors (`extract.opportunity.v1`, `extract.link.v1`) with validators.
- [ ] Radar: mail intent `opportunity`, `reader.opportunity.v1`, out-of-band official-page lookup, vetting of link domains, `TRACK` and `DISMISS`, tracker in `SimWorld`, outcome resolver, exam operators, `radar.digest.v1`.
- [ ] Reading: inbox intake, clues, `FILE_TO_COLLECTION` and `ARCHIVE_LINK`, library in `SimWorld`, resolver, exam operators.
- [ ] Synthetic generator: opportunity mails (real public opportunity pages as fixtures, **fictional** lookalike mails) and saved links.

Acceptance: **T-LINK, T-QUAR** pass; **T-PACK, T-RESOLVE, T-EXEC** and the exam operators pass for both packs; the demo shows a verified opportunity tracked and a fictional lookalike held back with sources.
Cut line: **Reading is cut first**; keep Radar.

### Phase 9: API and dashboard (14-25 Oct, parallel from Phase 5)

**Goal:** a clear, polished product experience.
**Read:** `CONTRACT.md` section 9; `USER_FLOW.md`; [`FRONTEND_IMPLEMENTATION_PLAN.md`](FRONTEND_IMPLEMENTATION_PLAN.md) (required design and navigation brief); `DEMO_AND_SUBMISSION.md` section 2; `TEST_PLAN.md` (T-API).

Tasks:
- [ ] All endpoints in `CONTRACT.md` section 9 (build over fixtures first, then real data).
- [ ] Build the five primary destinations and screen groupings in `FRONTEND_IMPLEMENTATION_PLAN.md`; use `USER_FLOW.md` for individual journeys and copy. Keep Radar conditional on its pack/API being active; Reading is cut first and must not appear as a working destination in v1.
- [ ] Scores and historical agreement are task/action-specific in the UI; never show one overall trust or accuracy score. The current report-card contract is family-scoped, so raise the Contract Change Request described in `FRONTEND_IMPLEMENTATION_PLAN.md`. Implement the task-specific backtest score only if the change is approved and the API returns that scope; otherwise label it unavailable. Do not invent the score in the browser.
- [ ] Deliver Queue (digest and respond), item detail (why, similar cases, draft), Actions (cancel/undo), Permissions (per task/action evidence), and grouped Insights/More views for report card, habits, chains, exams, metrics, exposure, ledger verification, settings, and replay controls, following the plan and actual API readiness.
- [ ] Empty, loading and error states; responsive layout (judges may use a phone).

Acceptance: **T-API** passes; the five demo beats run in the browser without console errors.
Cut line: Habits, Chains and Exposure pages may be simple read-only tables.

### Phase 10: Evaluation (22-26 Oct)

**Goal:** honest numbers.
**Read:** `EVALUATION_PLAN.md`.

Tasks:
- [ ] Baseline B3 (LLM-confidence), ablations, main run over the personas (stay inside the budget guard).
- [ ] Optional human study.
- [ ] `results.json`, tables and figures; fill the README results section.

Acceptance: **T-EVAL** passes; aggregate results committed under `docs/results/`; spend within `BUDGET_HARD_LIMIT_USD`.

### Phase 11: Deploy on Nebius and demo build (24-27 Oct)

**Goal:** a public demo that cannot embarrass us.
**Read:** `TECH_STACK_AND_REPO.md` section 6; `SECURITY_PRIVACY.md` section 5.

Tasks:
- [ ] Dockerfiles, compose, `vm-setup.sh`; HTTPS; replay service with saved LLM answers.
- [ ] Per-IP rate limits; budget kill-switch; no real data anywhere.
- [ ] Optional sandbox lock if the spike succeeded.
- [ ] `ledger verify` on the demo database; smoke test from a phone on mobile data.

Acceptance: demo URL works from a fresh browser; kill-switch tested; ledger verifies.

### Phase 12: Polish and submission (26-29 Oct)

Tasks: README with architecture diagram and results; LICENSE; 3-minute video; Devpost text; tools feedback; secrets scan; fresh-clone test; **submit on 29 Oct**.
Acceptance: every box in `DEMO_AND_SUBMISSION.md` section 4 ticked.

### Stretch S: dropped

The GitHub pack was replaced by Phases 6b and 8b.

---

## 3. Slip rules

If any phase finishes more than 2 days late, cut in this order:

1. Reading Triage pack (keep Radar and the vetting service).
2. Optional sandbox lock.
3. Human study.
4. Habits, Chains and Exposure pages become read-only tables.
5. Chain `CREATE_TASK` (keep reply and block time).
6. Ablations beyond the two most informative.

**Never cut:** ledger and its tests, the Tavily entity-vetting service and its first runtime call (bonus eligibility), the no-peeking test, the exam board, the files pack, and the core chain demo (reply plus block time). They are what make this more than an email tool.

---

## 4. Daily rhythm

- Morning (human): pick the phase task list; start agents (`AGENT_PLAYBOOK.md`).
- During: agents work on separate branches; `make check` before every commit.
- Evening (human): review handoff reports, merge what passes, update the tracker below, note anything for `DECISIONS_AND_OPEN_QUESTIONS.md`.

---

## 5. Progress tracker

| Phase | Status | Started | Finished | Notes |
|---|---|---|---|---|
| 0 | not started | | | |
| 1 | not started | | | |
| 2 | not started | | | |
| 3 | not started | | | |
| 4 | not started | | | |
| 5 | D2 integrated; D3 email accepted; whole phase open | 24 Oct 2026 | | D3 gate: 833 tests pass; see reports/phase-5-d3.md. Whole WP6 and live connectors/frontend remain separate gates. |
| 6 | not started | | | |
| 6b | not started | | | |
| 7 | not started | | | |
| 8 | not started | | | |
| 8b | not started | | | |
| 9 | not started | | | |
| 10 | not started | | | |
| 11 | not started | | | |
| 12 | not started | | | |
| S | dropped | | | |
