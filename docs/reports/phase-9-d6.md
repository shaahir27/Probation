# Phase 9 handoff — D6: API and complete frontend surface

**Earlier D6 branch:** `phase-9-d6-api-frontend` / `data/d6/worktree`
**Final completion tree:** `main` at the repository root, based on `00a1570`; the Connect apps, live read-only Gmail and More/Performance completion is the final work recorded in this report.
**Base commit:** `29f1f6616cdb08ee769a4f2bbad95b35e50f902d` (`phase-6c: fix Gmail cohort filtering`, verified equal to accepted `main`)
**D6 commits:** `6a3eb99` (backend, contracts, readiness), `ec0a30b` + `a574c99` (acceptance matrix, handoff, budget reconciliation), `4884e7b` (dashboard, harness, browser evidence), `00a1570` (final D6 identities and second gate). Nothing pushed.
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

- `python scripts/check.py` (isolated snapshot gate, the `make check` equivalent on this host — GNU make is absent) on `29f1f66` first: **10 failed, 1329 passed** → after this work: **1403 passed, 2 deselected, 0 failed**, `ruff check`, `ruff format --check` (430 files), project mypy and `mypy --strict` on `core/`+`engine/` all clean, **protected fixture and published-result hashes unchanged in source and snapshot** (`+74` tests, none weakened). The gate was run a second time at the final tree (`4884e7b`) after the readiness and dashboard work: **1403 passed, 2 deselected, 0 failed**, hashes unchanged again.
- Focused suites used during development: `backend/tests/connectors/test_d6_worker_runtime.py`, `test_d6_worker_isolation.py`, `test_gmail_runtime.py`, `test_gmail_ingest.py`, `test_gmail_evidence_provenance.py`, `test_gmail_live_wiring.py`, `backend/tests/integration/test_d5_pipeline.py`, `test_wp6_response_api.py`, `backend/tests/unit/test_d6_replay_controls.py`, `test_d6_replay_recovery.py`, `test_wp6_api_readiness.py`, `test_wp1_context.py`, `test_wp1_ledger_views.py`, `test_wp6_followup_evidence.py`, `backend/tests/api/test_api_endpoints.py`.
- Frontend at `4884e7b`: `tsc --noEmit` clean; `node --test tests/*.test.mjs` **10 passed / 0 failed**, including a new assertion that no production source imports or embeds fixture data.
- Browser harness at `4884e7b`: **37 passed, 0 failed** (`node node_modules/@playwright/test/cli.js test --reporter=list`, exit 0, 1.3m). Run against the built bundle on loopback with the system Chrome (`channel: "chrome"` — no browser download was needed), one isolated port pair and throwaway synthetic workspace per journey, `workers: 1`, traces and video off. Coverage: plain-language copy and no gate tokens on screen; technical detail hidden inside a collapsed `<details>`; four-way verification availability with citations and an unknown fee never reading as free; unavailable destinations stating a reason with no invented rows; all 14 `#/more/*` destinations marked current; deep link surviving refresh plus re-auth; Back/forward and filters; 360/390/768/1440 with no horizontal overflow and *measured* reachable >=44px actions; 200% zoom; keyboard-only review with visible focus; accessible names and announced errors; reduced motion; zero console errors; no off-origin request; production bundle verified rather than the dev server; memory-only key; sign-out DOM clearing; an in-flight response unable to repopulate a closed session; second identity seeing nothing; durable request never claiming completion; conflict demanding fresh review; undo only where the server offers it.
- Frontend at the final completion tree: `tsc --noEmit` clean; `npm run build` passed; `node --test tests/*.test.mjs` **11/11**; `npx playwright test --reporter=list` **40/40 passed** (including the Connect apps chooser and the server-selected synthetic workspace). The final More navigation has nine visible destinations plus the honest legacy deep-link fallbacks.

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
7. **Resolved in the final completion.** The historical note about live credential env names and the label display name is superseded by the Connect apps read-only flow: the safe preflight now reports the OAuth client, test account, owner and native `Label_1` configured; the fixed Web redirect `http://127.0.0.1:8765/` completed consent; the private store contains a verified read-only refresh token. The opt-in D4 live tests still read exported environment variables directly; that separate test path is unchanged.
8. The forward and deny admin commands accept an ignored `request_id` in the UI body; server-side determinism (`det_id` over the canonical payload) is what actually makes them idempotent. Undo does use the client request id via `UndoBody`.

## Contract change requests

**None.** No contract rule needed changing and no new ledger kind or unapproved table writer was created. The approved Connect apps extension creates one **read-only observation grant** (SHADOW, exact `gmail.readonly`, private token ACL); it creates no write credential or new authority. Two items would require a change request if pursued: persisting supervision state in the ledger (today it is a document beside the database, deliberately not durable history), and giving the API role an Examiner-authorized advance path for replay (today advancing stays Examiner-owned and the API only submits intents).

## New dependencies

