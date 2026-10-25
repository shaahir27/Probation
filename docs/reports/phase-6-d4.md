# D4 handoff — local Windows Gmail connector, private runtime, and live-capable acceptance wiring

Branch: `phase-6-d4-gmail`, worktree `data/wp12/worktree`, created from verified main
`347b06e5794085366d190a35985377fdb8b725cc`.
This file was first written as `phase-5-d4.md` because the authorisation text pinned that path
before the branch was renamed; it now follows the branch (`phase-6-d4.md`). No other reference
pointed at the old name.
Scope of this work: **D4 offline implementation + live-capable acceptance wiring.** The concrete
Gmail HTTP client, live token exchange, role credential resolution, and `--live` execution runtime
are fully built and proven offline; live network execution is gated under explicit operator consent
(`PROBATION_GMAIL_LIVE_CONSENT=scoped-authorization-granted`) and `@pytest.mark.live`. No account was
accessed, no OAuth grant exchanged, no live provider spend incurred.

## A. Offline conformance — PASSED

Full isolated gate `C:/Users/shaah/miniconda3/python.exe -B scripts/check.py`, run on the final
integrated source (exit code 0):

- `ruff check backend scripts/check.py` → **all checks passed**.
- `ruff format --check backend scripts/check.py` → **391 files already formatted**.
- `mypy --config-file backend/pyproject.toml backend/src/probation` → **234 source files, no issues**.
- `mypy --strict … core engine` → **49 source files, no issues**.
- `pytest backend/tests -m "not live"` → **1173 passed, 2 deselected** in 09:15.
- Synthetic-fixture and published-result hashes **unchanged** before and after, in both the source
  checkout and the isolated test snapshot.
- The two real-provider tests (`test_gmail_auth.py`, `test_gmail_read.py`) carry `@pytest.mark.live`
  and are the only ones deselected, so `make check` stays offline and secret-free.

## B. Provider capability matrix — supported / unsupported / unverified

Detail and citations: `docs/WP12_D4_GMAIL_CONTRACT.md` §1.

| Capability | Verdict | How it is represented |
| --- | --- | --- |
| Atomic conditional label change (C1) | **UNSUPPORTED** — `users.messages.modify` documents no precondition, no ETag/If-Match | `conditional_write` readiness `unsupported`; the gate refuses dependent effects before dispatch; the execute-time CAS is documented as check-then-act |
| Detection of intervening touched-label changes (C2) | **SUPPORTED, window-bounded** — per-message `historyId` plus `labelAdded`/`labelRemoved` records | `revision` and `label_versions` in `gmail_versions.py`; a real ABA refusal through D3's `prepare_undo` |
| History durability (C3) | **LIMITED — ~7 days**, stale cursor → HTTP 404 | 404 sets `resync_required`; never an empty successful poll |
| Server-side cohort narrowing (C4) | **PARTIAL** — only a singular `labelId` filter, which would hide INBOX/TRASH changes | account-wide history read, discarded locally with zero stored rows for non-cohort entries |
| Reversible archive / trash (C5/C6) | **SUPPORTED** — modify removes INBOX; trash/untrash are distinct; permanent delete never called | adapter + tests |
| Native-threaded send (C7) | **SUPPORTED** — threadId + In-Reply-To/References + matching subject | reply tests |
| Send correlation (C8) | **BOUNDED, NOT EXACT** — no provider idempotency key, no recall | unknown stays `needs-reconciliation`; no automatic resend |
| Attribution of observed changes (C9) | **UNSUPPORTED** — history carries no actor | unmatched events stay unknown; no agreement, correction or strong negative |
| Provider-enforced read/write separation (C10) | **TOKEN-LEVEL ONLY** | documented limitation, not a solved control |
| Whether `gmail.modify` also grants send (C11) | **UNVERIFIED** | recorded rather than assumed; not needed for D4 offline |

## C. Live Gmail acceptance — READY & GATED (NOT RUN)

All concrete transport components, token refresh flows, role credential sourcing, and runtime
provisionings have been built and proven offline. Prepared manifest and Phase 7 operator runbook:
`docs/D4_LIVE_TEST_MANIFEST.md` §9. Live execution is gated under
`PROBATION_GMAIL_LIVE_CONSENT=scoped-authorization-granted` and `@pytest.mark.live`. No account was
accessed, no live grant was exchanged, and no live network calls were executed.

## D. Live scenarios still blocked / decisions applied

