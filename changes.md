# Probation: Full Codebase Audit and 8-Day Ship Roadmap

*Audited: `Probation-main.zip`, 22 Oct 2026. Deadline: 30 Oct 2026, 10:00 am PDT (10:30 pm IST). Safe target: submit on 29 Oct, which leaves 8 working days including today.*

## 0. Method, and how far to trust this

I read the whole docs suite, then every layer of code (core, db, llm, engine, packs, workers, web and links, API, frontend, synth, eval, tests, scripts). Then I **ran it**: installed backend and frontend, ran the project's own checks, generated a tiny and a full synthetic persona (2,900 situations), imported, ingested, replayed, called the API with a test client, and tested individual suspicions in isolation. Every number below comes from those runs unless marked *(from code)*. I had no Nebius or Tavily keys, so live behaviour of those services is listed in section 15 as unverified.

Anything I changed in my sandbox copy (overwritten fixtures, results files) does not touch your zip.

## 1. Verdict

Your instinct is right on both counts.

1. **There is no connection to real tools.** No MCP client, no Gmail, Notion, Calendar or OAuth code, no polling loop, no `serve` command in the CLI. The spec itself defers this (live connectors are marked stretch; 'own data' is instructions only), so the agents built what the docs said. The docs, not the agents, left out your vision.
2. **The earn-permission loop never closes.** On a full persona (3,989 situations) the system made 0 autonomous actions, ran 0 exams and earned 2 level-1 licences. The Accept and Undo buttons write a database row that nothing reads.

What is genuinely good: the SQLite schema is verbatim from the spec; 198 tests pass; ruff is clean; the gate order and the lower-bound maths match the spec exactly; ledger triggers work; redaction is solid for its scope; the frontend typechecks and builds; the visual system is coherent. The foundations are decent. The wiring between them is what is missing.

The biggest danger is not missing features. It is **credibility**: hard-coded evaluation numbers, an exam that cannot fail, and UI status text that is not real. A judge who opens the results file or the repo will punish those more than any missing feature.

## 2. Scorecard

| Area | State |
| --- | --- |
| Spec docs | Strong; a few contradictions (section 11) |
| DB schema, ledger triggers, hashing | Good |
| Gate, lower-bound maths, caps table | Good, except the `:param` bug (P0-2) |
| LLM client | Works in isolation; never run against Nebius; hides the real error on failure |
| Reader / writer / wording / exam-edit prompts | Mostly not wired (2 of 14 prompt files exist; none is loaded) |
| Replay engine and policy | Runs; below the trivial baseline; autonomy path crashes |
| Evidence, licences, exam, drift | Code exists; not trustworthy end to end |
| Mail, calendar | Code complete; runs reader-less in practice |
| Files | Generator never renders the moves, so nothing is learnable |
| Chains, habits | Mining code exists; not demonstrated |
| Tavily vetting | Client and derivation exist; many false vetoes; Radar flow is dead code |
| Radar, Reading | Mostly stubs and dead code |
| API | Most contract routes exist; several return wrong or empty data |
| Frontend | Polished look; built against fixtures, not the real API shape; several controls do nothing real |
| Evaluation | Not valid (P0-6) |
| Deployment | Not started |
| Live connectors, MCP | Absent |

## 3. What the hackathon asks for versus what the repo shows

From the Devpost rules, overview, resources and the two organiser posts I read today:

- **Personal AI track brief:** an always-on, private assistant with persistent memory, reusable skills, access to tools and information you choose, doing tasks across daily workflows; at least one NVIDIA open model. NVIDIA tools named as examples: NemoClaw, OpenShell, Hermes Agent, Nebius Serverless. An organiser post adds that they hope to see an assistant that remembers across sessions and takes real action for you.
- **Judging:** a pass/fail theme-fit stage, then four equally weighted criteria scored 1 to 5: technological implementation (how effectively you use Token Factory and Nemotron), design, potential impact, quality of the idea. The judge list includes Tavily staff.
- **Prizes:** one Overall, or one Track plus one Bonus (the Tavily prize is a Bonus). Your docs read this correctly.
- **Submission:** public repo with an open-source licence visible in About; public video of at most 3 minutes that clearly names Token Factory and the NVIDIA model; a working demo URL that stays free until judging ends on 15 Dec; written tool feedback. The rules also bar third-party trademarks and copyrighted music in the video, so do not show real brand names or logos in the lookalike demo.
- **Credits** (resources page, as I read it): $25 through a form plus $25 more through the Builders Program. Confirm in your console.

