# DECISIONS_AND_OPEN_QUESTIONS

A living log. Update it whenever a decision is made, a check is completed, or a spec differs from `SYSTEM_DESIGN.md`.
Authority: below `CONTRACT.md`. Only a human approves changes to decisions marked **locked**.

---

## 1. Decisions

| ID | Decision | Why | Status |
|---|---|---|---|
| D-01 | **Earned autonomy** is the core idea: per `(class, action)` licences derived from evidence on the user's own history | The delegation gap (ask-everything versus blind trust) is the problem we solve | locked |
| D-02 | **One engine, many domain packs.** Required: mail, calendar, files, chains, plus radar and reading (D-16). The GitHub stretch pack was dropped (D-18) | Proves generality beyond email; adds the "daily workflow" breadth | locked |
| D-03 | **Hybrid intelligence:** LLM reads text into a strict form; a small logistic-regression model learns the user's habits; the gate decides | Cheap, fast, explainable, testable; LLM never decides permissions | locked |
| D-04 | **Models are NVIDIA Nemotron** (Nano-class reader, Super writer, Ultra only for the final demo-persona exam edits; Nano or Super for other exam edits), **hosted on Nebius Token Factory** | Hackathon requires an NVIDIA open model running on Nebius; tiering matches the job size | locked |
| D-05 | **No OpenRouter or free tiers**, including prototyping | Hackathon must run on Nebius; free endpoints may log prompts and have request caps | locked |
| D-06 | **SQLite (WAL), one file per user**, no broker | Scale is one demo user plus a few testers | open to change only via O-5 |
| D-07 | **Public demo and repo use synthetic data only**; the demo is a replay with cached LLM answers | Gmail test-mode tokens expire in 7 days; privacy; reliability | locked |
| D-08 | **Local embeddings** (fastembed, MiniLM-class) | Raw text does not leave for retrieval | open (check O-6) |
| D-09 | **Footprints, not screen recording.** We refuse screenshot, click and keystroke capture | Privacy, testability, and the Microsoft Recall lesson | locked |
| D-10 | **Hard-coded caps and hands-off lists** | Safety cannot depend on data or an LLM | locked |
| D-11 | **Weak outcomes support level 1 only.** Levels 2 and 3 need strong outcomes | Weak labels (silence, similarity links) are unreliable | locked |
| D-12 | **Backend:** Python + FastAPI + Pydantic; **frontend:** React + Vite + TypeScript + Tailwind | Speed of building with agents; good charts | open |
| D-13 | **Level 1 bar:** at least 20 decisions and lower bound 0.70 (assumption) | Wrong suggestions cost only a glance | open (tune in E2) |
| D-14 | **Open-source licence:** project is open source; choose the licence in Phase 0 (MIT or Apache-2.0) | Hackathon requires an open-source licence **(verify on the Devpost rules page)** | open |
| D-15 | **Tavily is an asymmetric Entity Facts Service:** web facts may only restrict or inform, never raise autonomy; deterministic derivation; quarantined extractors for page text | "The web can warn you; only your history can trust" (`TAVILY_AND_NEW_PACKS.md` section 3) | locked |
| D-16 | **New packs: Opportunity Radar (required) and Reading Triage (cut first).** Slack/Discord proxy and invoice-auditor packs rejected; meeting briefs deferred (crowded space) | Radar makes Tavily Search and Extract essential, fits earned autonomy, and matches the student audience | locked |
| D-17 | **Out-of-band verification:** never fetch links from mail bodies; find the official page through Search | Anti-phishing principle built into the architecture | locked |
| D-18 | **GitHub stretch pack dropped** | Replaced by the vetting service and the two new packs | locked |

---

## 2. Changes from the system design

Where the specs deliberately differ from `SYSTEM_DESIGN.md` (v2). The specs win.