1. **Live undo / restoration.** Provider history retention is ~7 days. Owner decision confirmed
   keeping `undo_days = 7` and proving late-undo refusal (`undo_history_unavailable` or safe
   capability refusal) rather than masking provider limitations. The required live gate
   "archive → undo → confirmed restoration" succeeds while the effect anchor is inside the
   retained window and refuses thereafter.
2. **Genuinely earned live autonomy.** No live evidence has accrued. No synthetic licence was
   transferred, no evidence backdated, no promotion forced. A live hold/cancel demonstration
   remains blocked until authority is earned prospectively.
3. **Forward.** Code enforces D3's restricted explicit contract. The live runtime now includes
   an explicit recipient allowlist check (`PROBATION_FORWARD_ALLOWLIST`). An empty allowlist
   refuses sending, and a single operator-allowlisted recipient can be provisioned for live tests.
4. **`messages.untrash` implicit INBOX behaviour** is unverified offline and needs the live gate.
5. **Public OAuth distribution.** `gmail.modify` is a restricted scope and `gmail.send` is
   sensitive; Google verification/assessment and the Testing-mode 7-day refresh-token limit are
   provider-side obligations, not code.

## What was built

**Contracts and storage.** `backend/src/probation/connectors/types.py` (pure records, the single
`HttpTransport` seam). Private store `backend/src/probation/db/gmail.sql` + `gmail_store.py`,
a separate SQLite file under `data/private/connectors/` with a per-authority SQLite authorizer,
so `CONTRACT.md` §3's role table is untouched and the ledger bytes cannot move.

**Read path.** `packs/mail/connectors/gmail_mime.py` (four enforced bounds, header-injection
defence, no attachment/remote-content fetch), `gmail_read.py` (cohort proven before any body
fetch; four Gmail identifiers kept distinct), `gmail_sync.py` (bootstrap anchor → paged commit →
catch-up → watermark; 404 → explicit resync; fenced competing workers),
`gmail_projection.py` (as-of answers from committed rows only; SENT is an observation).

**Write path.** `gmail_write.py` + `gmail_versions.py` implement the unchanged
`MailExecutionIO`. `revision` is a hash including the per-message `historyId`;
`label_versions` come only from provider-observed transitions and fail closed when the window is
incomplete. `capability.py` builds/persists the truthful manifest and gates effects.

**Credential boundary.** `connectors/credentials.py` + `credentials_state.py` (role-bound
providers, `SecretMaterial`, allowlisted child env, generation-guarded refresh),
`connectors/acl.py` (owner-only Windows ACL apply/verify via ctypes; fail closed),
`packs/mail/connectors/gmail_auth.py` (PKCE, bound single-use state, account/scope verification,
refresh serialised per credential reference).

**Runtime and API.** `workers/gmail_observation.py` (fenced lease, bounded retries,
`Retry-After`, interruptible waits, pause/revoke gating), `workers/gmail_commands.py` (idempotent
pause/resume/revoke consumption with an atomic receipt), `packs/mail/connectors/gmail_ingest.py`
(`GmailIngestBridge`: committed observations → engine `sources`/`raw_items`, then the unchanged
`ingest_situations`), `workers/gmail_runtime.py` + `workers/gmail_runtime_provisioning.py`
(one process per role — observation/brain/resolver/examiner/api/executor — with role-bound engine
connections, allowlisted child env, and a coordinator that receives status, never credentials),
`api/routes/gmail_connector.py` + `api/gmail_auth.py` (loopback only, owner credential on
list/detail/status as well as mutations, no client-supplied account identity, leak-free versioned
readiness).

**Live transport, credential sourcing, and runtime wiring (Part 2).**
- `packs/mail/connectors/gmail_transport.py`: Concrete `GmailHttpTransport` (stdlib urllib with
  timeouts, error mapping, and native ID quoting), `GoogleTokenTransport` (POST form exchange and
  refresh decoding), and `GmailProfileGateway` (`users.getProfile` verification).
- `workers/gmail_live.py`: `LiveOAuthClient`, `LiveCredentialSource`, `build_live_provider`, and
  role grant resolution.
- `connectors/grants.py`: `source_grants_for_owner`, `source_grant_for` supporting structured
  runtime grants and role-scoped environment variables.
- `workers/gmail_runtime_provisioning.py`: `LiveExecutorDeps`, `_live_effects`, and
  `EXECUTOR_LIVE_PROVISIONS`.