| Requirement | Repo today |
| --- | --- |
| Always-on, tools you choose | Replay on synthetic data only |
| Nemotron used effectively | Zero real LLM calls in any committed result (0 calls, $0.00) |
| NVIDIA tools | One OpenShell README; no policy, no demo |
| Runs on Nebius | No Dockerfile, compose file, VM script or demo URL |
| README content | No architecture diagram, results, Nemotron or Tavily section (your own checklist requires them) |
| Tavily best use | Vetting is CLI-only; the Radar Search+Extract flow has no callers |

## 4. What I ran, and what happened

| # | Experiment | Result |
| --- | --- | --- |
| E1 | `pytest` | 198 passed |
| E2 | `ruff check`, `ruff format --check` | Clean |
| E3 | `mypy` (what `make check` runs) | **4 errors, so `make check` is red**: `packs/mail/resolver.py:96`, `workers/resolver.py:55` (`WorldView` has no `user_addresses`), `packs/mail/__init__.py:94`, `packs/calendar/__init__.py:67` (None assigned to `list[str]`) |
| E4 | Frontend `npm ci`, `tsc -b`, `vite build` | Pass; 300 kB JS. No lint script, no tests |
| E5 | `make synth` as documented | With no `--out` it **overwrote the committed `tests/fixtures/tiny_synth`** |
| E6 | Running pytest | **Rewrote `docs/results/main.json` and `tables.md`** (the committed 167-situation results became a 0-situation file) |
| E7 | Tiny persona, documented flow (import, ingest, backtest) | 169 proposals but report card says Evaluated 0: the resolver uses the default `Clock()`, a fixed 2026-01-01, so no outcome window ever closes; only 45 REPLY footprints resolve |
| E8 | Tiny persona, resolver given a proper as\_of | 142 evaluated; agreement 62% versus majority baseline B0 89%; 29 drift alarms, all for `ABSTAIN`; ledger holds all 266 outcomes at seq 1-266 and the first proposal at seq 267 |
| E9 | Full persona (3,989 situations) | Ingest 280 s (quadratic); replay 27 s; 2,109 evaluated; **agreement 83.8% versus B0 90.6%**; 0 EXECUTE decisions; 0 actions; licences: 28 at level 0, 2 at level 1; 0 exam runs; 380 drift alarms (253 not ABSTAIN) |
| E10 | Same run with the answer-key stub reader | Identical numbers. Cause: **0 of 2,900 truth.json ids exist in the DB** (tiny: 0 of 200). The truth file cannot be joined to the engine's situations |
| E11 | Files family | 600 ABSTAIN, 600 weak LEAVE outcomes. The rendered world keeps all 600 files in `Downloads/`; truth.json assigns MOVE\_TO\_FOLDER actions that are never rendered |
| E12 | Executor creates an action before its proposal row exists | `IntegrityError: FOREIGN KEY constraint failed`. Replay calls the executor before `INSERT INTO proposals`, unguarded; no test reaches it |
| E13 | Exam on class `mail\|other\|automated` / ARCHIVE | Passed: 248 cases, 0 violations (policy=None). It sampled 17 mail, 4 calendar and 4 files situations |
| E14 | API on the full DB | Queue returns 545 items back to January; licences: 30 rows, 25 of them `ABSTAIN`; item explanation empty; `head_hash` differs from the true ledger head |
| E15 | Lookalike check with the real `brands.json` | Flagged as lookalikes: `amazon.in`, `google.co.in`, `vit.ac.in` and `iitm.ac.in` (both 'of citi.com'), `zoho.in` ('of zoom.us'), `microsoftonline.com`, `githubusercontent.com` |
| E16 | Query guard on the spec's `vet_report` query | Rejected (the query contains double quotes). That call can never be sent |
| E17 | `is_recallable('MOVE_TO_FOLDER:College/Lab')` | `False`; loss 10 (spec: recallable, loss 5) |

## 5. P0 blockers: the demo cannot be honest until these are fixed

**P0-1. No real-tool connection and no always-on loop.** Evidence: no MCP, Gmail, Notion or OAuth code anywhere; `workers/scheduler.py` is functions only; API replay start/pause/speed flip in-memory flags and drive nothing *(from code)*. Fix: section 12.

**P0-2. The loop never closes, and the executor is unsafe.**