`@playwright/test@1.64.1` (devDependency only, MIT) for the browser harness, with its lockfile change committed. Its **browser binaries are not installed** and were not downloaded. No other dependency was added, no unrelated package was upgraded, and the approved model mapping is unchanged — no automatic model fallback was introduced and no prompt was altered for UI convenience.

## LLM cost incurred

**Budget authority read from `data/d5/live/accounting.db` (read-only, 2026-10-26), scope `d5-nemotron-tavily`:**

| Provider | Ceiling | Confirmed charged | Estimates | Unresolved holds | Remaining |
|---|---|---|---|---|---|
| Nebius (Nano `NVIDIA-Nemotron-3-Nano-30B-A3B`) | $1.00 total | $0.001109 (22 reconciled attempts) | $0.004875 | 0 | ~$0.9989 |
| Nebius (Super `nemotron-3-super-120b-a12b`) | $1.00 total | $0.003896 (15 reconciled attempts) | $0.019298 | 0 | ~$0.9961 |
| Tavily | 20 credits | 8.0 credits (9 recorded calls, 8 reconciled) | $0.00009 reserved | **1 call `ambiguous`** | **11 usable** (12 gross − 1 hold) |

Nebius total confirmed across both scopes: **$0.005005**. 29 requests succeeded, 8 `failed_closed` — those failures consumed budget and produced no effect, which is the correct fail-closed outcome and is counted, not hidden.

**The one Tavily `ambiguous` row is an unresolved hold: it stays counted against the ceiling and must never be re-sent automatically.** Reconciling it is a read-only follow-up against the provider record, not a new paid request.

**$0.00 Nebius, 0 Tavily credits, 0 paid calls in this D6 work.** Everything above was verified offline against synthetic data and fake transports. The cumulative ceiling ($1 Nebius / 20 Tavily credits) is untouched by this session; prior charges and unresolved holds recorded against `data/d5/live/accounting.db` under scope `d5-nemotron-tavily` still count against it and remain to be reconciled before any paid test.

## Open questions

1. ~~Playwright browser download~~ not needed: the harness drives the installed Chrome through `channel: "chrome"` and the suite passes. Nothing outstanding here.
2. Approve the paid-test window, if any: I will re-read the accounting authority and run sequential paid checks only inside the remaining allowance.
3. ~~Set the native label and export the live credential bundle~~ **Resolved for read-only:** the fixed Web redirect completed consent; the SHADOW grant uses exact `gmail.readonly`; the token is ACL-protected. No write bundle was created.
4. The approved cohort contains one incoming synthetic workshop message. The live observation produced **one ASK review request** and the recorded history contributes 167 watching observations. No genuine send/archive/reply was performed; the write proof still requires the exact operation manifest.
5. No live effect (send, forward, trash, archive) has an approval yet; the Executor is deliberately unprovisioned. The operation manifest remains a separate approval.

## Suggested next step

The D6 read-only demo is now complete at the code and local-acceptance level: the frontend, runtime grant, live observation, More/Performance UI, budget hold display and browser suite are verified. Finish the final report/README and local commit, then stop. D7 (focused model-quality evaluation), D8 (deployment and visitor isolation), Gmail writes and Calendar/Drive remain untouched — **do not start them under this phase**, and do not push, merge or deploy as part of D6.

## Local main database repair — 26 October 2026

The running main checkout returned `503 Database upgrade required: probation db migrate`
from both queue and replay state. Its existing database predated the lifecycle schema.
The advertised CLI repair only called `migrate_wp1`, so it reported success without
installing the later lifecycle, replay, feature-provenance and accounting migrations.
`cli.db_migrate()` now delegates to the existing full `ensure_schema()` path and still
refuses a missing database. API reads continue to refuse old schemas without migrating them.

Before modifying the application database, a SQLite backup and successful rehearsal were
created under `data/backups/main-schema-97373fd9bf264c24ba16ad5854e74fca/`.
The corrected `python -m probation.cli db migrate` then completed on main. All 723 ledger
rows were byte-for-byte equal as serialized records, the hash chain verified, and every
pre-existing table retained its row count. Authenticated GETs to the running backend's
queue, replay state, Watching, actions and readiness all returned HTTP 200 afterwards.
The earlier screenshot's 500 was not reproduced: current requests reproduced the
database-upgrade 503 before repair and 200 afterwards.

Verification: 10 focused CLI/ledger/API-readiness tests passed; Ruff lint and formatting
checks passed for both changed Python files. The new regression first failed on the old
CLI implementation, then passed after the repair, including a repeated migration.
The root dotenv was loaded through application settings, never displayed or edited.
No Gmail effects, model calls or Tavily calls were performed. These results concern local
startup and do not complete the outstanding live Gmail acceptance.

## D6 final completion — Connect apps and live read-only Gmail — 26 October 2026

**Final tree:** `main` at the repository root, based on `00a1570`. The final local commit
is `FINAL_COMMIT` (nothing pushed, merged or deployed). The earlier
`phase-9-d6-api-frontend` worktree remains the historical milestone.