- `workers/gmail_runtime.py`: `--live` flag, fail-closed consent gate (`PROBATION_GMAIL_LIVE_CONSENT`),
  forward allowlist filtering (`PROBATION_FORWARD_ALLOWLIST`), and child process env forwarding.
- `scripts/gmail_live_env.py`: Operator helper generating runtime environment exports (PowerShell,
  Bash, CMD) from private token files.
- `Makefile` & `make.cmd`: Added `gmail-live` target to execute live tests.
- `docs/D4_LIVE_TEST_MANIFEST.md`: Added §9 Operator runbook for Phase 7 gated acceptance.

## Schema and role ownership

| Object | Writer authority | Key invariant |
| --- | --- | --- |
| `gmail_connections` | administration | identity + credential ref frozen; `selection_revision >= 1` |
| `gmail_history_events` | ingestor | append-only; sole source of `label_versions` |
| `gmail_observations` | ingestor | immutable; PK dedupes overlapping pages; tombstone carries no payload |
| `gmail_sync_cursors` | ingestor / read_worker | watermark and fence monotonic; identity immutable; catch-up flag one-way |
| `gmail_capabilities` | read_worker (read rows), executor (write rows) | CHECK ties `name` to `owner_role`; unsupported requires a reason |
| `gmail_worker_leases` | owning role | fence strictly advances |
| `gmail_effect_receipts` | executor | immutable; hashed native refs; no-effect proof only with `failed` |
| `gmail_command_receipts` | administration | immutable; one receipt per command |
| `gmail_credential_state` | executor | generation never regresses; **no token column exists** |

Engine database: **no schema change**, no migration, no row rewritten. `execution_attempts`,
`actions`, `command_requests` and the ledger are exactly as D3 left them.

## OAuth / injection / runtime instructions (no secrets here)

1. Register an installed-app OAuth client with redirect `http://127.0.0.1:<PORT>/oauth/callback`.
2. Inject per process, by name only: `PROBATION_RUNTIME_GRANT="<connection_id>|<account_id>|<credential_ref>"`,
   `PROBATION_GMAIL_GRANT_<ROLE>_<REF>_<DIGEST>=json(...)`, `PROBATION_GMAIL_LIVE_CONSENT="scoped-authorization-granted"`,
   and `PROBATION_FORWARD_ALLOWLIST="user@example.com"`. Or use legacy per-variable naming
   `PROBATION_GMAIL_READ_{CLIENT_ID,CLIENT_SECRET,REFRESH_TOKEN}`. Never a shared parent environment containing both.
3. Refresh state is written only after `apply_owner_only` + `verify_owner_only` succeed under
   `data/private/`; a failed ACL check denies startup.
4. Call `configure_gmail_api(...)` and `verify_loopback_binding(host)` before serving; the router
   refuses to serve unconfigured and only accepts `127.0.0.1`/`::1`.
5. The observation loop polls at 30 s by default; keep the poll interval comfortably below the
   undo window, because undo provability depends on committed provider history.

## Safe reproduction commands

```bash
cd data/wp12/worktree
C:/Users/shaah/miniconda3/python.exe -B -m pytest -q -c backend/pyproject.toml \
  backend/tests/connectors backend/tests/api -m "not live" --basetemp data/pytest-d4
C:/Users/shaah/miniconda3/python.exe -B scripts/check.py     # full isolated gate, >= 13 min
```

## Deviations and assumptions

- The plan's shorthand path `packs/mail/connectors/` is realised as
  `backend/src/probation/packs/mail/connectors/`; shared records live in
  `backend/src/probation/connectors/`. `backend/tests/connectors/` is collected automatically by
  the existing `testpaths`/`backend/tests` configuration.
- Connector bookkeeping uses a private store rather than engine tables, as §4.3 and the D4 plan
  explicitly permit; this is why no contract amendment was needed for cursor/lease homes.
- Capability row ownership between the read worker and the Executor is enforced by CHECK
  constraints plus the typed API, not by a row-level SQLite authorizer (SQLite cannot express it).
- Effect anchors are in memory by default: after a restart an in-flight undo fails closed
  (`undo_history_unavailable`) rather than being provable. Safe, conservative, recorded as a
  follow-up.
- A reconciled send outcome is returned but cannot be appended because receipts are immutable and
  keyed by `operation_id`.
- `gmail_sync` retains a history-filter helper that duplicates `gmail_read.cohort_transitions`;
  both discard out-of-cohort records. Recorded as maintenance debt.
