# Approved contract amendment — 22 October 2026

Authority: decision/provenance register beneath `CONTRACT.md`. The owner explicitly
allowed this contract edit, requested recommendations first, then replied “i approve”
to the D1-D9 recommendations. This is a scoped exception to the agent-edit prohibition.
No code implementation, deployment or personal-account access is established by this record.

## 1. Approved decisions and implementation boundaries

| Gate | Approved direction | Contract location | Remaining implementation/evidence |
|---|---|---|---|
| D1 / CCR-A | API records immutable intent and returns 202; Resolver records normal explicit feedback; Executor performs effects; Examiner owns drift. Decision evidence and execution results are separate. | Sections 3, 8, 9; I-12 | Durable per-consumer receipts, response status route, concurrency/restart and first-decision-wins tests; never infer a chosen alternative from rejection. |
| D2 / CCR-B | Append-only outcome events and an as-of projection preserve footprints, feedback, later corrections and undo. Resolver appends normal/override events; Executor appends its undo/cancel corrections. | Sections 3, 4, 8; I-6-I-8, I-12 | Reviewed additive DDL/migration, immutable events, one eligible evidence vote per proposal, historical replay and rollback proof; original ledger bytes unchanged. |
| D3 / CCR-C | Exact explicit owner approval authorizes one supported operation even at autonomous level 0. Caps continue to bound autonomy; hands-off and all hard validations still apply. | Section 8; I-10, I-20 | Distinct action authority and immutable payload/account/resource binding; no fake level-0 requirement or licence promotion; provider ambiguity reconciliation. |
| D4 / CCR-D | Persist immutable edited text in the response, preserve original generated draft, validate the exact reviewed version and send through Executor. | Sections 4, 9 | Versioned request/result models, provenance, validator parity and actual editor behavior. Editing body alone does not relabel REPLY. |
| D5 / CCR-E | Keep public `iter_situations(source, since)`; use a shared internal raw-observation mapper. | Section 5 | Source/cursor adapter and conformance tests across synthetic/live observations; no alternate evidence semantics. |
| D6 / CCR-F | Preserve the already approved typed administrative queue: API inserts intent; Examiner owns admin completion, habit denial and append-only drift receipts. | Section 3 | Existing WP1 implementation evidence remains in its closure report; later general commands need exact type/owner schemas and integration tests. |
| D7 / CCR-G | Add exact family/class/action/time report filters and echo the applied scope; separate historical counts, permission bounds, exams and current licence. | Section 9 | Scoped cohort tests/API/UI; explicit unavailable values for empty cohorts; no copied family score. |
| D8 / DOC-A/B/C | Keep ledger → proposal → draft atomic ordering; correct restriction monotonicity; retain query guard/grammar; choose Spruce & Brass dark brief; readiness reflects verified workflows. | Sections 8, 15; ENGINE_SPEC 7.1 | DOC-A was already resolved; validate the remaining web properties, query construction, UI/accessibility and readiness states. |
| D9 | Approve bounded connector/runtime/security architecture, prospective live evidence and retained full scope; retain concrete operational gates. | Sections 2, 14, 15 | Connector/provider/runtime proofs, concrete schemas/secrets backend, receipt wire/dependency/key approvals, resource scopes/budgets, deployment and actual study authorization. |

## 2. Full-spec decision mapping

This approval selects the following architectural directions. It does not convert
all FP decisions into completed schemas or operational authorizations.