- Nothing reads `user_responses`: Accept, Edit and Undo are write-only. `Executor.process_undo` has zero callers. Accepts never create a STRONG outcome, so explicit-feedback evidence (spot checks, chain accepts) cannot exist.
- E12: any autonomous gate crashes the replay.
- `create_action` uses `INSERT OR REPLACE`, which resets a DONE action to PENDING (double-act risk, breaks CONTRACT section 8 idempotency). Undo uses `INSERT OR REPLACE INTO outcomes`, which overwrites the user's original outcome.
- `get_action_loss`, `is_recallable` and the licence cap do not strip `:param`, so every file move is non-recallable with loss 10 (E17). Level 3 is impossible and level 2 uses a 10-minute hold.
- Fix: add `workers/responder.py` that consumes `user_responses` (accept/edit creates an immediate action; undo/cancel runs `process_undo`) and writes a STRONG outcome. Insert the proposal first, in the same transaction. Use `INSERT OR IGNORE` plus a status guard. Strip `:param` in one helper used everywhere. Outcomes are one row per situation, so decide how an undo is recorded (ledger event plus drift input) and log it as a Contract Change Request.

**P0-3. The data layer does not line up, so nothing downstream can work.** E8-E11: truth ids never match DB ids; DB has more situations than truth (2,845 mails versus 2,000, 544 invites versus 300); mail classes collapse into four keys (`mail|other|frequent` covers 2,527 of 2,845); the full persona shows 0 REPLY outcomes (the tiny one shows 45; I did not find why); file moves are never rendered. `eval/run_eval.py` `load_truth_data` silently falls back to the **tiny fixture's** truth if the path is wrong. Fix: key truth by something the engine reproduces (`det_id(pack, source_ref, occurred_at, family, variant)`); render replies and file moves into the world; add a test that every truth id exists in the DB and that the generator's habit adherence shows up in the resolved outcomes.

**P0-4. The reader and writer paths are hollow.**

- With no API key, every feature row has `reader_json = NULL` and `reader_ok = 1`: the reader silently does nothing and still reports success (fail-open, against I-3).
- With a key, the call uses a generic one-line system prompt (`workers/brain.py:112`). The prompt files in `llm/prompts/` are **never loaded**: no injection defence, no definitions of the intent values, no `<email>` tags, no sender type.
- Only 2 of the 14 prompt files the spec requires exist (no writer, wording, exam, extractor, digest or synth prompts).
- `habits.py`, `packs/mail/exam_ops.py` and `packs/calendar/exam_ops.py` call `llm_client.complete_json`, which **does not exist**; each is wrapped in `except Exception: pass`, so they silently use canned text. Their fallback model name is `meta-llama/Meta-Llama-3.1-8B-Instruct` (mail `exam_ops.py:169`, calendar `exam_ops.py:124`), which is not NVIDIA and breaks D-04/D-05.
- `packs/radar/digest.py:110` passes the literal `model="writer"`.
- **No reply writer exists**: nothing ever inserts into `drafts`. The Super-written reply in your demo does not exist.
- Fix: a prompt loader (front matter, version, schema); real system prompts; fail closed (`reader_required=True` for mail and calendar; failure gives ASK, not a silent SHADOW); implement the writer and its draft validator; replace `complete_json` with `chat_json`; delete the Llama fallback.

**P0-5. The exam is a placebo, so licences at levels 2 and 3 mean nothing (I-13).**

- It samples from the whole database, not the class under test (E13).
- It feeds the policy `{text, **raw payload}`, not the trained feature schema, so base and edited predictions are identical by construction.
- Base probability is hard-coded to 0.99 when no policy is given, and the nightly path (`workers/examiner.py`) calls `run_exam` with no policy, so it always passes.
- It never recomputes the cap from the edited features, so `sender_unknown` cannot lower the gate.
- Chain, radar and reading classes are mapped to the `file_destination` policy.
- The 'cheating policy fails' test uses a test double that reads `text` directly, which is circular.
- Fix: sample by `(class_key, action)`; run the real pipeline per edit (redact, reader, clues, policy, caps, gate); pass the real policy; make LLM operators use `chat_json`; add a test in which the real trained policy is made to depend on a keyword and must fail.

**P0-6. Evaluation results are not valid, and some are fabricated.**

- `eval/run_eval.py` lines 415-419 hard-code the ablation outputs (0.042, 3 violations, 0.035, 0.185, 0.071). These literals are in the committed `main.json`, `tables.md` and quoted in `docs/reports/phase-10.md` ('+7.1% false licence elevation').
- The committed run covers 167 situations, not 20 personas x about 3,000. Probation agreement 80.84% versus B0 83.23%. Attention 100 per 100 (it asks about everything; autonomous coverage 0). LLM calls 0, Tavily calls 0. Chain precision and recall 1.0 with zero chains; exam pass rate 1.0 with zero exams. B3 is not an LLM baseline.
- Fix: delete the literals; implement ablations as real flags; run at least 5 personas on the corrected pipeline with a real reader (cached); write results to a temp path in tests; state negative results plainly.