### Delivered after `00a1570`

- **Connect apps** is a visible destination in **More** with official local Gmail,
  Google Calendar and Google Drive icons and source attribution. Gmail is connectable;
  Calendar and Drive are explicitly **Planned**. The API receives only connection status,
  never a Google token, callback or authorization URL.
- **Read-only Gmail setup** runs in an isolated local child. It verifies the OAuth client,
  the configured test account, the fixed loopback redirect `http://127.0.0.1:8765/`, the
  exact `gmail.readonly` scope and the approved native `Label_1` before persisting a
  SHADOW registration and an owner-only refresh token under `data/private/connectors/`.
- **The supervisor now consumes that setup grant.** The `serve --gmail-runtime` path loads
  the registered grant and token store, injects exactly one read-only grant and OAuth
  bundle into the observation child, and leaves the API without Google credentials. The
  live flag is added only to the live-capable roles, not to the API or Resolver.
- **The observation start is fixed for the real provider.** Gmail returns its 64-bit
  `historyId` as a decimal string; the MIME parser now accepts that representation while
  still rejecting missing, negative or oversized values. The live observation role
  stays running instead of exiting at startup.
- **The ACL setup is portable to an already-owned directory.** `apply_owner_only` replaces
  only the protected DACL when the current user already owns the path; it no longer
  demands an unnecessary `WRITE_OWNER` handle. The final owner-only verification is
  unchanged, and the OAuth callback parser accepts a real Google authorization code while
  retaining the state/PKCE checks.
- **Frontend:** More now exposes nine working destinations — Connect apps, Performance,
  Counts & trends, Trick tests, Privacy & web, Cost & usage, Integrity record, Settings
  in use and Help & limits. Cost & usage shows confirmed, estimated, unresolved-hold and
  never-dispatched spend. Help explains the owner key versus Google consent and the exact
  local preflight. Connect apps maps safe setup failures to actionable copy. Legacy pack
  deep links remain honest unavailable pages.
- **Harness:** the synthetic-connections journey no longer attempts owner-key sign-in in a
  profile that correctly auto-signs-in; the final suite is unfiltered and green.

### Live evidence

| Item | Evidence |
|---|---|
| Read-only preflight | OAuth client, test account, owner and native `Label_1` configured; fixed redirect printed; no secret printed |
| Consent | Completed with the configured test account; exact `gmail.readonly`; SHADOW registration; owner-only token ACL verified |
| Live observation | One incoming synthetic workshop email observed; **1 ASK**, **167 watching** proposals from recorded history |
| Writes | **None.** The Executor is not provisioned; no write manifest was requested or used |
| Paid calls | `llm_attempts` 0 and `tavily_calls` 0 in this D6 live session; the cold-start item is a request for approval, not a claimed model draft |
| Runtime readiness | API, observation, Brain, Examiner and Resolver running; Executor intentionally exited without a write grant; Webfacts idle (`work_status_absent`) until a relevant request |
| Budget | D5 cumulative `$0.005005` confirmed across per-model Nebius scopes; Tavily **11 usable** (8 confirmed + 1 ambiguous hold); no fresh allowance |

The D5 six-case Super intent smoke (6/6; Nano 2/6) is separate evidence and remains a
six-case smoke only — not general accuracy, a Gmail flow score or an autonomous permission
result.

### Final tests

- **Backend full gate:** `python scripts/check.py` on the final read-only tree —
  **1462 passed, 2 deselected, 0 failed** (427.66s). `ruff check`, `ruff format --check`,
  project mypy and `mypy --strict` on `core/` + `engine/` pass; protected fixture and
  published-result hashes are unchanged.
- **Frontend:** `tsc --noEmit` clean; `npm run build` passed; `node --test tests/*.test.mjs`
  **11/11**; `npx playwright test --reporter=list` **40/40**.
- **Focused Gmail setup/ACL/runtime tests:** **67 passed**, including the new grant identity,
  token ACL, supervisor loader, callback parser and live-role tests.
- **Live Gmail:** read-only consent and observation pass; no write path was exercised.

### Final limitations

- No Gmail send, archive, trash, forward, reply or undo is enabled in this demo. Those require
  the exact operation manifest and an Executor write grant.
- Google Calendar, Google Drive, files, chains, habits, Radar and Reading are not part of this
  focused email release.
- No paid model/Tavily call is claimed for the cold-start live item; the D5 provider evidence is
  separate. The six-case Super smoke is not general accuracy.
- No deployment, public URL, multi-user account or real personal data is claimed. D7 and D8
  remain untouched.

### Final commit and preservation

The final local commit is `FINAL_COMMIT`. It includes the D6 code, tests, docs and root README.
The pre-existing staged `build_history` WP4 files and the local build-history D6 DB-repair notes
are intentionally **not** part of it, per the D6 scope. No push, merge or deployment was performed.