- Two live tests exist and are deselected; 9 live wiring tests added (`test_gmail_live_wiring.py`).
  No test was skipped, weakened or deleted. The full non-live suite is **1173 passed**, the D3 baseline
  plus this package's additions.

## Open interface requests (recorded, not silently closed)

Each is kept visible by a test or by the checklist rather than papered over; full text in
`docs/WP12_D4_GMAIL_CONTRACT.md` §10.

- **IR-D4-1 — backfill cohort not yet stamped on a commitment.** `gmail_projection.py` emits
  `retrospective`/`evidence_context` and `core/permission_history.py` honours them (proven by
  `test_backfill_cannot_grant_live_authority`), but the shared commitment writer
  `db/proposals.persist_proposal` uses a fixed field list without either key, so a Gmail backfill
  routed through the ordinary path would commit as prospective evidence. D4 will not edit a
  D3-owned shared file to close this; `test_backfill_label_is_not_yet_carried_by_the_writer`
  documents it.
  Regarding the ~7-day retention limitation vs `undo_days = 7`: owner decision confirmed retaining
  `undo_days = 7` and proving late-undo refusal rather than masking provider limits.
- **IR-D4-2 — CLOSED (in D4 Part 2).** Concrete HTTP transport `GmailHttpTransport` and
  `GoogleTokenTransport` implemented in `backend/src/probation/packs/mail/connectors/gmail_transport.py`.
  Live credential resolution and role provider wiring implemented in `backend/src/probation/workers/gmail_live.py`.
  Live runtime execution wired with `--live` flag and forward allowlist in
  `backend/src/probation/workers/gmail_runtime.py`. Offline tests cover all components, and real
  network calls carry `@pytest.mark.live` and remain gated under `PROBATION_GMAIL_LIVE_CONSENT=scoped-authorization-granted`.
- **IR-D4-3 — forward is deliberately unthreaded; its allowlist lives in D3.** A forward is a new
  message (no `threadId`/`In-Reply-To`/`References`) and the empty allowlist is enforced at the D3
  contract layer, not inside the connector, so checklist row 25 stays PARTIAL.

## Contract change requests (still open; nothing was edited)

1. **Named provider destinations.** `CONTRACT.md:84-90` names only `api.tavily.com` and says the
   ingestor may reach "Only the source" and the Executor "Only approved target apps/auth
   endpoints". Neither enumerates `gmail.googleapis.com` or `oauth2.googleapis.com`. Request:
   enumerate both, bound to their roles, before any live call. Offline work needs no answer.
2. **Connector cursor/lease home.** `CONTRACT.md` §5 assigns the ingestor "cursor durability" but
   §3's role table gives it only `sources`, `raw_items`, `situations`, and §3 forbids implicit
   allowlist extension. D4 avoided the conflict by using the private store. Request: either
   bless that arrangement explicitly or approve per-table rows per FP-D3.
3. **Forward semantics disagreement.** `CONTRACT.md` §9 with FP-D8/FP-D13 permit an explicitly
   owner-approved forward; `FULL_PRODUCT_SPEC` §7.2 step 7 says forward remains suggestion-only.
   D4 applied CONTRACT (restricted explicit forward, empty allowlist) and flags the conflict.

## New dependencies, spend, secrets

None. No install. No LLM or provider call. USD 0. No `.env`, account or personal record read;
all fixtures are synthetic (`acct@test.invalid`, `msg-1`, canary values).

## Credential-vault migration follow-up (separate package)

Move from per-process environment injection to genuine OS-identity isolation and a protected
vault: separate OS identities per role, vault-backed refresh storage with rotation/revocation,
migration rollback, ACL tests per deployment, and provider-side re-consent handling for the
Testing-mode seven-day expiry. Same-user process isolation today proves only that this
application did not hand the write grant to the reader; it does not isolate against other
same-user software.

## Remaining whole-WP12 obligations (not claimed here)

Calendar (12.3), files (12.4), Notion (12.5), IMAP/iCal (12.6), MCP (12.7) remain unbuilt.
Gmail live acceptance (12.2), durable anchors, an append-only reconciliation chain, the three
interface requests IR-D4-1/2/3 in `docs/WP12_D4_GMAIL_CONTRACT.md` §10, and D6 frontend
integration are open. D5/Tavily, other connectors and public OAuth hosting were not started.

## Suggested next step

Owner decision on the undo-window question in §D, then authorise the concrete live manifest.
