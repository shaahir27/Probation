# Full-product delivery specification

Revision 2, 22 October 2026. Status: **planned; no implementation or live account verification claimed**.

This document expands the existing [implementation plan](CHANGES_IMPLEMENTATION_PLAN.md) to cover the user's complete request, including all named connectors and additions in `changes.md`. Read it with the [original verification report](reports/changes-audit-2026-10-22.md), [opinion review](PRODUCT_OPINION_REVIEW.md), and [source coverage register](reports/changes-coverage.csv).

## 1. Exact completion boundary

“Fully complete” means every mandatory F01-F42 capability below has implemented behavior, reviewed governing decisions, appropriate tests, release evidence and operator documentation. Development staging is allowed; silently dropping a feature to meet a date is not. An unavailable provider, missing authorization, failed experiment or unfinished connector remains visible and blocks that capability. A prototype or hackathon submission can be a labelled intermediate release, not proof of full completion.

The finite connector set is Gmail API, Google Calendar API, local filesystem, Notion, IMAP observation, private iCal observation, an MCP client adapter and Probation's MCP server. The runtime integrations include OpenShell, Hermes and NemoClaw. This does not mean automatic compatibility with every email vendor, arbitrary MCP server or future service. Each configured provider/profile requires a manifest and conformance evidence.

All six domain packs are required: mail, calendar, files, chains, Radar and Reading. The complete chain set includes REPLY draft/send under mail rules, BLOCK_TIME and CREATE_TASK. All section-13 upgrades are retained as delivery obligations or explicit provider-availability decisions; none is marked implemented merely because its feasibility was investigated.

The product remains a single-owner assistant with local private data and a separate synthetic public demo. Screen/keystroke recording, monitoring other accounts, payments, applying to opportunities, sharing personal documents, permanent deletion, multi-user SaaS accounts, model fine-tuning and the dropped GitHub pack are not introduced by this expansion. Existing contract non-goals still apply. Ambiguous “irreversible” wording versus explicitly supported held replies/RSVPs requires clarification, not unilateral reinterpretation.

No plan can prove future code perfect. This specification makes completion falsifiable: each claim has an implementation boundary, a negative test and required evidence.

## 2. Complete capability register

`Core WP` refers to sections of `CHANGES_IMPLEMENTATION_PLAN.md`. `Extension` sections below add the previously incomplete implementation detail. Every row is required for the full requested profile. Provider-dependent rows cannot close as “done” while their required provider is unavailable; any substitute requires an explicit recorded scope decision.

| ID | Deliverable | Implementation location | Required acceptance evidence |
|---|---|---|---|
| <a id="f01"></a>F01 | Governing decisions, setup, command contract, logs and clean checks | Core WP0; this spec 3 | Resolved decisions, correct CLI, unchanged fixtures/results during tests, phase handoffs |
| <a id="f02"></a>F02 | Strict schemas, ledger, roles and atomic storage | Core WP1 | V01-V05/V10; rollback/concurrency/corruption tests |
| <a id="f03"></a>F03 | Truth identity, observation chronology, replay and backfill provenance | Core WP2; extension 6 | V07-V10; live history boundary tests and complete primary joins |
| <a id="f04"></a>F04 | Personalized policy, calibration, novelty, files folders and bounded clues | Core WP4 | V11-V13; chronological evaluation and performance scaling |
| <a id="f05"></a>F05 | Versioned prompts, required readers, redaction, cache and budgets | Core WP3 | V06/V23/V24; request capture and approved provider smoke |
| <a id="f06"></a>F06 | Validated reply writer, real editing and style evaluation | Core WP3; extension 14 | Persisted generated/edited draft provenance, no unsupported send, style results |
| <a id="f07"></a>F07 | Derived per-class/action permissions and consistent API/executor view | Core WP5 | Golden bounds, age/recent/strong/parent cases, fresh recheck |
| <a id="f08"></a>F08 | Real exams across every active pack and candidate level | Core WP5 | V14-V15; fitted cheating-policy failure, valid controls and case coverage |
| <a id="f09"></a>F09 | Feedback, actions, idempotency, hold, cancel, undo and reconciliation | Core WP6; extension 5 | V16-V20; per-connector failure/restart tests |
| <a id="f10"></a>F10 | Durable correction drift and model-driven family shift | Core WP6 | V21-V22; two-undo restart, behavior/covariate controls |
| <a id="f11"></a>F11 | Readable time-bounded habits and safe user corrections | Core WP8; extension 14 | No future support, meaningful wording, denial/correction does not edit authority |
| <a id="f12"></a>F12 | All three cross-tool chain actions | Core WP8; extensions 9/10 | Reply + block + task, separate evidence/caps/exams, full undo where recallable |
| <a id="f13"></a>F13 | Complete live/synthetic Radar | Core WP7; extension 10 | Guarded discovery→Extract→quarantine→cited tracker; no apply/pay/share |
| <a id="f14"></a>F14 | Complete live/synthetic Reading Triage | Extension 10 | Saved-link intake→typed clues→file/archive→Notion→undo/exams |
| <a id="f15"></a>F15 | Correct entity vetting and verified domain catalog | Core WP7 | E10 legitimate/fictional confusion matrix and false-veto regression |
| <a id="f16"></a>F16 | Provenance-aware URL sanitization, quarantine and citations | Core WP7 | V25-V27; no mail-body fetch and no raw-page writer exposure |
| <a id="f17"></a>F17 | Gmail REST observation and safe archive/trash/reply/forward execution | Extension 7 | Read/write scope isolation, sync recovery, exact effect and send ambiguity tests |
| <a id="f18"></a>F18 | Google Calendar observation, RSVP and private time blocks | Extension 8 | Recurrence/timezones, scope/ETag tests, held RSVP and private-block undo |
| <a id="f19"></a>F19 | Always-on local file observation and safe moves | Extension 9 | No root escape, duplicate watcher events, crash recovery, real restoration |
| <a id="f20"></a>F20 | Versioned Notion integration for Radar/Reading/tasks | Extension 10 | Data-source/property mapping, pagination, separate capabilities, idempotent writes |
| <a id="f21"></a>F21 | IMAP compatibility observation | Extension 11 | Read-capability enforcement, UIDVALIDITY recovery, Sent linkages, no mark-seen/write |
| <a id="f22"></a>F22 | Private iCal feed observation | Extension 11 | Secret-URL protection, snapshots/ETag/deletions/recurrence; no invented RSVP capability |
| <a id="f23"></a>F23 | MCP client with explicit pack/tool mappings | Extension 12 | Pinned schema/transport/server, role restrictions, malicious-tool denial |
| <a id="f24"></a>F24 | Probation MCP permission/proposal/explanation service | Extension 12 | Exact action binding, current authority recheck, caller authentication, no bypass |
| <a id="f25"></a>F25 | Supervised always-on role runtime | Extension 13 | Leases/cursors, restart/backpressure, durable hold/undo, pause/revoke gates |
| <a id="f26"></a>F26 | Complete connection/consent/onboarding/disconnect experience | Extensions 4/15 | Scope preview, backfill/shadow/live states, denied/revoked/offline cases |
| <a id="f27"></a>F27 | Complete truthful dashboard and every contracted API route | Core WP9; extension 15 | Real backend browser tests, deep links, accessibility, uniform errors |
| <a id="f28"></a>F28 | Real baselines, all listed ablations and multi-persona evaluation | Core WP10; extension 16 | Reproducible split/manifests/deltas/intervals and negative results |
| <a id="f29"></a>F29 | Measured model tiers and Nano→Super cascade | Extension 14 | Same held-out form dataset, cost/latency/escalation/error evidence |
| <a id="f30"></a>F30 | Ultra targeted exam edits and a restriction-only guard-model integration decision | Extension 14 | Allowed Nemotron endpoint, bounded edits, code verdicts; supported guard or explicit unresolved provider blocker |
| <a id="f31"></a>F31 | Enforced OpenShell profile | Extension 17 | Actual versioned effective policy and denied network/filesystem probes |
| <a id="f32"></a>F32 | Hermes interoperability profile | Extension 17 | Pinned runtime connects, proposes/checks/explains, cannot execute around Executor |
| <a id="f33"></a>F33 | NemoClaw interoperability profile | Extension 17 | Pinned supported profile/provider, restricted egress and same no-bypass proof |
| <a id="f34"></a>F34 | Nebius serverless/parallel evaluation execution | Extension 17 | Real synthetic job records, reconciled outputs/usage and chronological replay preserved |
| <a id="f35"></a>F35 | Skills manifests and learned-about-you correction UI | Extension 15 | Actual readiness, six-question pack details, evidence-preserving correction |
| <a id="f36"></a>F36 | Signed portable permission receipt | Extension 18 | Exact scoped signature, expiry/rotation/revocation/anti-replay and recheck tests |
| <a id="f37"></a>F37 | Controlled sender checker, TTL re-vetting and full web/exposure transparency | Extension 15 | Public-domain-only request path, independent budget cap, exact recorded queries/sources/history |
| <a id="f38"></a>F38 | Real Nemotron-Personas-India source integration and attribution | Extension 16 | Dataset revision/hash/synthetic lineage and engine truth isolation |
| <a id="f39"></a>F39 | Actual approved human study on synthetic stimuli | Extension 16 | Consent protocol, anonymous decisions, measured study distinct from simulation |
| <a id="f40"></a>F40 | Private deployment and reliable synthetic public demo | Core WP11; extension 19 | Packaged runtime, secret/data isolation, fault drills, external-browser proof |
| <a id="f41"></a>F41 | Honest README, video, results, feedback and submission | Core WP11; extension 20 | Claim→artifact register, licence/setup/reproduction, required access and maintenance |
| <a id="f42"></a>F42 | Operator controls, retention, backup/restore, upgrades and support | Extensions 4/13/19 | Restore drills, disconnect/purge policy, service SLOs, migration/rollback runbook |