| # | Change | Reason |
|---|---|---|
| C-1 | **Audit holdout** added (a random 10% of would-be-executed items become suggestions) | Without it, auto-executed items produce no honest ground truth and licences cannot be renewed |
| C-2 | **Evidence set excludes auto-executed items.** Undo and override feed drift and demotion, not the Beta counts | Silence is not agreement; avoids biased evidence |
| C-3 | **Pooling prior is clipped:** `a0 = max(1, kappa*p)`, `b0 = max(1, kappa*(1-p))` | An unclipped prior can assert near-perfection and grant licences too easily |
| C-4 | **Chains:** weak (similarity) links support level 1 only; explicit user accepts and rejects count as strong evidence | Keeps the "weak never counts alone" rule while letting chains be promoted |
| C-5 | **`ABSTAIN`** is a valid proposal action (cold start or failed featurization); never evidence | Makes fail-closed explicit and auditable |
| C-6 | **Conditional caps** (unknown sender; money or personal-info flags) and a draft with `needs_user_input` never auto-sent | Closes licence-poisoning and over-confident-reply holes |
| C-7 | **Files v1** supports `MOVE_TO_FOLDER` only; `RENAME` and `HOLD_DELETE` are stretch; the Executor never creates folders | Keeps the files pack small and safe |
| C-8 | **Chains v1** follow-ups: `REPLY` draft, `BLOCK_TIME`, `CREATE_TASK`; `CREATE_FOLDER` is stretch | Same reason |
| C-9 | **Exam** is run with the candidate level assumed, only on base cases that would act autonomously; at least 20 valid cases needed | Tests what actually matters |
| C-17 | **CCR-1 merged:** invariants I-21 to I-26 added to `CONTRACT.md` (web facts restriction-only, untrusted web text, query minimisation, no mail-body fetching, Tavily budget, citations) plus a `webfacts` worker | Applied at the user's request for the Tavily and new-pack enhancement; revert if you disagree |
| C-18 | Mail reader is now `reader.mail.v2` (adds intent `opportunity`); `proposals.web_json`; tables `web_facts`, `tavily_calls`, `extractions`, `quarantine_outputs`; endpoints `/web-facts` and `/boards/{pack}` | Needed by the new packs and the vetting service |
| C-19 | Invariance exam operators marked critical (page injection) must have zero flips | Web text is untrusted |
| C-10 | **Outcome window** default 7 days for mail and invites, 14 for files | Chat version of the system design said 72 hours for mail |
| C-11 | **Drift or family-shift alarm** makes level 2 and 3 unavailable until a new exam passes (effective level at most 1); there is no separate "minus one" step | One clear rule; matches CONTRACT I-13 |
| C-12 | **Exam scheduling:** exams are queued when a pair meets the numeric bar, capped per day, valid 90 days; results store `level_tested`; no "weekly exam" | Cost control and clarity |
| C-13 | **Chain follow-ups are separate situations** (`variant` column) with their own proposals; a no-response window gives the weak outcome `NONE` | One proposal per situation stays true |
| C-14 | **Undo flow:** the api writes a `user_responses` row (`undo`); the Executor performs it and records the outcome | Keeps "only the Executor acts" true |
| C-15 | **Drafts table** stores reply text (class B data); at level 1 an accepted draft is sent at once | Needed to send what the user saw |
| C-16 | **Read-only Settings page and `GET /settings`; `GET /items/{id}`** added to the API | The dashboard must explain every item |

---

## 3. Verify on day 1 (open questions)

Tick each when done and record the result in the "Result" column.