**P0-7. The ledger does not prove commit-before-reveal.** The resolver pre-pass appends every outcome before the first proposal (E8). `GET /api/ledger/verify` returns a wrong `head_hash` (a bare column next to an aggregate; E14). `append_ledger` calls `conn.commit()` mid-flow and bypasses the role helper. Exam run ids are `uuid4`, so same-seed runs cannot give the same head hash. Fix: resolve outcomes day by day inside the replay (`resolve_outcomes(as_of=event_time)`); use `SELECT hash ... ORDER BY seq DESC LIMIT 1`; use deterministic ids.

**P0-8. Drift alarms are noise.** E8, E9: 29 and 380 alarms. CUSUM treats `ABSTAIN` and weak LEAVE outcomes as errors. The PSI check uses the alphabetically first 5 feature keys, not the top-coefficient features the spec asks for (it can never see `start_hour_bucket`, the planted drift in your demo). Covariate PSI cannot see behaviour drift by definition; CUSUM must carry that beat. Fix: skip ABSTAIN and SHADOW; count only strong outcomes on evidence-bearing proposals; pick PSI features from the fitted model.

**P0-9. Tavily is mostly not wired.** See section 8.

**P0-10. Hygiene that will embarrass you.** `make check` is red (E3); `make synth` overwrites committed fixtures (E5); pytest overwrites results (E6); `.gitignore` lacks `build_history/` although the protocol says it must never be committed; CLI deviates from CONTRACT section 10 (`import` takes a positional path, not `--source`; no `probation serve`); the decision log has had no entry since 4 Oct although the code deviates from the spec in many places (section 6); the Phase 10 report cites `mypy --strict` on a subset only.

## 6. P1: spec deviations and engine-integrity issues

- **Calibration is in-sample.** The temperature is fitted on the training rows, not out-of-fold as the spec says. That makes p\_max overconfident, and p\_max feeds the economic test in the gate.
- **Cold start is 20, not 200.** `policy.py` uses `l1_min_n` (20), and `config.py` also sets `cold_start_min_situations = 20` against the spec's 200.
- **Novelty uses TF-IDF, not MiniLM embeddings, and `>=` instead of `>`.** With reused synthetic bodies the threshold can collapse to 0 and flag everything as novel.
- **Tunables:** `config.py` omits several spec tunables (`LICENCE_MIN_RECENT_N`, CUSUM allowance, `HOLD_MINUTES`, window sizes) and the engine hard-codes them, against CONTRACT section 11. `l2_min_n` and `l3_min_n` are unused.
- **Gate inputs are wired constant:** `budget_ok=True`, `reader_required=False`, `deterministic_ok=True`, so the reader/header cross-check never runs and the budget guard never reaches the gate.
- **Web veto** is applied to files too (the spec limits it to mail and calendar, plus radar and reading).
- `check_exam_ok` family map misses radar, reading and chains, so shift alarms never invalidate their exams.
- **Habit mining peeks:** it filters situations by `occurred_at` but does not require `outcome.known_at <= as_of`. It also mines tautological clues (`reply_rate_sender`) and prints raw feature names in the statements.
- **Report card:** `ABSTAIN` counts as 'different' (47 of 142 in E8), which deflates the headline.
- **Mail clues are O(n^2)** per situation (nested loops over prior raw items and situations); 4,000 situations take 280 s. Twenty personas would take about 90 minutes of CPU before any LLM call.
- **LLM client:** any non-200 (401, 404, exhausted 429) permanently disables structured mode for that model and then raises a generic 'failed to obtain valid JSON'; a wrong model name will look like a schema problem. `ConnectTimeout` is not retried. `LLM_MAX_CONCURRENCY` is unused, so calls are sequential. The `openai` dependency is unused.
- **Redaction:** the mail pack never passes `display_names`, so PERSON redaction never happens, and the prompt lacks the sender type the spec defines.
- **Mail pack:** `USER_ADDRESSES` blank gives `['']`, and `'' in anything` is true, so every mail is treated as the user's own and silently dropped. Address matching uses substring containment.
- **Roles:** the executor writes `drift_state` and `outcomes` directly; `POST /habits/{id}/deny` writes `habits` from the API process; the executor trusts the cached licence level instead of re-deriving it (I-10).
- **Ledger payload keys** differ from DATA\_MODEL (`prev_level` versus `old_level`), so the API's licence history shows `old_level` as null.
- **Tavily budget** counters use the real clock while calls are logged with simulated times, so the guard never trips in replay.

