# WP12 D4 — Gmail connector contract, capability gate and interface decision record

Branch `phase-5-demo-gmail-connector`, created from verified main `347b06e5794085366d190a35985377fdb8b725cc`
in isolated worktree `data/wp12/worktree`. Status authority: CONTRACT > specs > plans.
This file is the released interface record. Parallel agents code against it; only the
integration owner edits it.

## 0. Baseline evidence

| Item | Verified value |
| --- | --- |
| main / origin/main | both `347b06e` (no divergence) |
| Accepted D3 tests | 833 passed, 0 failed, 778.15s — `docs/reports/phase-5-d3.md:51` |
| Worktree tips `fd45942` `200ab93` `347b06e` `a5610a0` | all ancestors of main (nothing unmerged) |
| Root dirty files | `build_history/index.md`, `build_history/phase_04_engine_core_backtest/feature_policy_novelty_lb.md` (tracked, pre-existing, preserved untouched) |
| Interpreter | `C:/Users/shaah/miniconda3/python.exe` carries all deps; no install performed |

Baseline SHA-256 (first 16) of files this package is not allowed to change silently:
`lifecycle_io.py 13c469aa5bdb12bd`, `lifecycle_operations.py 4909239ead0be4b2`,
`packs/mail/executor.py d19261606b300b08`, `workers/mail_execution.py b14af9385d934caa`,
`synth/mail_operations.py 354899e8662cd674`, `core/lifecycle.py ce6dfb543ad7f72a`,
`db/lifecycle.sql b2bcc06e1dd95ffe`, `db/migrations.py ce616674f4a7a3ca`,
`db/access.py 269e6b9d0882fae4`, `db/connection.py c8e667d607884f36`,
`db/guards.py 35505de2d088fc30`, `scripts/check.py ecd4f7a78c1726dd`.

## 1. Provider capability matrix (offline evidence)

Sources: Gmail REST reference for `users.messages` / `users.messages.modify` /
`users.history.list`, the Gmail sync guide, and the Gmail auth scopes page.

| # | Capability | Verdict | Evidence and consequence |
| --- | --- | --- | --- |
| C1 | Atomic conditional label change (compare-and-set on modify) | **UNSUPPORTED** | `users.messages.modify` documents body fields `addLabelIds`, `removeLabelIds`, `addClassificationLabels`, `removeClassificationLabelIds` and **no** precondition parameter; the Message resource documents no ETag, version or If-Match. The execute-time `expected_revision` check in `mail_execution.py:228-233` degrades from atomic to check-then-act against Gmail. Never report local locking as provider atomicity. |
| C2 | Detection of intervening touched-label changes | **SUPPORTED, window-bounded** | `Message.historyId` is "the ID of the last history record that modified this message" — per-message, advances on modification. `users.history.list` returns `labelAdded`/`labelRemoved`/`messageAdded`/`messageDeleted` records in increasing `historyId` order. Enables honest `label_versions` (§2) and real ABA detection. |
| C3 | History durability | **LIMITED — ~1 week** | The sync guide states history records last about one week; `history.list` returns **HTTP 404** for an invalid/out-of-range `startHistoryId`, requiring full re-sync. See the window collision in §3. |
| C4 | Server-side cohort narrowing of history | **PARTIAL** | `history.list` accepts a singular `labelId` filter, not `labelIds`. Filtering by the cohort label would hide adds/removes of `INBOX`/`TRASH`, which is exactly what C2 must detect. Decision: read **account-wide** history and discard out-of-cohort records locally (§4). |
| C5 | Reversible archive | SUPPORTED | `modify` removing `INBOX`; restoration re-adds it. |
| C6 | Reversible trash / untrash | SUPPORTED | `trash`/`untrash` are distinct reversible methods; `delete` is a permanent-delete endpoint and is **forbidden** by `FULL_PRODUCT_SPEC` §7.1 and CONTRACT hands-off rules. |
| C7 | Send with native threading | SUPPORTED | Requires `threadId` plus `In-Reply-To`/`References` plus matching subject (`/gmail/api/guides/threads`). |
| C8 | Send correlation / reconciliation of an ambiguous send | **BOUNDED, NOT EXACT** | No provider idempotency key and no recall. Reconciliation is a bounded search of `SENT`; absence is not proof of failure. Unknown stays `needs-reconciliation`, never auto-resent (D3 semantics retained). |
| C9 | Attribution of an observed change (who did it) | **UNSUPPORTED** | History records carry no actor identity. Unmatched events stay unknown; never labelled human, never counted as agreement. |
| C10 | Provider-enforced read-only vs write separation | **TOKEN-LEVEL ONLY** | `gmail.readonly` is classified readonly; `gmail.modify` is **restricted**; `gmail.send` is **sensitive**. A same-user process cannot be isolated from another same-user process by the provider. Documented limitation, not a solved control. |
| C11 | Whether `gmail.modify` also grants send | **UNVERIFIED** | Not needed for D4 offline: the authorized Executor profile requests `gmail.send` and, where archive/trash is in scope, `gmail.modify`. Recorded rather than assumed. |