## 3. Approved directions and remaining implementation/operational gates

The owner approved the recommended D1-D9 directions on 22 October 2026 and
expressly delegated the CONTRACT v2 amendment. The historical audit remains evidence
of the original conflicts. [The approval register](CONTRACT_AMENDMENT_2026-10-22.md)
maps every FP gate below. Architecture approval does not imply implemented schemas,
new role grants, live resource authorization or feature completion.

| ID | Conflict or missing contract | Approved direction | Remaining gate |
|---|---|---|---|
| FP-D1 | Source/since interface versus raw-item implementation | Keep public source/since with shared internal raw-observation mapping (D5). | Adapter/cursor conformance implementation. |
| FP-D2 | Real backfill versus I-7 prospective commitment | Use eligible backfill for training and separate retrospective runs; live autonomy evidence starts prospectively. | Enforce provenance/cohort isolation and I-7; no live qualification from reconstructed predictions. |
| FP-D3 | New connection/cursor/command/event tables not in role matrix | Explicit per-role/per-row ownership; immutable events/intents and worker-owned results. | Exact connector/cursor/lease/budget DDL, constraints, role matrix and migration review before use. |
| FP-D4 | SECURITY_PRIVACY previously allowed environment-only secrets; refresh tokens/receipt keys need a lifecycle | Role-protected OS credential store/deployment secret manager or environment injection. | Choose/test concrete store, refresh/rotation/revocation, dependencies and provisioning; no keys approved here. |
| FP-D5 | API may write only user_responses but Connections, pause, habits, receipt revocation and admin operations need commands | Typed API command requests consumed by their designated role; no raw tokens. | Versioned lifecycle request/receipt schemas, consumer ownership and auth tests. |
| FP-D6 | Only Executor holds write credentials; ordinary OAuth callbacks/MCP servers may hold them elsewhere | Write-grant exchange/refresh/callback inside trusted Executor deployment boundary; separate observation grants. | Registered flow/endpoints, account/resource scopes and isolated secret delivery. |
| FP-D7 | I-1 data-only LLMs versus Hermes/NemoClaw model-controlled tools | External runtimes/MCP submit validated proposals; protected writes remain Executor-only and internal LLMs data-only. | Pinned runtime/tool manifests/transport and no-bypass proof; no arbitrary external write authority. |
| FP-D8 | CONTRACT non-goal “anything irreversible” versus held REPLY/RSVP action catalog | Supported non-recallable replies, owner-approved forwards and RSVPs permitted under cap/hold/approval rules. | Catalog/effect evidence and clear cancellation versus undo; prohibited permanent destruction/payments/sharing remain blocked. |
| FP-D9 | Public fixture-only Tavily rule versus proposed public live domain checker | Bounded domain-only, independently quotaed Webfacts-owned public checker design. | Endpoint/abuse design, explicit public deployment and live resource/spending authorization. |
| FP-D10 | Full scope versus old cut lines and phase numbering | All F01-F42 and six packs retained under original phase ownership/dependencies. | Per-feature acceptance evidence; any incomplete release is labelled partial. |
| FP-D11 | Editable habits versus evidence-derived authority | Descriptive edits/denial allowed; semantic corrections become prospective provenance-bearing feedback. | Exact request/consumer/UI behavior; never mutate historical counts, caps or policy labels directly. |
| FP-D12 | Human participants versus synthetic-only agent workflow | Separate consented study on synthetic stimuli with anonymous decision records/aggregates. | Concrete protocol/withdrawal/retention and authorization for recruitment/collection; simulation is not the study. |
| FP-D13 | FORWARD is in the catalog at suggestion-only cap, but the current response contract lacks a forwarding-recipient field | Explicit owner-selected validated forward recipient and immutable reviewed payload; REPLY stays original-sender-only. | Dedicated forward content/attachment/request/provider contract, versioning and send-reconciliation tests. |

No credential, signing key, private feed or real export should be pasted into an agent chat. Development tests use fabricated credentials and synthetic provider resources. Live verification requires explicit authorized account/resource scope later.

## 4. Connection, permission and privacy model

### 4.1 Separate authority layers

The application must display and enforce four distinct grants:

1. **Provider authorization:** the account's OAuth/API/OS permission to access selected resources.
2. **Observation consent:** the owner permits history import and continued observation of specified folders/labels/calendars/data sources.
3. **Execution consent:** the owner enables the specified action types/resource targets. This is an on/off restriction, not a stored licence or authority increase.
4. **Earned authority:** the current evidence/exam/cap/novelty/economics decision for this exact class/action, freshly derived at execution.

Any layer can restrict. A provider's broad token does not authorize using every resource. Enabling a connection or a skill does not set licence level 2/3. Revoking an execution grant increments a restriction revision and invalidates queued receipts; resume requires a fresh check. A user can pause a task, pack or connection without altering historical evidence.

### 4.2 State machines

Connection lifecycle: `UNCONFIGURED → AUTHORIZING → AUTHORIZED → BACKFILLING → SHADOW → ACTIVE`, with `PAUSED`, `DEGRADED`, `AUTH_REQUIRED`, `REVOKED`, `DISCONNECTED` and `PURGE_PENDING` as explicit states. These are proposed application states, not current schema values.

Execution-enablement state is separate from sync state. ACTIVE means healthy selected capabilities, not guaranteed autonomy. A failed write credential must not disable unrelated read observation invisibly; the UI shows the specific degraded capability.

Required transitions:

- Cancel OAuth: no partial token, connection or duplicated authorization record.
- Read grant only: backfill/shadow available; write action unavailable with a reason.
- Upgrade write scope: separate explicit grant; previous queued actions remain ineligible until revalidated.
- Pause: stop new execution immediately, invalidate pending authority and define whether observation continues according to selected pause scope.
- Disconnect: stop observations/execution, revoke local grant and queued jobs, optionally revoke provider tokens; restore after reconnect only with fresh account/resource verification.
- Purge: remove permitted private content/projections according to approved retention design while preserving the append-only ledger and required non-content audit facts. Never promise deletion of remote recipient copies, provider backups or historical ledger bytes.

### 4.3 Data and credential storage

Private content remains under `data/private/` on the owner's installation; public demo has a separate synthetic volume and independent provider keys. Encrypt private backups and use approved device/disk controls. Do not describe redaction as anonymization or cloud-provider retention as zero unless verified.

Store only opaque credential references and granted capability metadata in the application DB. Read tokens belong to read roles; write tokens and signing credentials belong to the approved execution boundary. A broad IMAP app password is not read-only just because code opens a mailbox read-only. Either enforce a real constrained credential/gateway or block that observation profile under I-2 until approved.