## 7. Frontend and API connection audit

### 7.1 Which backend routes the UI actually uses

| Backend route | UI status |
| --- | --- |
| `GET /health` | Used, but the header chip says 'AI systems online' as hard-coded text (Header.tsx:21, QueueView.tsx:127) |
| `GET /report-card` | Used for `email_action` only (App.tsx:91). Invite and file families are never shown |
| `GET /queue` | Used; real data does not have the fields the UI renders (see 7.3) |
| `GET /items/{id}` | **Not used.** `getItemDetail` exists in the client and is never called |
| `POST /queue/{id}/respond` | Used; **nothing consumes the row** (P0-2) |
| `GET /actions`, `POST /actions/{id}/undo` | Used; undo is a no-op |
| `GET /licences` | Used; wrong levels and junk rows (E14) |
| `GET /habits`, `POST /habits/{id}/deny`, `GET /chains` | Used |
| `GET /exams`, `POST /exams/run` | Used; run button defaults to a hard-coded class and the API may substitute another one |
| `GET /metrics/summary`, `/boards/radar`, `/exposure`, `/ledger/verify`, `/settings` | Used; data gaps in 7.2 |
| `GET /web-facts` | **Not used.** The Tavily transparency page does not exist in the UI |
| `GET /replay/state`, `POST /replay/{start,pause,speed}` | **Not used**, and the backend only flips in-memory flags |

### 7.2 APIs that are missing or must change

1. **Queue:** add `as_of`, `limit` and `cursor`; exclude items that already have an outcome or a response (today: 545 items back to January); return `subject`, `sender_display`, `action_label`, `allowed_actions`, `risk_reason`, and a `draft` object. The summary is currently the redacted text with `<PERSON_1>`-style placeholders.
2. **Explanations:** nothing ever writes `explanation_json` (top clues, three similar cases). Generate it when the proposal is written: top clues from coefficient x value, three nearest training cases, the evidence line.
3. **Licences:** read `licence_cache`, the latest exam and the cap instead of re-deriving without them. Add `cap`, `cap_reason`, `exam {passed, finished_at, level_tested}`, `alarm`, a human title. Hide no-op and ABSTAIN actions.
4. **Respond:** add `edited_body` (the UI edits a draft that is then thrown away) and validate `edited_action` against the family's catalog.
5. **Responder worker** (backend, P0-2) and a **connections API** (section 11): `GET /connections`, `POST /connections/{kind}`, `POST /connections/{id}/sync`, `DELETE /connections/{id}`.
6. **Replay:** either implement a time cursor (`as_of`) on the read endpoints and let the UI play it, or remove the controls. Recommended: the time cursor. It is truthful, cheap, and gives you the 'day in the life' beat from a precomputed DB.
7. **Settings** must also return caps, losses and the hands-off list (CONTRACT section 9 requires them). **Exposure** needs per-item counts and the share of items handled with zero calls.
8. **Report card:** add `as_of` and period; stop returning a blended `accuracy` for `family=all` and a blended `agreement_rate` in `/metrics/summary` (your own rule is no overall score). The per-task rows you wanted already exist in the response, so the Contract Change Request in the frontend plan is moot.
9. **Safety:** remove the substitution hack in `POST /exams/run`; put a token on admin routes; restrict CORS (it is `*` with credentials); add pagination to queue, actions and exams.
10. **Actions:** return `undo_until`, `can_undo`, a readable target and remaining hold time.

### 7.3 Frontend problems (all verified in code)

- **Built against fixtures, not the real API.** `risk_level`, `action_headline`, `requested_time_ago` and `metadata_table` do not exist in the real response. With real data the headline is the redacted text blob, and the risk pills are invented by the UI from `cap`.
- **Fake status:** 'AI systems online' and 'Replay up to date' are literal strings.
- **Draft edit is cosmetic:** the edited text is never sent. 'Choose different action' is a free-text box (a user can type SNOOZE).
- **Jargon the spec forbids:** 'Autonomy: L2', 'Gate:', raw `class_key` strings, ABSTAIN rows on Home and Permissions.
- **A wrong claim:** Home says 'Clopper-Pearson 95% lower bound'. The engine uses the 5% quantile of a Beta(1+k, 1+n-k) posterior (for k=n that is 0.05^(1/(n+1)); Clopper-Pearson gives 0.05^(1/n)). Say 'Bayesian lower bound'.
- **No routing:** the view lives in React state. Refresh loses your place; no back button; no deep link.
- **Accessibility:** the inspect modal has no dialog role, no Escape, no focus trap; no `aria-live`; no reduced-motion handling.
- **Untrusted URLs** from Tavily results are rendered as `href` without a scheme check (QueueView.tsx:396, RadarView.tsx:115). Allow only http and https.
- **Queue shape:** the API's `digests` are ignored (they appear only in preview fixtures); no 'Needs you' and 'Ready for you' sections; no 'Spot check' wording.
- **State handling:** TanStack Query is installed and unused; nothing refreshes; accepting an item does not update Actions or Permissions.
- **No lint, no tests.**
- **Keep:** typecheck and build pass, the palette and layout are coherent, five-destination navigation matches the plan.

