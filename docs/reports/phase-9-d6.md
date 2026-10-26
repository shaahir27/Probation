# Phase 9 handoff — D6: API and complete frontend surface

**Branch:** `phase-9-d6-api-frontend`
**Worktree:** `data/d6/worktree`
**Base commit:** `29f1f6616cdb08ee769a4f2bbad95b35e50f902d` (`phase-6c: fix Gmail cohort filtering`, verified equal to accepted `main`)
**D6 commits:** `6a3eb99` (backend, contracts, readiness) and the frontend/e2e commit that follows it in this branch
**Milestone name:** D6 (the `phase-9` prefix is the API/dashboard implementation phase)

## Done

D6 now connects the accepted D4 Gmail connector and the D5 Nemotron/Tavily work to an application that tells the truth.

- **Private API access is authenticated.** `optional_owner` and `require_owner` resolve a real loopback bearer credential through the existing constant-time Gmail owner boundary, and grants come only from committed connector rows. Every private read (queue, watching, items, actions, licences/permissions, reports, insights, boards, web-facts, ledger verify, settings, exposure, readiness) and every private mutation is protected. An unconfigured private API is unavailable rather than open; an invalid non-loopback bind host is refused instead of substituted; validation errors echo no request body.
- **The real Gmail pipeline runs.** Incoming situations reach a bounded history snapshot, the configured Nemotron reader, webfacts verification where applicable, fresh cutoff and restriction checks, the existing gate and derived licence, and atomic proposal/draft persistence — in one process per role with exact per-role environment allowlists. A scrubbed child cannot reload the repository dotenv (proved with a synthetic canary file and real Windows child processes).
- **Tavily stays outside the Brain.** Verification crosses a supervisor-brokered byte-framed JSON pipe with strict schemas, one outstanding request per Brain, a 180-second timeout on an injected clock, and typed unavailable replies for malformed, oversized, unknown-field, mismatched-identity and timeout cases. Nothing is re-sent, so an uncertain paid request is never repeated.
- **Web facts fail closed.** An unavailable verification now restricts (`cap 0`) rather than reporting the message unrestricted (`cap 3`). The same tightening that D5 already applied to its own failure paths had not been applied in the new Brain path.
- **Source identity and evidence provenance are consistent.** One canonical `gmail-source:<connection>` id is shared by ingestion, owner scope, grants and execution; the historic persisted id was preserved, not rewritten. Gmail cohort flags are carried into the appended proposal commitment, and only explicit matching prospective provenance can qualify autonomy — legacy, backfill and malformed provenance are excluded.
- **Replay survives restart.** Controls are durable Examiner-owned intents with receipts, lease fencing, a controller epoch and an OS lock; simulated and operational time are separated; a resumed run continues from its checkpoint rather than restarting the scenario, and the API never advances replay.
- **Read models are honest.** Intended decisions are separated from confirmed effects and from unresolved results; report filters and cutoff reach the engine; spend separates confirmed charges, estimates and unresolved holds; empty evidence stays empty; role readiness requires a reported successful tick and a missing or stale supervisor document means unavailable.
- **Frontend.** Rebuilt against the frozen contracts: memory-only owner session with a session-generation guard, runtime-validated responses, hash navigation with real links, review-then-bind-then-submit with a stable request id, conflict requiring fresh review, typed citations and fee status, and honest loading/empty/error/stale/locked/unsupported states. Production mock data was removed from `src` entirely and is now enforced by a test.

## Files changed

Backend (commit `6a3eb99`, 71 paths): `api/authority.py`, new `api/owner_auth.py`, `api/app.py`, `api/gmail_auth.py`, `api/routes/gmail_connector.py`, new `api/readiness_models.py`, new `api/routes/readiness.py`, `api/routes/{queue,items,actions,licences,report,insights,boards,webfacts,controls,responses,replay}.py`, `api/review_models.py`, `db/{proposals,migrations,lifecycle_commands,lifecycle_receipts,lifecycle.sql,replay_commands,replay_migration}.py`, new `core/{replay_controls,runtime_status}.py`, `core/{clock,lifecycle,history,permission_history}.py`, new `engine/{replay_kernel,runtime_snapshot}.py`, `engine/{evidence,licence,exam_context,replay}.py`, new `workers/{bootstrap,d5_ipc,gmail_brain,gmail_role_loops,replay_controller,replay_lock}.py`, `workers/{gmail_runtime,gmail_runtime_provisioning,admin,d5_verification}.py`, `config.py`, `cli.py`, `connectors/grants.py`, `packs/mail/connectors/gmail_ingest.py`, `core/clock.py` (`operational_clock`), `.env.example`, `make.cmd`, `docs/WP9_D6_IMPLEMENTATION_PLAN.md`, `docs/wp9/*`, and the test files named below.