## 2. Frozen decision: how Gmail satisfies `MailSnapshot`

`MailExecutionIO` (`lifecycle_io.py:31-42`) keeps all three methods and gains none.
`runtime_checkable` only checks method presence, so the guards below are behavioural.

**`revision`** — SHA-256 over canonical JSON of `(connection_id, native_message_id,
thread_id, sorted(labelIds), message_historyId)`. It must change when any actor changes
the message. `apply_mail` re-reads it immediately before `modify` and, on mismatch,
returns `MailReceipt("failed", safe_code="mail_revision_conflict",
confirmed_no_effect=True)` exactly like `synth/mail_operations.py:106-109`. `confirmed_no_effect`
is returned only when the adapter verified no write occurred; `attempts.finish`
(`db/lifecycle_attempts.py:168-173`) admits a definitive FAILED only on that proof.
Conformance asserts **change detection**, never revision-string equality across providers,
because SimWorld digests the whole row and `MemoryExecutorIO` digests a subset.

**`label_versions`** — per-label count of *observed* label transitions for that message.
Built from Gmail's own `labelAdded`/`labelRemoved` history records, anchored on the
message `historyId` captured at effect time and already persisted in the attempt
`before_json`. Version at undo = baseline + observed transitions after the anchor.
This preserves the two guards that actually carry undo safety:

- `prepare_effect` (`lifecycle_operations.py:34-37`) predicts each touched label at `current + 1`.
- `prepare_undo` (`lifecycle_operations.py:76-83`) requires exact equality, so a remove-then-readd
  by another actor advances the count and refuses undo.

Forbidden, because each silently turns the ABA guard into dead or unusable code:

- returning `{}` — every legitimate undo fails (`test_wp6_mail_lifecycle.py:43,85`);
- returning a constant or a hash-derived pseudo-version — the ABA check always passes;
- substituting `labelIds` set equality for versions — remove-then-readd is invisible.

**When the anchor cannot be resolved** — a 404 on `startHistoryId`, a cursor gap, a
re-sync that dropped records, or an anchor older than the retained window — the adapter
raises a typed `MailConflict("undo_history_unavailable")`. It does not degrade to a guess.
Dependent effects stay blocked and readiness reports the reason.

`snapshot_mail` performs no write. It reads `messages.get` plus, for undo paths only,
one bounded `history.list` from the persisted anchor. The Executor derives versions from
the provider itself, **not** by reading the ingestor's observation rows, which keeps the
contract role table (`CONTRACT.md:84-90`) intact without a read-set extension.

## 3. Open blocker: undo window collides with history retention

`config.py:64` sets `undo_days: int = 7`; `mail_execution.py:296-298` computes the undo
deadline as execution time plus that window. Gmail history retention is documented at
about one week (C3). Therefore a label action requested for undo late in its own window
can be unprovable: the anchor that makes C2 sound may already have aged out.

Consequence, stated plainly rather than engineered away: the required live gate
"archive → undo → confirmed restoration" (`OCT29_DEMO_BUILD_PLAN.md` §10.2) is
**supportable only while the effect anchor remains inside the provider history window**.
Near the end of the window the correct behaviour is refusal with degraded readiness,
which is fail-closed but not the demonstrated success the acceptance row demands.