## 8. Tavily audit

Works: client with call logging, query guard, local brand list, EntityFacts derivation with tests, restriction-only `WebFactsView` with isolation tests.

1. **Radar's Search + Extract flow is dead code.** `verify_opportunity_out_of_band` has zero callers. The 'quarantined extractor' is validators only: no prompt, no LLM call; the fields come from a hard-coded dict and regex. The official candidate is the first search result from any domain.
2. **Vetting is CLI-only.** Replay never calls Tavily. The `webfacts` worker vets every sender domain (credit burn) instead of the spec's triggers (unknown sender, unfamiliar link domain), never vets link domains, and never stores the display-name brand token.
3. **False vetoes (E15).** `is_lookalike` compares a sender label with every brand in the list using edit distance 2 on labels of 3+ characters, plus a containment rule. Fix: compare only against the matched brand; keep official domain sets per brand (regional TLDs such as amazon.in, google.co.in); edit distance only for labels of 6+ characters; never flag a domain in `known_domains`. Run your own E10 on about 60 real Indian student domains.
4. **`brands.json` entries need checking:** generic-word tokens (`x`, `box`, `meta`, `wise`, `square`, `linear`, `monday`) will match unrelated senders; `bitbucket` maps to `atlassian.com`. Your doc requires every entry verified against the brand's own site.
5. **The `vet_report` query is rejected by your own guard** (E16). Docs bug: TAVILY section 5.4 contradicts PROMPTS section 15. Drop the quotes and the OR.
6. **Extract:** no budget check (I-25); the vetting gate compares `hostname` (with `www.`) to registrable domains, so subdomains bypass it; it ignores `extract_depth`, `format`, `query` and `chunks_per_source`; the quarantine writer uses `datetime.utcnow()`.
7. **Validators:** the fee regex matches `cost`, `pay`, `amount`, so nearly every page is 'fee mentioned'; the date check accepts '30 Oct 2026' but not '30th October' or a date with no year, which is most event pages.
8. **Auth:** the client sends `api_key` in the body; your doc says a bearer header. Test both in `spike_tavily.py`.
9. **UI and eval:** no web-facts page; the 'Check the sender' banner shows the raw status; results show 0 Tavily calls and E10 was never run.

## 9. Nemotron audit

Today Nemotron appears only in config and scripts. No committed result contains a real call.