OAuth implementation must use registered flow/redirects, state and PKCE where appropriate, bind completion to the initiating owner, verify returned account/scopes, handle refresh rotation/revocation, and exclude tokens/codes/private URLs from logs. Desktop flow and hosted private flow are different profiles with separate registered redirects. The [Google installed-app flow](https://developers.google.com/identity/protocols/oauth2/native-app) documents system-browser and loopback authorization; choosing the hosted flow requires its own tested registration.

Acceptance: consent/scope denial, state mismatch, wrong account, overbroad token, expired/revoked grant, refresh race, pause during an in-flight hold, disconnect during retry and backup restore all fail safely. These are required tests, not explanatory UI only.

## 5. Proposed interfaces, durable storage and migrations

### 5.1 Common connector contracts

Proposed pure types live in `backend/src/probation/connectors/types.py`; transport implementations live under pack connector modules. The names below define planned interfaces, not currently existing methods.

```python
class ReadConnector(Protocol):
    def capabilities(self) -> CapabilityManifest: ...
    def snapshot(self, request: SnapshotRequest) -> ObservationPage: ...
    def changes(self, cursor: SyncCursor, limit: int) -> ObservationPage: ...
    def get_observation(self, native_ref: NativeRef) -> SourceObservation: ...

class WriteConnector(Protocol):
    def preflight(self, action: ValidatedAction) -> PreflightResult: ...
    def apply(self, action: ValidatedAction, key: ActionId) -> ConnectorResult: ...
    def reconcile(self, intent: ExecutionIntent) -> ReconciliationResult: ...
    def compensate(self, undo: UndoRecord, key: ActionId) -> ConnectorResult: ...
```

`SourceObservation` carries connection/resource/native ID, native version, occurrence time when trustworthy, system observation time, source-known-time provenance, content hash, event type, sanitized metadata and raw local content reference. It never trusts a provider field labelled `updated` as proof of when the system knew a decision.

`ObservationPage` contains immutable observations, next-page cursor, next-sync cursor and a complete-page watermark. Persist page observations and the corresponding cursor atomically. A crash cannot advance past uncommitted events. Never share a cursor between accounts, resources, filter revisions or protocol versions.

`CapabilityManifest` specifies provider/version, supported resources/actions, read/write requirements, provenance quality, reversible/non-recallable behavior, max scope, idempotency/reconciliation method and conformance test result. Server-advertised MCP annotations are input, not trusted manifests.

`ConnectorResult` distinguishes confirmed success, confirmed failure and ambiguous effect. Preserve provider-native receipts locally without secret/content leakage. Existing `ExecResult` adaptation and status changes require reviewed schema/API decisions; do not map ambiguous send to an automatic retry.

### 5.2 Proposed persistent objects

| Object | Main keys/invariants | Proposed write owner |
|---|---|---|
| connections | Stable connection ID; provider/account binding; resource selection revision; no raw token | Ingestor for observation metadata; lifecycle changes via approved commands |
| sync_cursors | `(connection, resource, role, filter_revision)`; versioned committed watermark | Ingestor/resolver only for their owned cursor rows |
| source_observations | Immutable native version + observation ID; local payload reference; no answer key | Ingestor |
| outcome_events | Immutable event/response/action IDs, known time, strength/source; no destructive replacement | Resolver for normal feedback/footprints; Executor for undo events, per approved matrix |
| command_requests | Immutable owner/action payload; idempotency key; no credentials | API |
| command_receipts | One designated consumer per typed command; feedback has separate role-owned decision and execution receipts keyed by request/consumer | Designated consumer role only; no cross-role result writes |
| execution_attempts | Durable action/attempt IDs, expected native version, confirmed/ambiguous result, reconciliation status | Executor |
| policy_snapshots | Complete model/encoder/calibration/feature provenance; immutable version and as-of | Approved training owner, proposed examiner |
| worker_leases | Role/resource/job key, monotonic fencing token, expiry from Clock | The owning role; scheduler merely coordinates |
| budget_reservations | Attempt/model or endpoint bound, durable reservation/reconciliation and charged retry accounting | Existing LLM-calling roles/webfacts, explicit owned rows |
| restriction_events | Pause/scope/revoke revision; irreversible append of restriction decisions | Approved command consumer; never model-written |
| receipt_revocations | Receipt/key ID, restriction revision, reason/time | Approved signing/execution owner |

Every table needs approved DDL, indexes, role permissions, migrations, strict models, retention classification and tests before use. No new table silently expands `RoleAccess` from the API.

### 5.3 Migration and release procedure

1. Back up a closed/consistent SQLite snapshot and verify its ledger before upgrade.
2. Test migration on a synthetic copy of each supported prior schema, including existing outcome collisions and old ledger payload names.
3. Add new structures without changing historical ledger payload/hash/sequence. Keep original outcome provenance when building an event projection; record migration origin explicitly.
4. Validate row counts, foreign keys, current-state projections, as-of queries and invariant queries before enabling workers.
5. Preserve schema/version compatibility checks; prevent an old worker from consuming new-format commands.
6. On failure, leave actions disabled and restore a compatible snapshot. Once external effects have occurred, do not restore an old DB and blindly repeat them; reconcile the durable execution journal first.

Acceptance includes concurrent double-clicks, worker duplication, connection loss after write, process death before receipt persistence, stale lease owner, partial page sync and migration rollback. No “exactly once” claim is allowed for an unconstrained remote service.

## 6. Backfill and learning without invented historical proof

Backfill is required for mail/Sent, calendar, Notion histories available through selected APIs and file observations/snapshots. Its limits must be visible.

1. Ask for explicit resource selection, date range, maximum items and redaction/exposure policy; show an estimate before any costly model processing.
2. Import native source artifacts with deduplication and source revisions. Preserve received/sent timestamps, thread/reference IDs, invitation metadata, current labels/statuses and the actual import observation time separately.
3. Do not infer old archive times from current INBOX absence, old file-move times from one current directory listing, or past RSVP timing from the latest event update. Mark such facts snapshot-derived or uncertain and apply conservative known time/strength/censoring rules.
4. Build historical training/replay datasets with explicit source-availability assumptions. Historical replay has its own run/ledger namespace and is labelled retrospective; it is not represented as a real prediction committed months earlier.
5. Resolve FP-D2 before using retrospective replay agreement to grant live autonomy. If approved, specify a frozen walk-forward protocol, untouched holdout, evidence cohort, source quality and live confirmation rule; train/examine without looking at held-out actions. If unapproved, training can use permissible history but live qualifying evidence accrues prospectively.
6. Record whether import-time snapshots bias the observable dataset and measure that effect. Do not treat absence of a footprint as a strong negative label.
7. Default connected observation to a shadow interval such as the proposed seven days only after its policy is approved. The end of seven days does not grant permission. Distinguish data-provider authorization, observation restrictions and computed licence.
8. Show current action-specific qualification: raw strong count, recent count, current bound, eligible exam, hard cap and blocking reason. The 58/148 examples cannot be a universal progress counter.
9. Reconnection/resync does not reset the evidence clock, duplicate history, erase drift alarms or restore stale licences. Source/resource changes invalidate only the appropriate derived state and require fresh checks.

Acceptance: two old snapshots with no event history cannot fabricate a full archive timeline; retrospective/prospective ledgers stay distinct; future mutations cannot change earlier predictions; a backfill-triggered model refresh cannot execute before all current restrictions and approved evidence rules pass.

## 7. Gmail API connector

### 7.1 Scope and implementation files

Proposed files: `packs/mail/connectors/gmail_read.py`, `gmail_write.py`, `gmail_auth.py`, provider parsers and focused tests under `backend/tests/connectors/`. Common pure types use section 5. HTTP goes only through approved pack connector transports; no Gmail calls in engine/API presentation code.

Implement Gmail REST as the full mail execution profile, retaining IMAP as a separately tested observation profile. Read selected messages/threads/Sent and labels; support ARCHIVE, TRASH, REPLY, FORWARD at the catalog caps. Never use immediate permanent-delete endpoints or modify mailbox filters/settings.

Request `gmail.readonly` for read workers. Executor uses reviewed narrow write scopes appropriate to sending/label actions, with grants separated from read roles. Google's [scope reference](https://developers.google.com/workspace/gmail/api/auth/scopes) classifies readonly/modify as restricted and send as sensitive; server-side restricted-data access may require verification/security assessment. Provider enrollment is a release dependency for the chosen distribution profile, not a task with a promised one-day duration.

### 7.2 Exact implementation sequence

1. Register the selected desktop/hosted OAuth profile, exact redirect URLs and separate role grants. Verify account identity via authenticated provider metadata and exclude unapproved aliases/resources.
2. Bootstrap the selected mailbox cohort by paginating message IDs and fetching MIME/headers. Preserve native message/thread IDs and RFC Message-ID/In-Reply-To/References; decode safely with bounded input sizes. Do not fetch attachments or remote images merely to understand a body.
3. Persist a bootstrap watermark, complete paginated observations, then catch up changes across the bootstrap interval. Use a documented overlap/dedup procedure so new mail or label changes during initial import are not missed.
4. Incremental sync consumes typed message/label/deletion history, deduplicates overlapping entries and advances the history cursor only after commit. Stale history ID triggers an explicit resync; it does not mean no changes. Google's [sync guide](https://developers.google.com/workspace/gmail/api/guides/sync) documents history-based partial sync and the out-of-range 404 case. Polling is sufficient for correctness; push watch, if implemented, needs renewal and authenticated notification handling.
5. Distinguish external user footprints from Probation-issued changes using the execution journal and native receipts. Correlate labels/Sent after an action without counting them as new human agreement.
6. Build ARCHIVE by removing only INBOX; snapshot original membership. Build TRASH through the reversible trash operation and preserve the relevant original state. Undo restores only the change Probation made and detects conflicting user edits.
7. Build replies from a validated persisted draft, using the original sender only, correct MIME encoding and native thread/reference identity. Validate From alias, To, empty Bcc/Cc by default, subject/body rules and no attachments. FORWARD remains suggestion-only; resolve FP-D13, use a distinct validated forward payload and explicit typed owner-selected recipient, and never accept a model-invented address. Forwarding does not inherit permission to share files or add attachments.
8. Before autonomous send, enforce hold expiry, current licence/exam, consent revision, catalog/parameter/draft checks and account binding. Explicit approval uses current contract semantics and does not imply a new autonomous licence.
9. Gmail send is non-recallable for this product. Use a deterministic local action/message correlation marker and durable attempt record. If request outcome is ambiguous, reconcile against Sent with bounded evidence; absence alone is not proof of failure. Never resend automatically after an uncertain effect.
10. On OAuth revocation, permission error, repeated quota error or scope mismatch, mark the affected capability unavailable, halt dependent actions and surface reauthorization. Do not fall back to another account or an app password silently.

The [REST method reference](https://developers.google.com/workspace/gmail/api/reference/rest) distinguishes message modification, trash/untrash, sending and permanent deletion. Binding those methods to Probation's catalog, deterministic identities and failure behavior is an application design requirement.

### 7.3 Required acceptance tests

Fake-provider tests: multi-page bootstrap, change during bootstrap, duplicate history records, stale cursor, MIME failure, wrong account, missing scope, Sent reply matching, label undo preserving pre-existing state, revoked token, quota/backoff and refresh races. Runtime isolation tests prove brain/examiner/API cannot read write tokens or invoke mail transport.

Authorized live tests use designated owner-controlled test messages with synthetic content: observe inbound/Sent, approve one reply, perform/undo archive/trash, cancel a held send, and simulate a timeout without duplicate send. Public demo/video uses the synthetic replay unless separately approved; no private mailbox contents are recorded for release evidence.

## 8. Google Calendar API connector

Proposed files: `packs/calendar/connectors/google_read.py`, `google_write.py`, recurrence/identity mapping helpers and connector tests. Reuse the approved Google auth infrastructure with separate calendar grants and resource selection; mail authorization alone does not grant calendar access.

1. Discover selected calendars and actual access role; bind primary/allowed calendar IDs and account identity. Request event-read capability for observers and the narrow supported event-write scope for Executor. Do not request calendar/ACL administration for RSVP or private blocks.
2. Initial sync paginates events and captures a final sync token using a stable query profile. Incremental requests must preserve compatible options; handle tombstones and an invalid sync token with a complete resync. The [Calendar sync guide](https://developers.google.com/workspace/calendar/api/guides/sync) defines full/incremental synchronization; tokens are resource/profile-specific.
3. Preserve event ID, iCalUID, recurring series ID, original occurrence start, timezone, observed version and owner's attendee identity separately. Treat occurrence cancellation, series changes and daylight-saving/all-day dates as distinct tested cases.
4. Observe invitation/RSVP footprints with known-time provenance. A latest event snapshot is not a historical invitation-arrival or attendee-response log. Do not train on future accepted-event conflicts or invent exact response times.
5. Preflight RSVP against the current native event/version and the owner's attendee record. Preserve other attendees, organizers, conference metadata and recurrence semantics. Select an update strategy that changes only the owner's response; partial arrays must not erase others. The [events update reference](https://developers.google.com/workspace/calendar/api/v3/reference/events/update) documents participant response fields and `attendeesOmitted` behavior. Verify the chosen request in fake and live test calendars.
6. Enforce cap 2 for ACCEPT/DECLINE/TENTATIVE, conditional caps, autonomous hold and explicit-approval semantics. A transmitted RSVP is non-recallable in this product even if a later status change is technically possible: another update does not retract information already sent.
7. Implement BLOCK_TIME as a private, owner-calendar event without guests or externally fetched conference data. Use a deterministic provider-valid native ID/action marker. Store the original state and exact created identity for undo; do not delete a user-edited event without conflict checks.
8. Use conditional modifications where supported. Google's [versioning guide](https://developers.google.com/calendar/api/guides/version-resources) documents `If-Match` and 412 responses. A conflict triggers re-read and safe reconsideration, not blind overwrite or automatic reschedule.
9. Define and test outbound update notification behavior. Do not assume a request flag guarantees that no participant received information. UI state reflects actual request/receipt/uncertainty, not a simulated confirmation.
10. Pause/revoke stops new Calendar effects; held actions whose event changed or disappeared fail preflight. Uncertain request results are reconciled through native identity/version, never blindly repeated.

Acceptance: repeated/all-day/DST events, deleted invitation, organizer/user identity, already-responded invite, stale version, conflicts changing during hold, exact owner-only RSVP update, one created private block, safe undo and duplicate-request/restart handling. Execute only against designated synthetic-content test events after authorization.

## 9. Local filesystem connector and live chain execution

Proposed files: `packs/files/connectors/local_read.py`, `local_write.py`, `local_watch.py`; shared action-identity and durable observation helpers. `watchdog` is already declared; verify deployed platform support rather than assuming watcher delivery is complete.

1. Onboarding selects existing watched directories and allowed roots explicitly. Observe filenames/origin metadata only as required; no general file-content crawler. Sensitive/executable/double-extension/RLO files remain hands-off.
2. Bootstrap a bounded directory manifest and reconcile watcher changes against it. Deduplicate event bursts; rescan after overflow/disconnect/restart. Use stable file identity when available plus content/metadata checks; path alone cannot distinguish a replacement file from the original.
3. A file still being written is not eligible for move. Record stable metadata/version and check again at execution. Avoid following symlinks/junctions/reparse points outside approved roots.
4. Observer process gets read-only OS permissions. Executor alone receives filesystem write capability. A DB flag named read_only is insufficient protection.
5. MOVE_TO_FOLDER uses an existing permitted destination, never creates directories, preserves case and cannot escape a root through traversal, drive-relative paths, symlinks or rename races. Collision handling must be explicit and non-overwriting; store the actual resulting path.
6. Persist a move intent before filesystem I/O and reconcile source/destination identity after crash. Cross-volume behavior may not be atomic: either disallow it in the selected capability manifest or implement a tested non-overwriting copy/verify/commit protocol. Never report success because the expected file is absent.
7. Undo checks both endpoints/identity, allowed roots and original-location occupancy again. If the owner changed/moved/replaced the file, require review; do not overwrite it. Preserve exact undo deadline/status.
8. Correlate own moves to execution IDs so the observer does not count them as new human agreements. An owner override remains a correction/drift event.
9. Chain REPLY uses Gmail execution, BLOCK_TIME uses Calendar, CREATE_TASK uses the selected Notion task data source. Each is a separately authorized action; do not create a cross-tool transaction that claims rollback can unsend a reply.
10. Define partial chain outcomes: completed steps remain accurately listed; a later failure cancels or asks for remaining steps. Compensation is offered only for truly reversible completed actions and with current conflict checks.

Acceptance: real synthetic files in temporary controlled roots; duplicate events, overflow, busy file, replaced file, junction/symlink escape, root/permission changes, occupied undo path, cross-volume policy and crash at each move stage. A three-step chain must show separate evidence/permissions/receipts and recover from a middle-step failure without duplicate send.

## 10. Notion, Radar, Reading and tasks

### 10.1 Provider contract

Proposed shared transport: `packs/connectors/notion_read.py` and `notion_write.py`, with pure mappings for `radar`, `reading` and `chains`. One read connection may observe selected data sources; a separate Executor-owned connection grants only the required update/insert capabilities. Start with an internal single-owner integration; a distributed/public OAuth profile is a separately completed authentication profile, not a renamed internal token.

Plan pin: `Notion-Version: 2026-03-11`, subject to a recorded compatibility test before implementation lock. The [2025 data-source guide](https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03) explains database/data-source separation. The [2026 upgrade guide](https://developers.notion.com/guides/get-started/upgrade-guide-2026-03-11) replaces API `archived` with `in_trash`. Keep the product's “archived link” state separate from a Notion page's trash status.

Notion's [capability reference](https://developers.notion.com/reference/capabilities) distinguishes read/update/insert content permissions. Test the actual granted combination and selected resource sharing; a page grant may include children. Do not assume the connection sees only rows named in the UI.

### 10.2 Property mapping and sync

1. Discover and bind both database and data-source IDs. Persist native property IDs/type versions, not only display names that the owner can rename.
2. Validate required schemas before enabling a workflow. Radar needs item/source identity, title, organizer/type, deadline, official URL, verification sources, state and action marker. Reading needs saved URL, collection, state, source identity and action marker. Tasks need title, due time, status and action/source references.
3. Explain missing/mismatched properties; do not create arbitrary pages/properties automatically outside selected capabilities. New data-source/property creation is an explicit owner provisioning task, not a pack action that bypasses the catalog.
4. Paginate data-source queries; persist bounded overlapping update watermarks and deduplicate by page version. Detect removed access, trash, deletions and schema changes; a polling absence alone is not proof of deletion.
5. If webhooks are added, validate/deduplicate notifications and fetch current objects before using them. [Notion webhooks](https://developers.notion.com/reference/webhooks) provide event notifications rather than a full current row; private installations must still work with polling when no public callback is available.
6. Respect actual response rate limits/Retry-After and retry only safe operations. The [request-limit guide](https://developers.notion.com/reference/request-limits) distinguishes throttling and write-retry hazards. Do not assume an uncertain create can be retried because a read request can.

### 10.3 Writes, reconciliation and undo

1. TRACK creates one scoped tracker page or updates an explicitly matched existing item according to the approved product semantics. Record whether the page was created or pre-existing and every changed property's previous value.
2. DISMISS changes the selected item's product state, preserving original state. It must not catch a write failure and return success.
3. FILE_TO_COLLECTION changes only the mapped collection property; ARCHIVE_LINK changes the product state. Resolve labels to typed selected collection choices; reject unknown collection IDs and unexpected property types.
4. CREATE_TASK creates one task bound to its triggering action and data source. Deduplicate/reconcile with a deterministic action marker and a local serialized execution intent; do not assume provider-native idempotency where none is documented.
5. Before update, re-read expected values/version and fail on known conflict. Do not invent ETag/CAS support. Where the provider cannot offer atomic conditional property writes, document the remaining concurrency limit, post-verify results and stop on conflicts; never claim that local SQLite makes remote edits serializable.
6. Undo restores only Probation's changes if the current state still matches the expected post-effect version/values. A created page may be put in trash/restored under the pinned API; never permanently delete or trash a pre-existing owner page merely to undo a property change.
7. Source links/verification fields remain typed and cited. Notion text is untrusted input and passes normal redaction/reader/quarantine rules; it is not a new instruction channel.

### 10.4 Reading is mandatory in the full product

1. Intake accepts an explicitly user-saved URL from the Reading inbox, a supported bookmark export or an approved local intake UI. A URL encountered inside third-party email is not automatically user-saved. Mail-to-self support needs an explicit owner-approved intake event and review against I-24 before fetching.
2. Sanitize secret/private URLs, check domain restrictions, perform guarded Extract and strict quarantined reading, then derive permitted content clues. Entity facts stay restriction-only; saved-item content is the documented separate source of reading clues.
3. Train on known user collection/archive decisions with a bounded named collection set plus OTHER/LEAVE behavior. Unknown collections are suggestions/abstentions, not silently created destinations.
4. Implement collection/archive action parameters, current licence/exam checks, Notion execution, correct source footprints and conflict-safe undo. Do not count automatic filing as strong self-confirmation.
5. Run all Reading-specific exam operators, including injection/URL invariance/domain risk, through the real shared pipeline. Display supported summaries, source URL, collection, state and action/evidence in Library under More.
6. Weekly Radar digest is generated from validated typed fields and citation-checked output; delivery is in the dashboard unless a separately authorized outward notification channel is specified. “Send a digest” does not silently add email sending to another role.

Acceptance: fake Notion provider with renamed property, missing capability, multi-source database, pagination, access removal, duplicate notification, failed/ambiguous create and user edit during undo. Authorized test workspace demonstrates tracker create/dismiss/undo, saved link file/archive/undo and task create/undo using synthetic content. Passing isolated pack tests alone does not close the integration.

## 11. IMAP and private iCal observation profiles

### 11.1 IMAP

Proposed file: `packs/mail/connectors/imap_read.py`; constrained credential gateway, if needed, is implemented in the approved Executor boundary, not in an LLM or unrestricted helper process.

1. Implement TLS with certificate/hostname verification, bounded timeouts and an explicit approved host/port. Never fall back to plaintext or disable certificate checks to make login work.
2. Prefer the supported OAuth profile where available. Gmail documents [XOAUTH2 IMAP/SMTP support](https://developers.google.com/workspace/gmail/imap/imap-smtp). Google [app-password guidance](https://support.google.com/accounts/answer/185833) says availability depends on account/security settings and recommends modern sign-in where supported. An app password is not an assumption about every owner's account.
3. Resolve FP-D6 before observers receive credentials that can write. For a broad credential, an Executor-owned observation gateway can expose only bounded read operations; role/network/credential restrictions and this additional source endpoint require explicit approval. No raw password reaches ingestor/brain/API.
4. Use read-only mailbox selection and non-mutating fetches; do not mark messages seen. Reject STORE/APPEND/COPY/MOVE/EXPUNGE and arbitrary protocol commands on the read capability.
5. Persist account, mailbox, UIDVALIDITY and UID-based cursor; handle resets, missing UIDs, reconnect and optional MODSEQ support explicitly. Deduplicate across folders/native message references; never rely on unstable sequence numbers.
6. Preserve MIME, labels/flags, Message-ID/References and Sent mapping. A final folder snapshot cannot recreate missing historical moves; source evidence strength follows section 6.
7. This profile observes. Gmail REST is the defined write implementation for a Gmail account, after verifying that both profiles bind the same account/native items. A generic non-Gmail SMTP send connector is not claimed by this profile and is not silently introduced.

Acceptance: protocol fake-server tests enforce no mutating command, wrong certificate, reconnect, UIDVALIDITY change, duplicated folders, message arrival/deletion, missing Sent and scope denial. Confirm the implementation against the pinned supported Python/library version; do not rely on defaults for TLS verification.

### 11.2 Private iCal

Proposed file: `packs/calendar/connectors/ical_feed.py`.

1. A private feed URL is a credential. Configure it outside prompts/logs; persist only a protected credential reference. Never send it to Tavily, a writer, the browser API or generic URL previews.
2. Fetch only an explicitly approved HTTPS source, with controlled DNS/redirect behavior, size/time limits and source credentials. A pasted arbitrary URL must not turn the service into an SSRF proxy.
3. Use ETag/Last-Modified when the provider supplies them; otherwise compare bounded content hashes. Parse recurrence/cancellation/timezone data with limits and reject malformed/unbounded calendars.
4. Key observations by calendar source, UID and recurrence identity. Compare snapshots with a recorded observation horizon; treat missing events and response history conservatively. A feed may omit RSVP or arrival data and can be delayed.
5. Report capability as observe-only. RSVP and BLOCK_TIME require the Google Calendar write profile or a separately completed supported write connector. Map duplicates across API/feed views without generating two situations/evidence counts.
6. Revoke/pause prevents further fetches; reconnect does not re-label old snapshots as new decisions.

Acceptance: secret URL absent from logs/LLM/citations, cache-hit/changed feed, malformed/large recurrence, stale/deleted event, timezone, redirects/private-host denial, duplicate API/feed identity and no exposed write action for the feed.

## 12. MCP client and Probation MCP server

### 12.1 Explicit compatibility contract

Proposed pure mappings: `connectors/mcp_manifest.py`; transport adapters: `packs/connectors/mcp_read.py` and `mcp_write.py`; server: `integrations/mcp_server.py` with authenticated command forwarding, never direct unrestricted DB/credential access.

Protocol plan pin: MCP `2025-11-25`, negotiated against a recorded supported SDK/server/runtime version before lock. Implement stdio and supported Streamable HTTP profiles with explicit local-process/remote-server approval. No automatic `npx` installation or execution of server commands supplied by a document/tool result.

The official [tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) defines schemas/discovery and treats tool annotations as untrusted unless sourced from trusted servers. The [security guide](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices) covers authorization/SSRF/session/token risks. A discovered tool called read_file is not proof that it is read-only.

### 12.2 Client implementation

1. Provision a server profile with origin/command, version/hash, authentication mode, resource selection, supported protocol, schema digest and approved tool mapping. Bind it to a named pack and owner.
2. Discover all paginated tools/resources, validate schemas and compare against the manifest. Changed/unknown tools remain disabled pending mapping review; no free-form LLM selection or tool-name-only permission.
3. Map known tool outputs to SourceObservation and pack facts using strict validators, size/time/resource bounds, provenance and known times. Server instructions/prompts are untrusted data and cannot change caps or credentials.
4. Separate read and write clients/capabilities. A mixed server with broad write credentials cannot be presented as an isolated read service without an enforceable approved boundary.
5. Executor alone initiates mapped write operations with a validated action ID, exact resource/parameters, native preconditions, fresh authority and reconciliation rules. A remote server that itself holds write credentials requires the FP-D6 trust-boundary decision; hiding it behind MCP does not satisfy I-2 automatically.
6. Disable unnecessary sampling/elicitation/prompt capabilities. Never let an MCP server request arbitrary credentials or broaden access as a tool response. Handle cancellation, timeout, output truncation, schema change, invalid sessions and reconnect without duplicate effects.
7. Reject bearer-token passthrough to another audience/origin, redirect-driven credential leakage, session IDs used as owner identity, cross-server confused-deputy behavior and private-network target substitution.
8. Produce a tested manifest for each claimed provider/server integration. Generic transport success alone is not a “works with any MCP server” product claim.

### 12.3 Server implementation

Implement exactly scoped `check_permission`, `propose` and `explain` contracts:

- `check_permission` accepts a known resource/class/action/parameter binding and returns a typed current result with cutoff/version/expiry and reasons. It is advice until Executor's final check.
- `propose` accepts validated caller intent through the approved command path; brain constructs the immutable proposal. Caller-supplied confidence/licence/cap cannot be authoritative.
- `explain` returns bounded, owner-authorized evidence and safe citations for that proposal/task; no unredacted history or secrets by default.

If an execution tool is later exposed, it must be an authenticated submission to Executor and maintain the same journal/approval/cap behavior. It cannot mean “external agent received a true boolean and may now use arbitrary Gmail tools.” Authentication/resource binding, rate limits, auditability and signed-receipt checks apply identically to HTTP and MCP.

Acceptance: fake schema-mutating/hostile servers; missing tools, changed annotations, wrong token audience, malicious redirect, revoked scope, timeout after write, duplicate tool calls, session restart, unexpected large output and invalid typed fields. Real interoperability requires a pinned working server/runtime profile with synthetic resources and proof that alternate write tools cannot bypass Probation.

## 13. Always-on supervisor and operational control

Proposed files: `workers/runtime.py`, role entry points, lease/checkpoint repositories, health/status models, `probation run` CLI and deployment service profiles. This is a durable application runtime, not an LLM given all credentials.

1. Run role workers with separate credentials, network policies and database capabilities. Scheduler owns timing/orchestration; any data writes execute through the authorized role function. Do not add a scheduler superuser because it is convenient.
2. Maintain per-source bootstrap/change queues, proposal processing, response consumption, correction/alarm work, due action/undo queues and nightly review/retrain jobs. Use durable checkpoints and fencing so two processes cannot consume the same effect unsafely.
3. Trigger event order from actual known times. Before an autonomous effect, consume relevant prior responses/corrections/restrictions and derive current authority. New evidence arriving between preflight and network dispatch remains a bounded external race, handled through explicit status/reconciliation; do not claim an atomic cross-service transaction.
4. Polling target is configurable (initial design target 60 seconds when idle), with rate-aware scheduling/backoff. Holds need their own due-time scheduler; daily ticks must not delay a ten-minute action until tomorrow. All dates/deadlines use Clock and durable UTC state.
5. Backpressure limits work, model concurrency, provider concurrency, memory and queued payload size. Partial provider failure degrades the affected capabilities visibly; LLM/budget/validation failure never permits execute. Tavily failure returns to baseline as I-25 specifies.
6. Nightly jobs run once per scheduled interval with recoverable IDs; restart does not retrain/exam infinitely or reset quotas. Policy snapshots are committed before readers consume them.
7. Shutdown stops new claims, persists safe in-flight state and leaves ambiguous effects for reconciliation. Restart handles overdue holds, expired authority, missed observations and stale leases without blind replay.
8. Pause controls exist globally and by connection/pack/action. A completed network dispatch cannot always be cancelled; the UI distinguishes request-to-pause, confirmed stopped, already dispatched and confirmed effect. “Paused” must mean the relevant safety barrier is active.
9. Show last successful observation, cursor/horizon lag, worker heartbeat, pending/failed/ambiguous counts, model budget and provider capability state. API liveness alone is not “AI systems online.”
10. Set and test operating targets: synthetic functional poll within two configured ticks under normal load; due action processing within one configured scheduler tick; no execution after an acknowledged restriction revision; a 72-hour synthetic soak with forced restarts, duplicate jobs and provider failures. These are proposed acceptance targets, not current measured performance or availability guarantees.

Required runbook: start/status/pause/resume/shutdown, reauthorize, reconcile ambiguity, recover cursor, rotate secrets, restore backup, migrate schema, inspect failed quarantine, verify ledger, enforce budget kill-switch and retain synthetic public service through judging. Commands must be implemented/documented before screenshots use them as real controls.

## 14. Nemotron tiers, cascade, writer metrics, guard and targeted red team

All inference remains NVIDIA Nemotron through Nebius Token Factory under locked D-04/D-05. Provider catalog entries, usable account model IDs, prices, reasoning mode, schema support and quota are separate verification items. A public model announcement is not proof of this account's access.

### 14.1 Exact sequence

1. Create a provider-capability record through an approved operator smoke: exact endpoint/model ID, final-content behavior, schema/fallback mode, max output, timeouts/rate headers, usage and price source/date. Never print credentials or reasoning traces.
2. Complete every prompt job in PROMPTS.md and active callers; record a prompt manifest with immutable version/hash, strict model/schema and model role. Missing writer/digest/exam/synthesis/extractor jobs block their features.
3. Build a held-out synthetic reader-form corpus with canonical field labels independent of the engine. Account for generator vocabulary differences such as chat/social and unsupported intents; do not silently score one label vocabulary as another.
4. Evaluate Nano/Super/Ultra on the same redacted forms; report per-field accuracy, unsafe false negatives, uncertainty flags, schema failure, latency p50/p95 and cost per 1,000 with sample counts. Frozen test examples must not be used to tune the selected prompt/cascade.
5. Implement Nano first and deterministic escalation to Super on documented typed conflicts/validation failure/uncertainty, with a strict budget. A free-form confidence word is not a reliable escalation signal. If a required escalated read is unavailable or conflicts persist, ASK. Cache the complete cascade/prompt/model provenance.
6. Re-run policy/calibration/exams on the selected reader feature version; a cascade change can change class assignment and cannot inherit an old exam as if nothing changed. Define version applicability explicitly in the approved evidence/exam contract.
7. Ultra red-team generation receives only permitted, redacted, as-of policy context and targeted feature names. Generated edits remain untrusted; code validates perturbations and computes every verdict. No model-written “pass” can enter the licence predicate.
8. Investigate a supported Nebius-hosted NVIDIA guard model using the actual catalog. If available and approved, implement a schema-validating restriction-only detector; it cannot raise cap/probability/evidence or override a failing reader. Measure false positives/false negatives on synthetic injection controls. If unavailable, record a provider blocker/decision; never substitute a different endpoint or claim the guard is implemented.
9. Permission/habit explanations use typed evidence and correct coefficient alignment; validate counts, units, task/action, polarity and source scope. Number equality alone does not prove faithful wording. Keep a deterministic explanation when wording is unavailable.
10. Writer evaluation reports greeting/sign-off, length/formality and unsupported number/date/commitment checks plus a blinded synthetic-example review if authorized. Name these as style/provenance metrics; they are not proof of human voice fidelity or factual correctness.

### 14.2 Required evidence

Artifacts: versioned prompt registry, cached synthetic form dataset, model capability smoke, tier comparison, cascade operating-point study, targeted-edit validity/coverage table, guard availability/integration record and writer-style report. No stage closes with zero calls represented as a successful benchmark. Model/guard unavailability is a stated dependency, not a reason to invent metrics or broaden providers.

## 15. Complete user journeys, APIs and product views

The original five primary destinations remain Home, Queue, Actions, Permissions and More. Add complete secondary destinations for Connections, Radar, Reading Library, Skills, Learned About You, Insights/Exams, Privacy & Web, Activity Record and read-only effective Settings. All enabled destinations require real API readiness and empty/loading/error/pending states.

### 15.1 First run through earned action

1. Choose synthetic replay or private owner installation. Explain footprint scope and what can leave the device before connection.
2. Connect a service through the actual selected authorization flow; show approved account/resources, read/write capability split, retention, last sync and revoke controls. A successful auth flow with failed tool/resource discovery is “authorized, capability unavailable,” not fully connected.
3. Select backfill range and resource exclusions; show source-quality/horizon limits and model-processing estimate. Show progress/resume/cancel without duplicating imported items.
4. Observe in Watch/Shadow, inspect task-specific historical suggestions and accept/reject/edit actual items. “What I would have done” is clearly hypothetical; no retrospective ledger is described as a live commitment.
5. Inspect exact evidence, posterior bound, valid exam, restrictions and readiness for a particular action. There is no “approve level 2” button or global accuracy/trust grade.
6. Enable execution restrictions only when the owner chooses. The derived licence may still be zero. The first earned reversible action has a visible action record and undo; the first earned non-recallable operation has the prescribed hold and cancel.
7. After an override/drift alarm, display demotion/retest state and explain why a held item stopped. Later a valid exam and fresh evidence can restore eligible authority; no manual edit to a licence row does so.

### 15.2 API additions requiring approval

Retain all routes in Core WP9. Propose typed extensions, with D/FP decisions before coding:

| Surface | Request/result contract to specify | Write/transport owner |
|---|---|---|
| Connections list/detail | Redacted provider/account/resource bindings, capability states, last-sync/horizon/lag, restrictions; no tokens/private URL | API read only |
| Connection authorization start/complete | Opaque flow/request IDs, owner/scope binding, failure/cancel states; write code/token stays in execution auth boundary | Approved role-specific auth handler |
| Connection commands | Backfill, pause, resume, disconnect, revoke, purge; idempotency/restriction revision and accepted/pending/result status | API command request; designated role consumer |
| Library/Radar intake | Explicit user-saved URL provenance and selected collection/workflow | Approved ingestion command path |
| Saved-item board/detail | Actual sources, supported fields, library/tracker state, action/permission link | API read only |
| Habit correction | Description/note/deny or typed prospective feedback, not arbitrary evidence/rule mutation | API command; examiner/resolver according to kind |
| Skills | Six-question manifest, available provider/actions, capabilities and evidence status | API read only |
| Sender check | Public registrable domain only, bounded typed query request and result/citations | API command; webfacts calls Tavily |
| Task-scoped report | Class/action/time cutoff, strong/censored/abstention denominators | Approved additive report contract |
| Runtime/admin command | Safe pause/status/reconcile/exam/review controls and admin authentication | API request; owner role consumes |
| Permission receipt/revocation | Exact requested resource/action binding, receipt ID/key ID, accepted/result state | Signing owner, API never gets private key |

Do not implement these as undeclared free-form POST bodies or direct API database writes. Publish OpenAPI/strict response models and validate the browser client against real pipeline-produced responses, including incompatible-version/error cases.

Concrete proposed routes to review: `GET /api/connections`, `GET /api/connections/{id}`, `POST /api/connections/{kind}`, `POST /api/connections/{id}/sync`, `POST /api/connections/{id}/pause`, `POST /api/connections/{id}/resume`, and `DELETE /api/connections/{id}`. DELETE records an idempotent disconnect command and returns accepted/result state; it does not delete the ledger. Add separately reviewed typed intake, habit-correction, runtime-command and receipt request/result routes. Exact schemas, authorization and role consumers must be committed to the API specification before handlers are written.

Required existing-route additions, after contract review:

- Queue, Actions and Exams have bounded `limit` and opaque stable pagination cursor; define deterministic ordering with an ID tie-break, filter binding and behavior when data changes between pages.
- Time-sensitive reads accept the approved `as_of`/period filters and apply them consistently to proposals, outcomes, licence/exam views, boards, metrics and exposure. Precomputed replay cursor playback is explicitly distinguished from recomputing/dispatching a replay; the controls must operate the selected real service and must not duplicate actions.
- Queue presentation includes a bounded redacted subject, sender display, deterministic action label, pack-approved `allowed_actions`, supported risk/cap reasons and an actual validated draft. Display names are redacted where required; risk labels are derived from declared flags, never fabricated from a fixture-only field.
- Item detail includes actual top contributions and three eligible similar historical cases, with known-time cutoff and evidence/provenance. Missing examples are unavailable rather than copied from the future.
- Licences exclude ABSTAIN/no-op rows from permission presentation and provide current cap/reason, eligible exam date/level and alarm state via the canonical derivation. Existing task rows do not replace the need for an approved task-scoped query contract.
- Respond carries approved `edited_action`/`edited_body` semantics with pack validation and idempotent accepted/result state. FORWARD additionally needs the explicit recipient contract; no arbitrary action such as SNOOZE is silently accepted.
- Actions return `undo_until`, actual `can_undo`/`can_cancel`, readable target and hold deadline, reflecting worker status and the shared clock. Browser countdowns are presentation only; the worker enforces the deadline.
- Settings include effective caps, losses, hands-off rules and tunable units; Exposure includes approved per-item counts and zero-call/cache proportions, without raw prompt text. Remove undocumented blended trust/accuracy headlines.
- Exam run requests require explicit valid scope and admin authority; missing classes never select a different class silently. HTTP, validation and safe internal errors use the same envelope.

### 15.3 Specific missing product features

- **Skills:** show each pack's six questions, supported actions, cap/recall rules, configured providers, current observation/execution consent and operational readiness. Enabling a skill cannot create evidence or expand hard-coded catalog rules.
- **Learned About You:** list actual bounded habits with counts/examples/as-of; edit labels/notes or submit a correction/deny. Editing wording does not edit historical outcomes or instruct the policy to grant autonomy. New preferences/feedback require typed provenance and future evidence rules.
- **Library:** real saved-link collections, archive, source-supported summary/topic, permitted action and undo/history; route belongs under More, with responsive empty/error states.
- **Privacy & Web:** exact public queries, sources, cache origin, TTL/history, credits and LLM exposure are distinct views. Opening transparency does not call a provider. Raw prompts/private URLs are not shown.
- **Sender checker:** domain normalization, rejected private/non-domain input, quota isolation, timeout/not_checked state and cited uncertain result. No arbitrary search/URL fetch proxy; the live path requires FP-D9.
- **Actions:** accurate pending/held/dispatched/done/ambiguous/failed/cancelled/undone states as approved; show when cancel/undo is actually available. Never show Undo after an irreversible send as if it retracts the message.

All views need keyboard-accessible navigation/dialogs, focus management, responsive layouts, reduced-motion behavior and safe HTTP(S) source links. Use actual health/mode/time; no static online badge or silent preview fallback. Accept/Edit must refresh dependent views, preserve failed/pending states and send the real approved edited body/action.

Acceptance: a browser session performs connect→backfill→shadow feedback→earned action→cancel/undo→drift/demotion→disconnect, plus Reading/Radar/task journeys, using synthetic provider data. Inspect mobile/desktop and keyboard behavior. Build/typecheck alone does not close this requirement.

## 16. Complete evaluation, Personas-India and actual human study

### 16.1 Full evaluation scope

Complete every E1-E13 experiment in EVALUATION_PLAN, with E8/E13 now retained for the full product, all seven listed E3 ablations, B0/B1/B2/B3 with the documented threshold sweep, drift/chain/exam/efficiency/privacy analyses, per-pack results and figures. E9 measures actual implementation effort rather than inventing hours retrospectively.

1. Use an explicit 15 development / 5 held-out persona main split and frozen seeds. B3's documented two-persona budget scope is reported as that cohort, not falsely expanded to 20. The development pilot is a staging gate only.
2. Run real conditions from fresh isolated state with the same event chronology, source cohort and cached redacted features. Invariant-violating ablations remain confined to the synthetic harness and cannot be activated in private/live execution.
3. Publish attention at matched attainable error, correct non-no-op coverage, agreement with/without abstentions, calibration, current/expired permission rates, correction and failure counts, promotion timing, drift delay/false alarms and model/Tavily actual spend. Every rate includes its denominator and unavailable case.
4. Compute majority behavior from eligible past observations for each family; do not assert a universal 90%. A 45-day promotion goal, lower interruption target and 100% cheating-policy catch target may fail. Record the attained value and uncertainty.
5. Extend the planted synthetic world to include correct rendered file moves, opportunity and reading items, all chain actions, injection fixtures and true drift. Distinguish primary items, generated Sent/calendar observations and derived variants so truth joins reconcile.
6. Test every planned provider with deterministic synthetic fixture/fake-server scenarios and separately authorized live test resources. A live provider smoke proves only its exercised capability, not all provider API behavior.
7. Aggregate bootstrap uncertainty by persona, record actual runtime/model/prompt/config/input hashes and preserve exact reproducible commands. Publish source-supported catalog labels and measured negative results.

### 16.2 Nemotron-Personas-India ingestion

The [NVIDIA dataset card](https://huggingface.co/datasets/nvidia/Nemotron-Personas-India) identifies a synthetic persona dataset and attribution licence. The local `synth/personas.py` currently creates its own personas; that is not evidence that this dataset is used.

1. Approve a pinned dataset revision/download mechanism, licence/attribution handling and network destination. Do not import/download the entire dataset at application startup.
2. Create an offline preparation step that selects a seeded, bounded cohort, records source row/revision/hash and converts only the needed attributes into the existing Persona schema. Keep demographic context out of authority/cap rules.
3. Generate fictitious local contacts/addresses/resource identities as necessary; do not mistake persona narratives for real account exports. Run schema/bias/duplicate/content review and label all derived examples synthetic.
4. Distinguish local template and NVIDIA-source personas in run manifests; fallback templates support offline tests but cannot satisfy a README claim that source integration was used.
5. Generate bodies through the actual versioned Nemotron synthesis jobs, cache and record provenance, then render source formats and hidden truth through the same engine-facing import path.
6. Keep training/evidence blind to the answer key and source-only hidden habit labels. Test identical seed/revision output and source attribution in aggregates/README.

Acceptance: a reproducible bounded preparation artifact, dataset licence/source manifest, generated fixture with aligned truth, correct API/LLM exposure provenance and a full run actually using the selected NVIDIA-source cohort.

### 16.3 Real human study

`eval/human_study.py` contains simulations; preserve them as tests with explicit simulation labels. They are not evidence of participation by real people.

1. Resolve FP-D12 and prepare a consented study protocol: synthetic stimuli only, anonymous participant code, no account login/export, no screen recording or secret collection, withdrawal/retention process and aggregate reporting. Separate contact/consent administration from decision data under an authorized operator.
2. Implement a study harness for the documented 150 synthetic items and 6-10 participants, preserving stimulus/randomization version and task/action vocabulary. Verify the interface/exports with simulated participants first.
3. Freeze the analysis before collection: per-participant chronological learning curves, uncertainty, disagreement rates and whether evidence supports level 1 or more. Do not expect 150 decisions spread across classes to guarantee level 2.
4. For E13, assign the defined synthetic unknown-sender items to evidence/no-evidence conditions with controlled ordering; measure decision quality with the documented reference labels and report limitations.
5. An authorized human conducts recruitment/consent and collection. Agent review can use approved anonymous aggregates; no one invents participants, replaces difficult choices or treats generated labels as human results.
6. Report actual n, exclusions, incomplete responses and negative findings. If recruitment/authorization is incomplete, F39 remains incomplete. It is not quietly cut to satisfy a date.

## 17. OpenShell, Hermes, NemoClaw and Nebius parallel/batch execution

### 17.1 OpenShell

Deliver a version-pinned Linux deployment profile with filesystem/process/network policy, per-role allowed destinations and denied probes. Public synthetic hosting is separate from private Windows/local-file access; document/test Windows local workers or a supported local Linux/WSL deployment explicitly. Do not claim Linux Landlock enforcement exists natively in a Windows process.

The [OpenShell policy documentation](https://docs.nvidia.com/openshell/latest/sandboxes/policies) distinguishes startup filesystem/process rules and network controls. Translate the approved architecture into a reviewed effective policy; configuration text alone is not proof of enforcement.

1. Provision supported kernel/runtime and verify actual enforcement, filesystem mounts and secret visibility at startup. Fail closed if the selected required security control cannot be enforced.
2. Brain/examiner reach only approved inference; webfacts reaches approved Tavily/inference; read connectors reach selected providers; Executor reaches selected target apps. A global “only Nebius and Tavily” policy would break live connectors and misrepresent the system.
3. Keep inference clients data-only and write credentials outside reader/writer/exam sandboxes. Audit provider-added effective rules and direct-network bypass, not only the base YAML.
4. Test an allowed request, blocked unlisted destination, blocked unauthorized filesystem write and denied credential read. Confirm proxies/managed inference route to approved Nebius models without fallback to another provider.
5. Record kernel/runtime/version/policy digest and effective policy in synthetic release evidence; no secret-bearing config is committed.

### 17.2 Hermes and NemoClaw

Both named integration profiles are retained in the full register. The [Hermes MCP guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) documents local/remote MCP connectivity and per-server filtering. The [NemoClaw overview](https://docs.nvidia.com/nemoclaw/latest/about/overview.html) describes sandboxed runtime/provider routing. Those capabilities do not prove compatibility with the selected installed versions or Probation's strict authority model.

For each profile:

1. Pin official runtime/SDK/config format and reproduce setup in a disposable synthetic environment. Record exact supported version rather than copying an untested command from a blog.
2. Configure only the approved Nebius/Nemotron inference provider. Explicitly disable provider fallbacks and direct target-app write tools; approved external-runtime boundary FP-D7 must be resolved.
3. Connect to Probation's authenticated MCP service; present schema-validated intent, check permission and explain evidence. Unknown actions/tools/resources cannot be dynamically approved by a model.
4. Route any permitted effect through Executor. Prove the external runtime lacks an alternate Gmail/Calendar/Notion/filesystem write capability that bypasses it. A voluntarily consulted permission API is not an enforcement layer if bypass remains possible.
5. Test restart, stale receipt, scope revocation, malicious server instructions, unavailable model/Probation and attempted direct write. Record allowed/blocked traces with synthetic content.
6. Do not introduce a second autonomous “brain” that can grant its own licences. Persistent runtime memory is input data subject to redaction/validation and bounded evidence, not an authority store.

If a runtime cannot expose a compatible constrained profile, its F row stays blocked pending an approved solution. Do not advertise the runtime integration merely because it can launch.

### 17.3 Nebius serverless/parallel evaluation

Deliver real serverless inference usage and a reproducible parallel evaluation runner. The [official batches reference](https://docs.tokenfactory.nebius.com/api-reference/examples/batches) documents asynchronous batch operations; the [Data Lab batch guide](https://docs.tokenfactory.nebius.com/data-lab/batch-inference) describes a separate dataset/operation flow. Select and pin one supported interface; do not mix their identifiers/status paths or invent a generic compute-job API.

1. Confirm chosen Nemotron models, schema/request support, account quota, cost and retention on the chosen interface before a run. Use synthetic redacted inputs only for this delivery profile.
2. Keep all inference HTTP in the approved `llm/client.py` boundary; payload/run helpers may be separate pure modules. New batch/upload endpoints and persistent datasets need reviewed accounting/privacy handling.
3. Reserve worst-case approved spend for outstanding work, exclude validated cache hits, bind each request to stable custom ID/model/prompt/input hash and submit bounded jobs. Retries/cancellation can still incur charges; reconcile actual usage.
4. Parallelize personas and content-only reader jobs where independent. Preserve chronological training/evidence/review/action order within each persona and per-situation historical prompt context. Never precompute future style examples or train on unfinished future results.
5. Persist job/output/error state and resume safely. Validate each response with the same strict schema/cache rules; out-of-order or partial outputs do not become guessed features.
6. Publish job IDs/status counts, actual tokens/cost, latency/throughput and equivalence against the sequential controlled run. A queued or failed job is not measured acceleration.

## 18. Portable signed permission receipts

Proposed files: pure receipt models/canonicalization under `core/`, signing/verification adapters under the approved execution/integration boundary, public verification key manifest and focused security tests. A maintained cryptography implementation/version and a signing credential require explicit approval; do not design new cryptography.

Recommended design decision: Ed25519 detached signature over canonical, versioned JSON with bounded scalar representations and no private content. Use the project's canonicalization contract carefully; reject non-finite/ambiguous values. Approve the precise wire format before implementation rather than making incompatible clients guess it.

Required signed fields: receipt version/ID, issuer/key ID, owner-installation pseudonymous binding, caller audience, provider/connection/resource, exact class/action, canonical parameter hash, policy/feature/evidence snapshot, ledger head/run ID, issue/not-before/expiry, consent/restriction revision, nonce and whether the receipt is explanatory or a one-shot execution request.

Implementation:

1. Generate/store/rotate signing keys only in the approved execution credential boundary; publish the verification key and key ID through a trusted channel. Never commit a private signing key.
2. Signature verification rejects altered fields, wrong audience/connection/parameters, expired/not-yet-valid receipts, unknown/revoked keys and unsupported versions. A hash chain alone is not a signature.
3. Offline verification establishes authenticity of the signed snapshot only. Before an effect, Executor rechecks current licence, exam, consent, caps, parameters and revocation; a previously signed level is not stored truth.
4. Consume one-shot execution nonce/action binding idempotently. Repeated delivery returns the existing result, never a second effect. Explanatory receipts may be read multiple times without becoming execution rights.
5. Revocation/disconnect/drift invalidates current execution eligibility and is recorded without rewriting old receipts/ledger entries. Re-key/restore behavior prevents a restored stale database from resending consumed actions.
6. Export only the minimum evidence summary necessary. A receipt must not leak mail bodies, filenames, private URLs or full source history through a “portable memory” feature.

Acceptance: positive cross-client verification and tamper, stale level, wrong resource, parameter substitution, audience mismatch, replay, rotation, offline-stale-revocation and restore tests. Do not claim the signature proves a prediction is correct or makes an arbitrary external agent safe.

## 19. Deployment, platform support and operations

### 19.1 Explicit delivery profiles

| Profile | Data and effects | Required verification |
|---|---|---|
| Development/test | Synthetic only, mocked providers/offline models unless explicitly authorized smoke | Reproducible environment, no accidental network/secret read, unchanged tracked outputs |
| Private single-owner Linux | Own selected accounts/files, role-separated credentials, approved live processing | OAuth/secret store, connector conformance, OpenShell, backup/upgrade/pause and local privacy tests |
| Private Windows owner installation | Windows filesystem observer/executor boundary plus an explicitly supported worker/sandbox arrangement | Native path/junction/ACL/watcher tests, installer/service lifecycle, approved local Linux/WSL dependency if used |
| Public demo | Synthetic replay and simulated effects only; approved isolated live public-domain lookup if selected | Fresh browser/mobile, per-session synthetic state, quota isolation, no private accounts/tokens/resources |

Do not add multi-user personal account hosting. If a cloud VM serves the private owner dashboard, decide whether private data remains on the owner's machine or that authorized private VM and document it precisely; the current local-data policy cannot be silently replaced by cloud sync.

### 19.2 Packaging and operations tasks

1. Lock Python/Node dependencies and package prompts, schema/migrations, offline embedding artifacts and public fixtures. Runtime setup must not download unknown programs or expose private exports.
2. Provide documented install/start/status/upgrade/uninstall behavior for each claimed platform. Uninstall preserves or purges private content only by the approved operator choice and never rewrites an append-only ledger.
3. Deploy the chosen Nebius AI Cloud/reverse proxy profile with HTTPS, owner/admin authentication, tight CORS, size/time/rate limits and non-secret structured errors. Provision cloud accounts/resources only after approval; no guessed preset/region/pricing.
4. Synthetic visitors get isolated demo copies/reset behavior without access to the owner's DB or write connectors. A demo reset cannot duplicate live charges indefinitely; independent public lookup quotas persist appropriately.
5. Enforce worker resource limits, dependency/security checks and safe default-disabled execution during migrations/config failures. Publish operator health instead of “online” based only on `/health`.
6. Backup private DB/world/cursors/approved secret references consistently; encrypt and restrict backups. Test restore without duplicating remote effects and prove ledger verification before/after.
7. Document retention/export/disconnect/purge with explicit field classes, deadlines and limitations. Do not claim all provider-held data or remote sent copies can be purged by Probation.
8. Run the 72-hour synthetic soak, crash/failure drills and a controlled private synthetic-content provider pilot; record actual availability/resource use and unresolved incidents.
9. Budget deployment through the judging end, including compute/storage/domain/certificate/LLM/Tavily costs. Free credit opportunities are not an actual balance. Keep the full product completion date separate from a hackathon deadline.
10. Produce support/troubleshooting docs for wrong scope, cursor expiry, Notion schema change, feed privacy, file conflict, missing model, budget exhaustion, signature expiry and ambiguous sends. No support procedure asks the user to paste a token into chat.

## 20. Claim control, completion evidence and sequencing

### 20.1 README/video claim register

Every claim must have a row with exact wording, scope (synthetic/private live), feature ID, test/run artifact, version/date, limitations and approval/review status. Required reviewed wording includes own footprints, per-task evidence, known caps, pre-send cancellation versus post-effect undo, entity-web restriction asymmetry and measured negative results.

Do not claim “every action is undoable,” “always holds even after explicit approval,” “58 decisions guarantees permission,” “learns how you work in general,” “100% cheating detection,” “90% baseline,” “works with any MCP server,” “legally compliant,” “zero retention,” or “all features complete” without the appropriate precise qualification/evidence. The [opinion review](PRODUCT_OPINION_REVIEW.md) provides the correction for each supplied assertion.

Complete architecture/setup/licence/model/Tavily/results sections, screenshots from synthetic resources, reproducible CLI commands, written provider feedback, permitted media and the short working video. Prepare a testing-access and maintenance runbook before submission. Publishing/deployment/submission itself requires the appropriate later authorization.

### 20.2 Full delivery order

1. **Design closure:** approve the recorded conflict resolutions, complete source/opinion mapping, provider distribution scope, credential boundaries and test plan. The 22 October D1-D9 amendment was expressly delegated; future amendments still require explicit human approval.
2. **Foundation repair:** Core WP0-WP5 in reviewed original-phase slices; correct data/strict schemas/transactions before spending on real inference.
3. **Closed synthetic loop:** Core WP6-WP9, all six packs and all three chain actions; real pipeline API/browser tests and no-peeking proof cases.
4. **Connector foundation:** common envelopes, per-role storage/credentials, OAuth/consent UI and fake-provider conformance tests.
5. **Complete native connectors:** Gmail, Calendar, filesystem and Notion read/write profiles; explicit IMAP/iCal observation; no private-account testing before scope authorization.
6. **Always-on operation:** supervisor/leases/cursors, reconciliation, pause/revoke, backup/restart and shadow/backfill provenance rules.
7. **Interoperability/security:** MCP client/server, signed receipts, OpenShell and both external runtime profiles with no-bypass proof.
8. **Model/data extensions:** real prompt jobs, tier comparison/cascade, Ultra/guard resolution, Personas-India ingestion and Nebius parallel/batch evaluation.
9. **Full evaluation/study:** every planned experiment/ablation, held-out reporting, actual consented study and complete claim register.
10. **Release acceptance:** all F rows, all original V cases and connector test families green; selected platform/private pilot/public demo proofs, operational runbooks and reviewed phase handoffs.

The order expresses dependencies, not a promise of elapsed days. Create a task estimate after each approved interface spike and record actual time. The earlier eight-day schedule cannot guarantee this expanded scope. If a provider approval, recruitment, model availability or unresolved contract blocks completion, retain its open requirement and publish only a labelled partial milestone.

### 20.3 Evidence required to close a capability

Each F row must link an immutable evidence record with: implementation commit, governing decision IDs, exact supported provider/version/platform/resource scope, tests and commands, fixture/run hashes, positive/negative/failure/restart results, relevant measured counts/cost, documentation/operator instructions and reviewer conclusion. “Planned,” “directory exists,” “fake test passed,” “live login succeeded” and “dependency installed” are distinct states and none alone means delivered.

Close full-product completion only when all 42 records satisfy their defined contracts, no source/opinion requirement is unassigned, no P0 remains, no governing approval is unresolved, required checks pass, and the complete workflows have been demonstrated. A target experiment can be completed with a negative result; an unavailable or unimplemented connector cannot.