Proposed design change for owner review — **not applied unilaterally**: keep
`undo_days = 7` untouched, and gate Gmail label undo on an anchor-freshness check
(`anchor_history_id` resolvable, cursor continuous since effect, `now - executed_at`
below a connector-published `undo_provable_horizon`). If the owner instead prefers a
shorter Gmail-specific undo window, that is a spec change to a D3 constant and needs an
explicit decision; D4 does not change it, because lowering it would silently redefine
D3 acceptance. Until decided, live undo is reported **blocked-by-capability**, not passed.

## 4. Cohort, privacy and observation rules as implemented

- Selection is explicit native message IDs or an owner-provisioned label. No
  application-created Gmail filters, no mailbox-wide population, no settings endpoints.
- Cohort membership is verified **before** any body fetch. `messages.get` for a body only
  happens for selected resources; enumeration uses bounded `messages.list` pages.
- Account-wide history records outside the cohort are **discarded in memory**: no
  observation row, no identifier, no label name, no diagnostic payload is persisted or
  logged for them.
- A selected message stays tracked after `INBOX` removal — tracking follows the
  cohort label, not the inbox.
- Never fetched: attachments, remote images, any URL appearing in message content
  (CONTRACT I-24/T16).
- Three times stay distinct: provider occurrence (`internalDate`), observation time
  (`historyId` provenance), and local knowledge time from `core/clock.py`. A `Date`
  header is never evidence of when Probation knew something (I-6/I-7).
- `SENT` is an observation, never an incoming decision situation.
- History is never translated into "no changes" on failure; 404 forces explicit re-sync.
- Unmatched events stay unknown (C9); backfill and replay never grant live authority
  (FP-D2 behaviour retained).

## 5. Credential and OAuth profile

Installed-app flow, system browser, PKCE, loopback redirect. Read worker resolves
`gmail.readonly` only. Executor resolves `gmail.send`, plus `gmail.modify` only where
archive/trash or reconciliation is in scope; the broad modify grant never leaves the
Executor boundary (I-2, FP-D6). No `gmail` full-access scope, no domain-wide delegation,
no mailbox-settings administration, no redundant broader bundles.

Write-code exchange, callback and refresh live inside the Executor process; the
authorization listener belongs to that credential boundary, never the dashboard API.
OAuth state binds owner, role, intended account, redirect and expiry and is single-use;
completion verifies the returned account and the actual granted scopes before installing
a grant. Refresh is serialized per opaque credential reference with a generation guard so
a stale refresh cannot overwrite newer state. Missing scope, wrong account, revoked or
expired grant disables exactly the affected capability and halts dependent work; it never
falls back to another account or an app password.

Access tokens stay in process memory. Persisted refresh state and native receipts stay
under gitignored `data/private/` behind verified owner-only Windows ACLs; a failed ACL
check denies startup. Repository configuration holds opaque references only. Callback
query logging is suppressed; codes and tokens never enter URLs, arguments, command
payloads, logs, ordinary DB rows, prompts or screenshots.

Two documented limits stay in the handoff, not in marketing: Google's Testing publishing
mode expires refresh tokens for Gmail scopes after about seven days, and `gmail.modify`
being a restricted scope means Google verification or security-assessment obligations
attach to any distribution profile. Same-user process isolation proves only that the
application did not provision the write grant to the reader.

## 6. Released file locations and single owners

| Path | Contents | Owner |
| --- | --- | --- |
| `backend/src/probation/connectors/types.py` | Pure shared records: `NativeRef`, `SyncCursor`, `ObservationPage`, `SourceObservation`, `CapabilityManifest`, `CapabilityState`, typed failures | Integration owner |
| `backend/src/probation/connectors/__init__.py` | Package marker, no runtime deps | Integration owner |
| `backend/src/probation/packs/mail/connectors/` | Gmail transport, parsers, auth, read and write adapters | Split: read agent owns read files, execution agent owns write/auth files |
| `backend/src/probation/db/gmail.sql`, `db/gmail_*.py` | DDL, migrations, typed stores | Integration owner |
| `backend/tests/connectors/` | Fake-provider conformance and boundary regressions | Each agent owns its own new files |