| Full-spec gate | Selected direction | Still required before the dependent operation |
|---|---|---|
| FP-D1 | D5 public source/since boundary plus internal mapping | Adapter implementation/conformance. |
| FP-D2 | Training and labelled retrospective replay may use eligible backfill; live autonomous evidence starts prospectively | Provenance/cohort enforcement and no-peeking tests; historical replay cannot unlock live authority. |
| FP-D3 | Explicit role/row ownership, immutable events/intents, worker-owned results | Exact DDL/index/role matrix for each proposed connector/cursor/lease/budget table; no blanket table grants. |
| FP-D4 | Protected OS credential store/deployment secret manager or role-specific environment injection | Select/test a concrete platform store, refresh/rotation/revocation and secret provisioning; no new dependency is approved incidentally. |
| FP-D5 | Typed API requests consumed by the designated role; no tokens in commands | Lifecycle command models/ownership, migration and auth tests. |
| FP-D6 | Write-grant callback/exchange/refresh inside trusted Executor deployment boundary; separate observation grants | Registered flow, endpoints, account/resource scopes and role-bound secret isolation. |
| FP-D7 | External runtimes/MCP submit validated proposals; protected writes remain Executor-only | Pinned runtime/transport/manifests and no-bypass proof. This is not permission for Probation LLM tools or arbitrary external write tools. |
| FP-D8 | Permit supported non-recallable replies, owner-approved forwards and RSVPs with existing caps/hold/approval rules | Actual supported catalog workflow and clear cancellation versus undo evidence. Prohibited destructive/payment/sharing actions remain prohibited. |
| FP-D9 | Narrow, domain-only, separately quotaed Webfacts-owned public checker | Public endpoint/auth/abuse design and explicit deployment/live-spend authorization. |
| FP-D10 | All F01-F42/six packs retained; original phase ownership and dependencies remain | Acceptance evidence for every row; any earlier submission is labelled partial. |
| FP-D11 | Descriptive edits/denial; semantic corrections are prospective, provenance-bearing feedback | Exact UI/request/consumer contract without editing historic counts or hard caps. |
| FP-D12 | Separate consented study on synthetic stimuli, anonymous decision records and aggregates | Concrete protocol, retention/withdrawal arrangements and authorization to recruit/collect; no personal-account collection. |
| FP-D13 | Owner-selected validated forward recipient and exact reviewed payload; no model-selected recipient | Dedicated forward request/content/attachment rules, provider binding, immutable persistence and send ambiguity tests. REPLY remains original-sender-only. |

## 3. Migration and rollout requirements

The legacy DATA_MODEL DDL documents an existing baseline, not an implementation of
the approved new event/request/authority models. Introduce these through reviewed,
versioned additive migrations with synthetic compatibility tests. Existing worker
code must not read a new schema until its compatibility/readiness gate passes.

Preserve every historical ledger payload, hash and sequence. Preserve initial
decisions; later corrections append linked events. A derived projection may change
only as a reproducible consequence of events visible at the requested cutoff.
Response text stays in protected local payload storage; ledger entries contain
identifiers/decisions/hashes, never edited bodies, credentials or recipient addresses.

The new response route/fields are the approved target API. Implement schema-version
compatibility explicitly; until the full workflow is ready, report it unavailable.
Neither a 202 acknowledgement nor a recorded human decision proves a remote effect.
An ambiguous effect stays visible for reconciliation and cannot trigger blind retry.

## 4. Acceptance mapping and scope

Implementation regressions remain V03-V05, V08-V10, V14-V21 and V23-V33 in
`CHANGES_IMPLEMENTATION_PLAN.md`, plus T-ID/T-CLOCK/T-LEDGER/T-SEC/T-NOPEEK,
T-EVIDENCE/T-EXEC/T-API and T-WEBISO. Add versioned request/migration/as-of and
external-runtime no-bypass cases before enabling their dependent workflows.

This amendment is documentation only. It does not claim the new schemas, feedback
lifecycle, connectors, receipts, human study or full product have been implemented.
It does not waive unchanged invariants or authorize spending, new destinations,
private data, installations, signing-key provisioning, publishing or recruitment.
Future contract amendments still require explicit human approval.

Documentation validation: all 14 affected Markdown documents passed local-link,
code-fence and text-encoding checks; D1-D9 and FP-D1-FP-D13 coverage was verified;
`git diff --check` passed. The 11 pre-existing modified application/test files
matched their recorded SHA-256 hashes at the initial documentation validation.
A later final check observed a concurrent change to `engine/replay.py`; it was
left intact. This amendment changed documentation only. No runtime tests, code
implementation, commit or push were performed for this amendment.