Frontend and harness (second commit): `frontend/src/{App.tsx,index.css,api/{client,types,validation,queries,mutations,action_status}.ts,auth/OwnerSession.tsx,navigation.ts,lib/links.ts,components/{layout,common,queue}/*,views/*}`, removal of `frontend/src/api/fixtures.ts` and `frontend/src/views/InsightsView.tsx` into `frontend/tests/fixtures/`, `frontend/{index.html,vite.config.ts,tailwind.config.ts,package.json,package-lock.json,playwright.config.ts}`, `frontend/tests/*`, `scripts/d6_e2e_{server,seed}.py`, `.taste-skill/d6/direction.json`.

## Tests

- `python scripts/check.py` (isolated snapshot gate, the `make check` equivalent on this host — GNU make is absent) on `29f1f66` first: **10 failed, 1329 passed** → after this work: **1403 passed, 2 deselected, 0 failed**, `ruff check`, `ruff format --check` (430 files), project mypy and `mypy --strict` on `core/`+`engine/` all clean, **protected fixture and published-result hashes unchanged in source and snapshot** (`+74` tests, none weakened).
- Focused suites used during development: `backend/tests/connectors/test_d6_worker_runtime.py`, `test_d6_worker_isolation.py`, `test_gmail_runtime.py`, `test_gmail_ingest.py`, `test_gmail_evidence_provenance.py`, `test_gmail_live_wiring.py`, `backend/tests/integration/test_d5_pipeline.py`, `test_wp6_response_api.py`, `backend/tests/unit/test_d6_replay_controls.py`, `test_d6_replay_recovery.py`, `test_wp6_api_readiness.py`, `test_wp1_context.py`, `test_wp1_ledger_views.py`, `test_wp6_followup_evidence.py`, `backend/tests/api/test_api_endpoints.py`.
- Frontend: `tsc --noEmit` clean; `node --test tests/*.test.mjs` **9 passed / 0 failed**, including a new assertion that no production source imports or embeds fixture data.
- Browser harness: **37 Playwright specs across 8 files load cleanly** (`playwright test --list`) and cover widths 360/390/768/1440 with no overflow, mobile bar not obscuring the action, 200% zoom, keyboard-only review with visible focus, accessible names and announced errors, reduced motion, zero console errors, no off-origin request, production bundle served (not the dev server), memory-only key, sign-out DOM clearing, in-flight response cannot repopulate a closed session, second identity sees nothing, durable request that never claims completion, conflict → fresh review, undo only where the server offers it.
- **Execution of the browser suite is blocked**, not skipped: no Playwright browser binaries exist on this host (`~/.cache/ms-playwright` and `%LOCALAPPDATA%\ms-playwright` are both absent) and installing them is a new network destination, which requires the owner's approval. A22/A23/A24 are therefore **authored, unexecuted**.
- Test-plan ids satisfied offline: T-LEDGER (append-only chain asserted around provenance refusal), T-ID and T-CANONICAL (`test_canonical_source_identity_links_ingestion_grants_and_execution`), no-peeking (cutoff and future-cutoff refusal in the new provenance and Brain tests), T-AUTH (`test_configured_owner_auth_rejects_outside_and_ungranted_clients`), T-RACE (conflict/duplicate command tests), T-IPC (malformed/oversized/mismatch/timeout), T-RESTART (replay recovery suite).

## Invariants touched

- **I-1 / I-2 (LLM output is data; only Executor has side effects):** unchanged and reinforced — the new Brain path only reads and proposes; the webfacts role holds the Tavily client and performs no write; the API holds no provider credential.
- **I-3 fail closed:** restored in three places where D6 work had drifted open — webfacts unavailable `cap 3 → 0`, malformed stored provenance now excludes the record instead of raising or trusting it, and an unreadable supervisor status document reports unavailable rather than online.
- **I-4 no peeking:** the Brain and the readiness/replay projections read only `HistoryView(as_of=t)` bounded cohorts; a `CUTOFF_EXPOSED_ALL_KEYS`-style future cutoff is refused and no control path injects a later timestamp.
- **I-5 / I-7 ledger append-only, proposal precedes outcome:** no new ledger kind, no new writer, no UPDATE/DELETE; replay checkpoints use existing receipts; `clock_state` is not written anywhere in `backend/src/probation`.
- **I-8 licences derived, not stored:** `permission_history` is stricter about which Gmail evidence may qualify; caps and hands-off lists remain hard-coded.
- **I-9 examiner is code:** unchanged; the Examiner loop computes verdicts and owns replay consumption.
- **I-10 redaction and budget guard:** status lines, logs and metrics carry identifiers, counts and exception type names only — never a message body; the fitted snapshot is cached per process instead of re-fit every tick, which removes an unbounded repeated embedding cost.
- **I-12 synthetic data, no secrets:** no `.env` was read, printed, copied or committed by this work; the dotenv-isolation test uses a synthetic canary file in a temp directory.
- **I-13 web facts may only restrict, never raise autonomy:** policy, evidence and licence code import nothing from `web/`; raw web text remains inside the quarantined extractor and never reaches the writer.