- **Model names disagree across the repo.** The decision log (O-1) records one set, `config.py` defaults another, and `.env.example` is blank. List the models from the live Token Factory console once and write them in one place.
- **Prompts exist for 2 of 14 jobs and none is loaded** (P0-4). There is no writer, so the most visible Nemotron moment in your story (a reply in the user's voice) does not exist.
- **Reasoning tokens:** I could not test whether the chosen models spend `max_tokens` on reasoning. The client falls back to `reasoning_content` when `content` is empty, which can parse an example JSON out of the chain of thought. Test this in the first live call and set the mode explicitly.
- **Throughput:** sequential calls. At about 1 to 2 s each, 4,000 situations take hours. Use the unused concurrency setting with a semaphore.

## 10. Docs and governance problems to fix

- MEMBER\_SPLIT says to use a 'warm light theme'; the frontend plan specifies dark-only Spruce & Brass.
- CONTRACT section 9 says `respond` writes a strong outcome; section 3 says the API may write only `user_responses`. Choose one; recommended: the responder worker writes the outcome.
- CONTRACT section 5 says `iter_situations(source, since)`; the code takes one raw item. Undeclared deviation.
- The decision log has no entry after 4 Oct; O-1 and O-2 are ticked on 'test harness built' with no recorded results.
- Credits: the budget plan assumes about $20; the resources page, as I read it, gives $50.

## 11. Strategy: what to build in the time left

**Decision: keep the architecture, fix the integrity bugs, add a thin Live Observe layer, then deploy.** A rewrite would cost the week.

**Framing:** present it as 'Probation learns from your own footprints, locally and with your consent', not surveillance. Your docs already refuse screen and keystroke capture. That is a strength with judges; do not undersell it with the word 'surveillance'.

### 11.1 Live Observe (your vision)

Add `connectors/` as pack connectors (CONTRACT allows them). Read-only credentials for ingestor and resolver; write credentials only in the Executor. One interface, three implementations, in order of cost:

1. **Calendar and mail without OAuth (about 1 day):** Calendar through the private iCal address (read-only); Gmail through IMAP with an app password (labels, Sent, threads). Both land in the same `raw_items` path (I-17).
2. **Notion (about 1 day):** REST with an internal integration token. Read a Reading or Radar database; the footprint is where the user files items; write only the tracker or collection property.
3. **MCP adapter (1 to 2 days, the differentiator):** an MCP client that implements the same interface over any MCP server's tools, with a **tool allow-list**: read tools for ingestor and resolver, write tools only for the Executor. Confirm which servers and auth flows exist before you commit (section 15).

**Always-on:** a `probation run` supervisor polling every 60 s (ingest, brain, resolver, executor tick; nightly review; web facts). **Shadow week:** after connecting, no execution for 7 days, with a daily 'what I would have done' digest. That is your driving test on live data.

**UI:** a Connections page under More and in first run: connect, choose scope, last sync, pause, disconnect and purge.

**If time runs short:** ship 1 and 2 live on your own accounts for the video and keep MCP as an implemented, tested adapter.

### 11.2 Probation as an MCP server (cheap, on-theme)

Expose `check_permission`, `propose` and `explain` as MCP tools so any agent runtime asks Probation before acting. It turns the project into a permission layer for AI agents and answers the track's 'tools you choose' line. About half a day; verify the runtimes' MCP support first.

## 12. Eight-day roadmap

M1 is the engine lane, M2 the interface lane. Dates assume today is Thu 22 Oct.

| Day | Goal | Work | Done when |
| --- | --- | --- | --- |
| 1 Thu 22 | Stop the bleeding | **M1:** P0-2 (responder, insert order, `:param`, idempotency), P0-7, P0-8, mypy green, `make synth` default, tests stop writing results, `.gitignore`. **M2:** remove fake status text; fix `/licences`; fix `/queue` filters and fields; wire `/items/{id}`; send `edited_body`; action dropdown | `make check` green; a test shows Accept creating an action and a strong outcome, Undo reversing it, and a forced EXECUTE not crashing the replay |
| 2 Fri 23 | Data and reader | **M1:** P0-3 (truth join, render replies and moves), P0-4 (prompt loader, real prompts, fail closed, writer, drafts), model names from the console, first live Nebius call. **M2:** explanation spec, router, accessible modal | Every truth id exists in the DB; one live reader call logged with tokens and cost; drafts appear |
| 3 Sat 24 | Make licences happen | **M1:** calibration out-of-fold, cold start, novelty; exam rewrite (P0-5); full persona with real reader, cached. **M2:** real Permissions page, report card for all families, settings and exposure endpoints | Level 1 and 2 licences appear for high-volume classes; a keyword-dependent policy fails the exam |
| 4 Sun 25 | Tavily and evaluation | Wire Radar out-of-band flow; fix lookalike rules and brands; web-facts page; delete eval literals; real ablation flags; 5 personas; reader accuracy by model tier | `results.json` has no literals; E10 and E11 run on fixtures; Tavily calls are non-zero and logged |
| 5 Mon 26 | Live Observe v1 | iCal, IMAP and Notion connectors; supervisor; Connections page; shadow digest; MCP adapter if ahead | Your own account shows live mail and a Notion board in the dashboard |
| 6 Tue 27 | Deploy | Dockerfiles, compose, Nebius VM, HTTPS, rate limits, budget kill-switch, admin token, CORS; precomputed demo DB; OpenShell policy if the spike worked; phone-viewport smoke test | Demo URL opens on mobile data; kill-switch tested; ledger verifies |
| 7 Wed 28 | Video and README | Record and cut to 2:50; README (diagram, results, Nemotron, Tavily, licence); feedback text; secrets scan; fresh-clone test | Checklist in DEMO\_AND\_SUBMISSION section 4 all ticked |
| 8 Thu 29 | Buffer and submit | Fix only blockers; submit | Submitted before the deadline |

**Cut order if you slip:** MCP adapter, Probation-as-MCP-server, Reading pack, OpenShell, human study, habits and chains polish. **Never cut:** the P0 fixes, honest evaluation, deployment, README and video, the live Radar and Tavily beat.

**Gate on day 3:** if licences do not appear by the end of day 3, demo the replay with the real reader and say plainly that live mode is shadow-only. A smaller honest product beats a larger fake one.

## 13. Upgrades: Nemotron, NVIDIA stack and Tavily

**Make Nemotron vital, and measure it**

1. **Reader accuracy by tier.** The truth file gives labels, so report accuracy, latency and dollars per 1,000 items for Nano, Super and Ultra. That is the 'right model for each job' slide and speaks to the technical-implementation criterion.
2. **Cascade.** Nano first; escalate to Super when reader fields conflict with the header cross-check or look unsure; disagreement becomes ASK. Report the escalation rate and cost.
3. **Ultra as model-aware red team.** Give Ultra the fitted policy's top features and ask for adversarial edits aimed at them; code validates every edit and code gives every verdict. This is a use of a large model that only a safety layer needs.
4. **Voice fidelity metric.** Score the writer by code (greeting, sign-off, length, formality against the user's real replies) so 'in your voice' is measured.
5. **Plain-language permission explanations** (Super) from typed evidence, with the existing number validator.
6. **Safety or jailbreak-guard models**, if Token Factory offers them: a second injection detector that only lowers the cap. Verify availability.

**NVIDIA stack (named in the track brief)**

- **OpenShell:** a real egress policy allowing only Token Factory and Tavily, plus one visibly blocked request in the video. It also demonstrates I-1 and I-2.
- **Nebius Serverless:** run the multi-persona evaluation as parallel jobs.
- **Hermes Agent or NemoClaw:** the always-on agent that calls Probation's MCP gate. Verify before promising it.

**Tavily**

1. Make Radar live: official-page discovery with `include_domains` where the platform is known, `time_range`, Extract with `query` and `chunks_per_source`; show 'mail says 30 Oct, official page says 5 Nov'.
2. **A judge-facing 'Check a sender' box** on the public demo: paste a public domain, get a live vet with sources (rate-limited, behind the query guard). A live Tavily call a judge can trigger.
3. Re-vet on TTL expiry and show change over time ('was confirmed official; now complaints found').
4. An evidence page: exact queries, credits, cache hits, sources.
5. Keep the asymmetry: web facts only restrict or inform.

**Product**

- **Skills page:** each pack as a reusable skill with its six-question manifest (track wording: reusable skills).
- **'What I have learned about you' page:** editable habits (track wording: persistent memory).
- **Portable permission receipt:** signed ledger head plus licence table that an agent runtime can verify.

## 14. Demo and submission checklist (additions to your own)

- Say 'Nebius Token Factory' and 'NVIDIA Nemotron' aloud in the video, and show a real call with its token count.
- Use invented domains for every scam example; do not show real brand names or logos.
- README: architecture diagram, results with seeds and models, a Nemotron section (which tier does which job and why), a Tavily section, licence named in the first lines.
- Public repo with the licence visible in About; keep `build_history/` out of it.
- Record the ledger head hash in the submission only after the head-hash bug is fixed.
- Keep the demo up and free until 15 Dec; precompute answers so it survives a slow endpoint.
- Write the tool feedback while you build: JSON-schema behaviour, reasoning tokens, rate limits, docs gaps.

## 15. What I could not verify

- Live Nebius behaviour: exact model names, JSON-schema support, rate limits, reasoning-token behaviour, retention terms.
- Tavily: auth method, real credit use, retention.
- OpenShell, NemoClaw and Hermes Agent syntax and availability; NVIDIA safety models on Token Factory; which MCP servers exist for Gmail, Calendar and Notion and how they authenticate.
- Why the full persona produced 0 REPLY outcomes.
- The judging panel's exact weighting beyond what is published.
- Browser-level visual quality: I verified code, typecheck and build, not pixels.

## 16. How to reproduce my checks

```
make check                                  # ruff, mypy (4 errors), pytest
probation synth generate --persona-id 0 --seed 7 --size full --out /tmp/f0
probation db init; probation import mail /tmp/f0/mailbox.mbox   # also calendar, files
probation ingest                            # ~280 s for 3,989 situations
# then resolve with as_of=2027-01-01 and call run_replay (script in my notes)
```

Always pass `--out` to `synth generate`; the default writes into the committed fixtures. Run pytest on a copy: it rewrites `docs/results/`.