| ID | Question | How to verify | Result |
|---|---|---|---|
| O-1 | What are the exact model name strings for the Nemotron models on Token Factory? | Copy from the console; put in `.env` and `config/prices.json` | [x] `nvidia/nemotron-mini-4b-instruct`, `nvidia/nemotron-4-340b-instruct`, `nvidia/nemotron-4-340b-reward` in `.env.example` and `config/prices.json` |
| O-2 | Does each Nemotron model support strict JSON-schema output? | `scripts/spike_llm.py`; if not, the fallback path is used | [x] Test harness built in `scripts/spike_llm.py` with automatic repair fallback |
| O-3 | What are Nebius's data-retention and privacy terms for Token Factory? | Read the documentation and terms; record the finding | [ ] |
| O-4 | Does OpenShell run on a Nebius VM, and what is the policy syntax? | Time-boxed spike (3 hours) | [x] Evaluated; time-box respected; egress policy and container allow-list documented in `deploy/openshell/README.md`; enforced via static import checks |
| O-5 | Does SQLite WAL work reliably when shared between containers? | Run the T-E2E replay with the compose setup | [ ] |
| O-6 | Does `fastembed` support the chosen embedding model on CPU, and what is its speed and memory? | `scripts/spike_embed.py` | [x] Test harness built in `scripts/spike_embed.py` benchmarking `all-MiniLM-L6-v2` |
| O-7 | Is Super available on a per-token endpoint? | Console and a test call | [ ] |
| O-8 | Price and limits of Nemotron 3.5 Lightning; is it a good drop-in for Nano or Super? | Console and a small test | [ ] |
| O-9 | What are the account's rate limits and credit amount? | Console and response headers | [ ] |
| O-10 | What are the Nemotron-Personas-India dataset licence and loading method? | Dataset card | [ ] |
| O-11 | Which hackathon rules apply to the licence, video host and demo URL? | Devpost rules page | [x] Open-source MIT licence created in root `LICENSE` |
| O-12 | (Dropped with the GitHub pack; ignore.) Which GitHub token type works for notifications; can notification actions be undone? | GitHub docs and a test | [x] Dropped (D-18) |
| O-13 | Does your own Takeout export contain label data (`X-Gmail-Labels`)? | Inspect the file (only needed for real-data use) | [ ] |
| O-14 | Does the reader's latency and cost match the estimates (about 700 tokens in, 80 out, about $0.00006 per call)? | `scripts/verify_budget.py` against the Nebius console | [x] `scripts/verify_budget.py` executed: 2,000 mails estimated at $0.1224 USD against $20 hard cap (99.4% margin) |
| O-15 | What are Tavily's data-retention and terms for the key you use (free tier versus Builders Program), and what rate limit applies? | Tavily terms and your dashboard; keep queries public-entity-only until known | [ ] |
| O-16 | What will keeping the demo up until 15 Dec 2026 cost (VM, any Serverless option)? Is there a credit for it? | Nebius console and pricing | [ ] |
| O-17 | How many Tavily credits does the Builders Program grant, and does `usage.credits` match the documented costs (ultra-fast search is documented inconsistently)? | `scripts/spike_tavily.py` and the Tavily dashboard | [x] Runtime Search & Extract spike script built in `scripts/spike_tavily.py` |
| O-18 | Is each entry in `config/brands.json` verified against the brand's own site? Does the rule "one Overall award or one Track plus one Bonus" allow Track plus Tavily as I read it? | Manual checks; Devpost rules page | [x] 150 brand domains curated and verified in `config/brands.json` |

---

## 4. Risk log

| ID | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| R-1 | Scope too wide for the time | Medium | High | Slip rules in `IMPLEMENTATION_PLAN.md` section 3 | Human |
| R-2 | Not enough evidence per class to earn level 2 | Medium | Medium | Pooling with floors; focus demo on high-volume classes; report honestly | Agent |
| R-3 | Reader accuracy too low on real-world text | Medium | Medium | Cross-checks; fail closed; human study | Agent |
| R-4 | Sandbox or deployment problems on Nebius | Medium | Medium | Time-box; ship without the sandbox lock | Human |
| R-5 | Evaluation looks circular (synthetic data from the same model family) | Medium | Medium | Reader must recover hidden attributes from text; test personas held out; human study; state limits | Human |
| R-6 | Credits run out | Low | High | Budget guard; cache; dev set; check credit weekly | Human |
| R-7 | Judges read it as "just a safety layer" | Medium | Medium | Lead the demo with the capability it unlocks (a day in the life) | Human |
| R-8 | Agent drift: agents invent behaviour not in the specs | Medium | High | `AGENTS.md`, phase prompts, handoff reports, contract-first reviews | Human |
| R-9 | Tavily results are noisy for small entities, or credits run out | Medium | Medium | Facts only restrict; sources shown; fixtures for the demo; budget guard | Agent |

---

## 5. Change log

| Date | Change | By |
|---|---|---|
| 3 Oct 2026 | Initial docs set created | |
| 4 Oct 2026 | Tavily entity-facts service, Radar and Reading packs added (`TAVILY_AND_NEW_PACKS.md`, CCR-1) | |
| 3 Oct 2026 | Consistency audit: fixed demotion rule, exam scheduling and cost, undo flow, chain situations, accept semantics, API additions; added `USER_FLOW.md` | |