`backend/tests/connectors/` is collected automatically: `check.py:131-135` runs
`backend/tests` whole and `backend/pyproject.toml:121-129` sets `testpaths = ["tests"]`.
Every real-provider test carries the registered `live` marker
(`backend/pyproject.toml:128`) so `-m "not live"` keeps `make check` offline and
secret-free. No test weakens, skips or deletes a baseline assertion; the 833 stay green.

`synth/world.py` (755 lines) and `workers/executor.py` (441 lines) already exceed the
~400-line rule, so no Gmail code is added to either.

Generic `preflight` and `compensate` from `FULL_PRODUCT_SPEC` §5.1 stay **proposals**.
Their mapping through the released adapter: preflight is `snapshot_mail` plus a
`CapabilityManifest` check before dispatch; compensate is a second `apply_mail` whose
payload is the preserved actual before-state, driven through the existing
`prepare_undo`/attempt machinery (`executor.py:105-121`, `mail_execution.py:228`).
No alternative effect path, no second action queue, no alternate sending route.

## 7. Storage ownership matrix as built

**Decision: connector bookkeeping lives in a dedicated private store, not the engine database.**
`FULL_PRODUCT_SPEC` §4.3 and the D4 plan both sanction this ("Use a dedicated connector
metadata store under the private namespace for new connection/sync records if this avoids
widening the engine database's existing role permissions"). Taking it means:

- `CONTRACT.md:84-90` role table stays byte-unchanged. `gmail_*` rows are not added to
  `ROLE_ALLOWED_WRITE_TABLES`, so §8 item 2 is **moot, not approved**.
- Imported mail still enters the engine through the existing, already-approved ingestor
  path (`sources`, `raw_items`, `situations`). No second observation pipeline.
- The private store is a separate SQLite file under `data/private/` with its own
  connection. `ATTACH` into the engine connection is impossible by design: `guards.py:46`
  permits writes only in `main`.
- The store holds no raw token and no out-of-cohort identifier of any kind.
- Migration for this store is local to the store file, additive, rerunnable and
  rollback-documented; engine migrations, ledger bytes and D3 rows are untouched.

New objects, DDL file `backend/src/probation/db/gmail.sql`, enforced by SQLite triggers
plus typed stores. Each row is claimed by exactly one role, and a second reader of the
same file cannot advance another role's row.

| Table | Writer | Key/uniqueness invariants |
| --- | --- | --- |
| `gmail_connections` | Bootstrap administration; state moves only via approved commands | one row per `connection_id`; `UNIQUE(account_id, connection_id)`; opaque `credential_ref`, never a token; identity columns frozen by trigger; `selection_revision >= 1` |
| `gmail_history_events` | Ingestor | cohort rows only; PK `(connection_id, history_id, native_message_id, event_type)`; append-only by trigger; the sole honest source of `label_versions` |
| `gmail_observations` | Ingestor | immutable; PK `(connection_id, native_message_id, history_id, event_type)` dedupes overlapping pages and repeated records; payload behind `payload_ref`; a tombstone carries no payload |
| `gmail_sync_cursors` | Ingestor only, scoped per connection | PK `(connection, resource_key, role, filter_revision)`; `committed_history_id` advances only with its committed page; `fence` strictly monotonic; a claim with an expired lease cannot write |
| `gmail_capabilities` | Read worker owns `read` rows; Executor owns `write` rows and native effect receipts | PK `(connection_id, name, owner_role)`; an unsupported row must carry a safe reason; `evidence IN ('supported','unsupported','unverified')` |
| `gmail_worker_leases` | The owning role; the coordinator only schedules | PK `(connection_id, job_key)`; `fence >= 1`, monotonic; expiry compared with `COLLATE UTC_TIMESTAMP` from injected Clock |
| `gmail_credential_state` | The process holding that credential role | PK `credential_ref`; `generation` strictly monotonic so a stale refresh cannot overwrite newer state; scopes and expiry only |

Ledger note: the `ledger.kind` CHECK constraint is frozen in `schema.sql:266-268`, so
connector events add **no** new ledger kind; D3's precedent is reusing `'outcome'` with
`ref_id = event_id`. Ledger bytes and all existing D3 rows stay byte-identical across
migration, rerun and rollback. No `ATTACH` into the engine connection: `guards.py:46`
permits writes only in `main`, so a private metadata store opens its own connection.

Implemented connection states: `UNCONFIGURED`, `AUTHORIZING`, `AUTHORIZED`, `BACKFILLING`,
`SHADOW`, `ACTIVE`, `PAUSED`, `DEGRADED`, `AUTH_REQUIRED`, `DISCONNECTED`.
`PURGE_PENDING` and purge/retention execution remain downstream and are **not** claimed.

## 8. Contract change requests

Stopping items for owner decision. D4 offline proceeds because none of them block
fake-provider work, and no live destination is contacted by this package.

1. **Named provider destinations.** `CONTRACT.md:84-90` allows the ingestor "Only the
   source" and the Executor "Only approved target apps/auth endpoints", and names only
   `api.tavily.com` literally. Neither enumerates `gmail.googleapis.com` or
   `oauth2.googleapis.com`. Request: enumerate both, bound to their roles, before any live
   call. Until then every real-transport test stays `-m live`.
2. **Cursor and lease homes for the ingestor.** `CONTRACT.md:82-90` assigns the ingestor
   `sources, raw_items, situations` while §5 assigns it "cursor durability", and
   `CONTRACT.md:96-100` forbids inferring new tables from that. Request: approve the
   §7 rows for `gmail_sync_cursors` and `worker_leases` per FP-D3.
3. **Forward semantics disagreement.** `CONTRACT.md` §9 with FP-D8 and FP-D13 permit an
   explicitly owner-approved forward; `FULL_PRODUCT_SPEC` §7.2 step 7 says forward remains
   suggestion-only. Applied rule: CONTRACT wins, so D4 keeps D3's restricted explicit
   forward with an empty allowlist (`WP6_D3_MAIL_CONTRACT.md`), and no model-selected
   recipient. Flagged because a spec-level reader may expect the opposite.

## 9. Requirement to test to owner

| Requirement | Package | Test id | Owner |
| --- | --- | --- | --- |
| C1 atomicity absent, never faked | D4-02 | `test_gmail_capability_matrix_marks_conditional_modify_unsupported` | Integration |
| revision changes on any external label edit | D4-08 | `test_gmail_revision_detects_external_change` | Execution |
| versions advance on remove-then-readd | D4-02/08 | `test_gmail_undo_refuses_after_label_removed_and_reapplied` | Execution |
| no fabricated versions when history unavailable | D4-02 | `test_gmail_snapshot_fails_closed_on_stale_anchor` | Execution |
| reader cannot resolve write grant | D4-05 | `test_read_worker_denies_write_credential` | Execution |
| OAuth state/PKCE/account/scope/expiry/replay | D4-05 | `test_oauth_*_fails_closed` | Execution |
| cohort enforced before body fetch | D4-06 | `test_out_of_cohort_history_stores_nothing` | Read |
| bounded MIME parsing | D4-06 | `test_mime_limits_*` | Read |
| atomic page and cursor commit | D4-07 | `test_crash_before_page_commit_repeats`, `test_crash_after_commit_does_not_duplicate` | Read |
| stale cursor forces resync not empty poll | D4-07 | `test_404_history_triggers_resync` | Read |
| competing workers fenced | D4-07 | `test_second_worker_cannot_advance_cursor` | Read |
| no peeking from live projection | D4-08 | `test_historical_read_issues_no_provider_call` | Read |
| unknown send never resent | D4-08 | `test_ambiguous_send_needs_reconciliation_no_resend` | Execution |
| migration preserves ledger and D3 rows | D4-04 | `test_gmail_migration_unchanged_ledger_bytes` | Integration |
| offline gate stays offline | D4-09 | `check.py` whole-suite run with `-m "not live"` | Integration |

## 10. Resolution log (post-implementation)

Decisions taken during the build, so the next agent does not re-litigate them.

**Accepted**
- `attribution` was added to `CapabilityName` (and to the `gmail_capabilities` CHECK). The matrix needs a truthful home for C9, which the original list could not express.
- `gmail_command_receipts` was added to the private store. Owner pause/resume/revoke intents are written through D3's `command_requests`, but `command_receipts.consumer` in the engine schema is fixed to `resolver|executor|examiner`. Rather than migrate the engine schema, the connector consumer records its own idempotent receipt in the private store, in the same transaction as the state change.
- `resource_id` for a Gmail effect is the **native Gmail message id**, confirmed against `core/review_binding.py` which binds `source_ref`/native ids. Gmail has no RFC-Message-ID lookup, so an RFC id can never be the handle.
- The credential API is the richer one already exercised by `test_credential_isolation.py` and `gmail_auth.py` (`SecretMaterial`, `TokenBundle`, `RoleCredentialProvider`, `build_child_env`, generation-guarded state repositories). The smaller intermediate version was discarded because three test modules depend on the richer shape and it carries the stronger canary coverage.

**Accepted as an operating requirement, not code**
- Undo provability requires the ingestor to have committed provider history. The Executor therefore fails closed (`undo_history_unavailable`) until a change reaches the local observation log. The live runbook must state a poll interval comfortably below the undo window; this does not change `undo_days = 7`.
- Rebase/live deployment must call `configure_gmail_api(...)` and `verify_loopback_binding(host)` before serving; the router is mounted but refuses to serve unconfigured.

**Declined for D4, recorded as follow-ups**
- Durable effect anchors: `GmailMailExecutionIO` keeps anchors in memory by default. After a restart an in-flight undo fails closed instead of being provable. That is safe and contract-compliant, so the DDL was not changed late in the build. A resource-keyed anchor row is the follow-up.
- Append-only reconciliation chain: receipts are immutable and keyed by `operation_id`, so a reconciled send outcome is returned but not appended. Documented, not silently dropped.
- Store-level capability row ownership: `read_worker` and `executor` both hold table-level write access to `gmail_capabilities`; `name`/`owner_role` are constrained by CHECK and by the typed API. A table-level authorizer cannot distinguish rows, so this remains a code-level control.
- `gmail_sync` retains a private history-filter helper that duplicates `gmail_read.cohort_transitions`. Both discard out-of-cohort records; the duplication is a maintenance risk and is recorded in the build log.
- `messages.untrash` implicit INBOX behaviour is unverified offline. It must be exercised only under the live gate.

**Interface requests (open, kept visible by tests)**

- **IR-D4-1 — backfill cohort is not yet stamped onto a commitment.** The released projection
  (`gmail_projection.py` `as_raw_item`) emits `retrospective`/`evidence_context` on every record,
  and `core/permission_history.py` already honours them and drops such a record from qualifying
  evidence. But the only writer of proposal commitments, `db/proposals.persist_proposal`, builds
  its ledger payload from a fixed field list containing neither key, so a Gmail backfill imported
  through the ordinary path is committed as ordinary prospective evidence. D4 does not change a
  shared (D3-owned) file to close it; `test_backfill_label_is_not_yet_carried_by_the_writer`
  keeps the gap visible instead of reporting it closed.
- **IR-D4-2 — no concrete HTTP transport ships in `src/`.** `HttpTransport` (types) and
  `TokenTransport` (auth) are Protocols and `RetryingReadTransport` only wraps and delegates. There
  is no concrete httpx client for `gmail.googleapis.com`/`oauth2.googleapis.com` in source; every
  transport test uses the faithful fakes, and the two real-transport tests carry `-m live` and are
  the only ones deselected. The concrete client belongs to live acceptance (part 2), which also
  requires contract change request §8.1 to be resolved first.
- **IR-D4-3 — forward is deliberately unthreaded and its allowlist lives in D3.** A forward is a
  new message: `_reply_address` returns no `threadId`/`In-Reply-To`/`References` for it, and the
  empty allowlist is enforced at the D3 contract layer, not inside the connector. Row 25 stays
  PARTIAL for that reason; the send path itself is generic and exact-payload.

## 11. Offline completion checklist (authoritative)

Derived by walking the approved D4 plan section by section against the code. A row is only
ticked when a named test or an inspected file proves it.

| # | Plan requirement | Status | Proof / gap |
| --- | --- | --- | --- |
| 1 | Branch, isolated worktree, baseline hashes, ownership, no copied unfinished files | **DONE** | §0; `git worktree list`; all worktree tips ancestry-checked |
| 2 | Provider capability matrix with evidence; unsupported capability blocks dependent effects | **DONE** | §1; `test_gmail_capability_matrix_marks_conditional_modify_unsupported`, `test_capability_gate_blocks_unsupported_effect_before_dispatch` |
| 3 | No invented If-Match, no local lock reported as provider atomicity, D3 conflict tests unweakened | **DONE** | `gmail_versions.py`; D3 modules unchanged (hash-locked) |
| 4 | Role-separated credential injection, no shared parent env, no creds in args/logs/URLs/prompts | **DONE** | `test_credential_isolation.py`, `build_child_env` |
| 5 | Access tokens memory-only; refresh state private + owner-only ACL; ACL failure denies startup | **DONE** | `test_private_acl.py`; `RefreshTokenStore` applies then verifies |
| 6 | OAuth state bound to owner/role/account/redirect/expiry, single use, PKCE | **DONE** | `test_gmail_auth.py` |
| 7 | Verify returned account and actual scopes before installing a grant | **DONE** | `test_gmail_auth.py` |
| 8 | Serialized refresh with stale-generation protection; revoked/expired disables capability | **DONE** | `test_stale_generation_cannot_overwrite_newer_state`, `test_revoked_grant_never_resolves_again` |
| 9 | Loopback callback belongs to the credential boundary, not the dashboard API; query logging suppressed | **DONE** | `gmail_auth.py` `ThreadingHTTPServer(("127.0.0.1", 0), …)`; canary-absence test |
| 10 | Cohort membership verified before body fetch; out-of-cohort history stores nothing | **DONE** | `test_non_cohort_id_triggers_zero_body_requests`, `test_out_of_cohort_history_stores_nothing` |
| 11 | Tracking survives archive; no filters; no attachments/remote images/body URLs | **DONE** | `test_tracking_survives_archive_after_inbox_removed`, MIME tests |
| 12 | Bounded MIME parsing; header-injection defence; ambiguous parsing fails closed | **DONE** | `test_gmail_mime.py` |
| 13 | Bootstrap anchor → paged atomic commit → catch-up → watermark | **DONE** | `test_gmail_sync.py` |
| 14 | Duplicate pages, tombstones, opaque history ids, stale-cursor resync | **DONE** | `test_gmail_sync.py` |
| 15 | Crash before/after page commit; competing workers fenced | **DONE** | `test_crash_before_page_commit_repeats`, `test_crash_after_commit_does_not_duplicate`, `test_two_competing_workers_exactly_one_advances` |
| 16 | 30 s poll, bounded batches, interruptible waits, persist before acknowledging | **DONE** | `gmail_observation.py`; `test_pause_blocks_dispatch_and_advance_until_consumed_resume` |
| 17 | Live `WorldView` from committed observations; historical read issues no provider call | **DONE** | `gmail_projection.py` guard; `test_historical_read_issues_no_provider_call` |
| 18 | Three distinct times; `Date` header never knowledge time | **DONE** | `test_three_times_stay_distinct` |
| 19 | Sent is an observation, not a decision situation | **DONE** | `test_sent_observation_never_becomes_decision_situation` |
| 20 | Probation effects add no human agreement; unknown attribution stays unknown | **DONE** | `test_probation_label_change_adds_no_agreement`, `test_unknown_attribution_adds_no_evidence` |
| 21 | Backfill cannot grant live authority; resync cannot duplicate/erase/restore | **DONE** | `test_backfill_cannot_grant_live_authority`, `test_resync_does_not_duplicate_or_restore` |
| 22 | Archive/trash before-state, unrelated labels preserved, no permanent delete/settings | **DONE** | `test_gmail_write.py`; `gmail_write.py` endpoint allowlist |
| 23 | Refuse undo when touched-state history is incomplete/conflicting | **DONE** | real `prepare_undo` ABA test; `undo_history_unavailable` |
| 24 | Reply: exact stored content, original sender, no CC/BCC/attachments, stdlib MIME + base64url, threading headers | **DONE** | `build_raw_message`; send tests |
| 25 | Forward: explicit controlled recipient, empty allowlist, no model-selected destination | **PARTIAL** | send path is generic and exact-payload; the empty allowlist is enforced at the D3 contract layer, not inside the connector — recorded |
| 26 | Ambiguous send: intent before HTTP, bounded Sent reconciliation, no resend, not-found ≠ failure | **DONE** | `test_ambiguous_send_stays_unknown_and_is_never_resent` |
| 27 | Pause/revoke/disconnect block before the next effect; degraded write readiness keeps observation | **DONE** | `test_pause_command_blocks_next_effect`, `test_disconnected_stops_observation_and_revocation_outranks_pause`, `test_failed_write_grant_keeps_observation_and_degrades_write_readiness` |
| 28 | Bounded retries, capped backoff, `Retry-After`, no spin on auth failure | **DONE** | `gmail_observation.py`; `test_retries_are_bounded_and_degrade_without_advancing` |
| 29 | Observation gap / stale freshness blocks dependent autonomy | **DONE** | `test_resync_gap_degrades_readiness_and_blocks_dependence`, `test_stale_source_freshness_blocks_dependent_autonomy` |
| 30 | **Committed observations reach the existing Ingestor → Brain pipeline** (plan §2 diagram) | **DONE** | `gmail_ingest.py` `GmailIngestBridge` writes `sources`/`raw_items` and reuses the unchanged `ingest_situations`; `test_gmail_ingest.py` |
| 31 | **Always-on local runtime: observation/Brain/Resolver/Examiner/API/Executor with own dependencies and role-bound connections; coordinator gets status, not write credentials** | **DONE** | `gmail_runtime.py` composes one process per role, role-bound engine connections, allowlisted child env; `test_gmail_runtime.py`, `test_gmail_worker_runtime.py` |
| 32 | Migration: populated prior-schema upgrade, rollback, rerun, unchanged ledger bytes/protected hashes | **DONE** | Engine schema untouched by design (no prior connector schema to upgrade); rerun + rollback + ledger-byte/protected-hash evidence in `test_gmail_migration_evidence.py` |
| 33 | Live-proof kit: dry-run manifest, no account access, vault follow-up package | **DONE** | `docs/D4_LIVE_TEST_MANIFEST.md`, `docs/WP12_D4_CREDENTIAL_VAULT_FOLLOWUP.md` |
| 34 | Full repository gate on the final integrated source | **DONE** | `scripts/check.py` passes on the integrated tree (ruff, format, mypy x2, non-live pytest, protected-hash check) |

**Explicitly out of offline scope** (unchanged by this checklist): live account access, OAuth
exchange, any Gmail request, provider spend, deployment, push, merge, D5, frontend, other
connectors.

## 12. Observation payload contract (frozen)

The read path must persist the bounded, already-parsed message content that the engine bridge and
the proposal path need. Without it, situations are contentless and the pipeline is decorative.

- **Location:** `<private_root>/connectors/payloads/<connection_id>/<native_message_id>.json`.
  `payload_ref` stored in `gmail_observations` is the **relative** path below `payloads/`, never an
  absolute path, never a token, never a URL.
- **Writer:** the read/observation path only, after `apply_owner_only` + `verify_owner_only` on the
  directory; written atomically (temp file in the same directory + `os.replace`), then the
  observation row is committed. A payload without a committed observation is garbage and may be
  overwritten; an observation whose `payload_ref` is missing is a hard ingest error, never an empty
  message.
- **Limits:** exactly the four MIME bounds already enforced; the on-disk JSON is capped and
  re-checked on read. No attachments, no HTML source, no remote images, no URLs extracted from the
  body.
- **Fields (exact):** `native_message_id`, `thread_id`, `rfc_message_id`, `from_addr`, `to_addr`,
  `cc_addrs` (list), `subject`, `body_text`, `occurred_at`, `attachment_present` (bool),
  `content_hash`.
- **Reader:** the engine bridge takes an injected `PayloadReader`; a missing or hash-mismatched
  payload raises a typed error. Hash mismatch means the file changed under us — fail closed.
- **Provenance:** `occurred_at` comes from `internalDate`. It is never used as knowledge time; the
  observation row's `observed_at` remains the only knowledge time.
- **Retention:** deletion of payloads is not part of D4 (purge stays downstream). A tombstone does
  not delete a payload in this package.