## Deviations and assumptions

1. **Two committed tests were corrected, not relaxed**, and both changes are visible in the diff. `test_owner_required_and_legacy_mutation_rejected` asserted `403` from a stub that always refused; with real authentication an unconfigured private API answers `503`, and the rejection case was extended into a new test asserting `401` off-loopback, `401` wrong token and `403` for an authenticated owner with no source grant. `test_api_replay_state_uses_the_application_clock` and the follow-up evidence fixture needed a faithful schema (an engine database; a `sources` row and `raw_items.source_id`), because those claims are now durable/derived rather than a module dictionary. In each case the assertion about behaviour was preserved and strengthened.
2. **Role readiness covers only the four engine loops** (brain, resolver, examiner, webfacts). Observation and executor export their ticks for reporting but are not gated on them, because coupling those roles' readiness to subprocess scheduling makes the suite non-deterministic. Their liveness plus provisioning is what is asserted.
3. **A `PROBATION_ENV_FILE` indirection exists** so a worktree without its own dotenv can run against the repository's. It is popped before any child imports the application, and the canary test proves the child cannot see it. If the owner prefers, the indirection can be removed entirely; it is a local convenience, not a contract requirement.
4. **`gmail_runtime.py` is ~880 lines**, over the ~400-line guidance. It already exceeded the limit before D6 and was not restructured inside a safety commit.
5. **Strict Pydantic response models cover `readiness` and `review` only.** `queue`, `items`, `actions` and `boards` still hand-build dictionaries; §7 asked for a broader `api/read_models.py`. Splitting them changes every response surface at once and was deliberately deferred to its own change so it cannot hide the safety content of this commit.
6. **`api/routes/gmail_connector.py` still holds configuration in a module global.** The plan called this out; making it application-scoped touches every test that constructs an app.
7. **Live credential env names are not what `.env` contains.** `PROBATION_GMAIL_CLIENT_ID`/`_SECRET`/`_REFRESH_TOKEN`/`_ACCOUNT` are read by the opt-in live tests directly from `os.environ`, which nothing populates from `.env`, and `PROBATION_GMAIL_LABEL` currently holds the label *name* while `gmail_sync.py:363` compares against the native `labelId`. Until the owner sets the ID and exports the credential bundle, live read tests skip and the live cohort would be empty. This is reported, not worked around.
8. The forward and deny admin commands accept an ignored `request_id` in the UI body; server-side determinism (`det_id` over the canonical payload) is what actually makes them idempotent. Undo does use the client request id via `UndoBody`.

## Contract change requests

**None.** No contract rule needed changing, no new authority or credential was introduced, and no new ledger kind or unapproved table writer was created. Two items would require one if pursued: persisting supervision state in the ledger (today it is a document beside the database, deliberately not durable history), and giving the API role an Examiner-authorized advance path for replay (today advancing stays Examiner-owned and the API only submits intents).

## New dependencies

`@playwright/test@1.64.1` (devDependency only, MIT) for the browser harness, with its lockfile change committed. Its **browser binaries are not installed** and were not downloaded. No other dependency was added, no unrelated package was upgraded, and the approved model mapping is unchanged — no automatic model fallback was introduced and no prompt was altered for UI convenience.

## LLM cost incurred

**$0.00 Nebius, 0 Tavily credits, 0 paid calls in this work.** Everything above was verified offline against synthetic data and fake transports. The cumulative ceiling ($1 Nebius / 20 Tavily credits) is untouched by this session; prior charges and unresolved holds recorded against `data/d5/live/accounting.db` under scope `d5-nemotron-tavily` still count against it and remain to be reconciled before any paid test.

## Open questions

1. Approve the Playwright browser download (~one Chromium) so the 37 authored specs can actually run and A22/A23/A24 can be evidenced rather than claimed.
2. Approve the paid-test window, if any: I will re-read the accounting authority and run sequential paid checks only inside the remaining allowance.
3. Set `PROBATION_GMAIL_LABEL` to the native label ID and export the live credential bundle (see the D6 build-history note), then approve the read-only cohort enumeration.
4. A separately authorized synthetic **sender** is still required: the six existing test emails are self-sent, so no genuine incoming message has ever been processed.
5. No live effect (send, forward, trash, archive) has an approval yet; I will present the operation manifest and stop before any write.

## Suggested next step

Finish D6 offline: install the browser binary on approval, run `npm run test:e2e` against the built bundle in a fresh synthetic workspace, resolve the material usability failures the Taste critique loop finds, and record before/after evidence in `docs/wp9/D6_ACCEPTANCE_MATRIX.md`. Implementation readiness and live acceptance must stay reported separately. Then D7 (focused model-quality evaluation) and D8 (deployment and visitor isolation) remain untouched — **do not start them under this phase**, and do not push, merge or deploy as part of D6.
