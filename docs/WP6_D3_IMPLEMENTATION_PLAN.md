> Integration authorization, 24 October 2026: the owner explicitly requested final verification, commit, push and merge into main. This supersedes earlier review-only/no-push instructions below. D3 email acceptance remains separate from whole WP6.

# Phase 5 / WP6 ? D3 email feedback and durable actions

Status: approved for implementation by the owner's execute-plan instruction and
explicit authorization to use subagents, merge/push D2, then branch from main.
This approval does not authorize real account access, provider spending, dependencies,
deployment, or push/merge of D3. Stop after the completed D3 handoff for review.

## Verified foundation and ownership

- D2 reviewed, corrected and integrated at 200ab938ff0986bdbb96005cd47bcc70dcfb1fb0.
- GitHub main and phase-5-demo-permissions-exams verified at that exact commit.
- D2 pre-merge isolated gate: 689 passed / 476.08s, lint/format and all typing pass;
  protected fixture/result hashes unchanged. See reports/phase-5.md.
- New phase-5-demo-feedback-actions created directly from main in data/wp6/worktree.
- Original root two dirty construction records remain byte-identical across merge;
  D2's four local construction updates and WP4/WP9 worktrees remain untouched.
- Graphify query-before-search applies to every agent; use root/main graph for
  initial navigation when the new worktree lacks a graph, then AST-update here.

The approved detailed conversational plan governs. CONTRACT > specifications > plans.
D3 is the email release slice plus shared safety/drift foundations, not whole WP6.
Existing WP1 action create-if-absent/terminal preservation is retained and extended;
it was already implemented, rather than a newly discovered replacement bug.

## Requirement / acceptance checklist

| ID | Required behavior / proof |
|---|---|
| D3-01 | Immutable v2 reviewed requests; atomic first valid Accept/Edit/Reject wins; stable retries and typed conflicts across independent connections. |
| D3-02 | Resolver records actual explicit decisions once, separately from effects; Reject no invented label, Leave no remote effect, body-only edit stays REPLY. |
| D3-03 | Append-only typed temporal outcomes/corrections; immutable legacy ledger; independent bounded evidence/training/correction projections; no future-peeking. |
| D3-04 | Typed role-owned receipts; API only inserts intent; Resolver/Executor/Examiner cannot forge another consumer/source; no generic raw-cursor bypass. |
| D3-05 | Explicit one-operation authority at licence0 is distinct from autonomy; exact server-owned owner/grant/account/resource/action/content/revision binding. Missing auth/grant fails closed. |
| D3-06 | Fresh D2 licence/exam/cap/restriction checks before autonomous effect and hold expiry; pending drift/pause/revoke block; lost authority requests Brain-owned linked suggestion. |
| D3-07 | Durable action/execute/undo intent, fenced claim, before-state and dispatch marker; no terminal reset or alternate resend attempt; ambiguous dispatch reconciliation only. |
| D3-08 | Archive/trash undo reverses actual changes only, preserving preexisting and unrelated state; conflicts/expired undo fail safely; confirmed execution-time deadline. |
| D3-09 | Original-sender validated stored reply; explicit approval immediate, genuine autonomous non-recallable hold10min and cancel; no post-send recall promise. |
| D3-10 | Restricted explicit-only forward contract: one controlled owner-selected recipient, no CC/BCC/attachments, exact source quotation, validated intro, max4800 chars/no silent truncation; default empty recipient set. |
| D3-11 | Truthful202 and owner-scoped response status; consumed receipt is not effect success; unknown visibly needs-reconciliation; original drafts/proposals immutable. |
| D3-12 | Durable deduped correction/eligible-decision CUSUM, configured thresholds, posterior baseline at actual licencechange, two corrections30days acrossrestart; no agreement pollution. |
| D3-13 | PSI from real fitted aligned top5 original features inclreader; maxabs aggregation/tie-name; reference-only bins, disjoint90/30day windows, insufficient/unavailable distinct. |
| D3-14 | Bounded worker batches/Clock/graceful shutdown and restart; rolecoordinator never combines credentials; fake provider crashgap proof, no blind resend. |
| D3-15 | Preserve D2 coldstart200/goldenmath/audit/strong/exams; all-family regressions, file boundaries, Reading/Chains unavailability; no whole-WP6 claim. |

Release acceptance: A01/A07/A09?A15; V03?V05, V08?V10, V15?V21;
T-EXEC/T-EVIDENCE/T-CUSUM/T-PSI/T-API/T-E2E/T-NOPEEK/T-LEDGER/T-SEC.
A16?A18 real Gmail and A22 browser acceptance remain downstream D4/D6.

## Shared interfaces and reviewed storage design

Concrete schema/ownership was independently reviewed by execution/storage agents
before enablement. New tables: outcome_events, command_receipts, execution_attempts,
command_requests; additive user_responses and action binding columns. Existing
admin_commands remains unchanged. Bootstrap-only transactional rerunnable migration;
legacy rows/ledger preserved, ambiguous legacy authority blocked, no invented proof.

Common records core/lifecycle.py: ApprovalBinding and ResponseIntent, SourceGrant
(source_id,connection_id,account_id,from_addr), ReceiptClaim, AttemptClaim.
Shared validation core/review_binding.py; API injected OwnerContext default absent403;
explicit server synthetic grants in tests, no source-id-as-auth/account fallback.

Typed db/lifecycle_* repositories: ResponseStore, EventStore, ReceiptStore,
AttemptStore, ActionStore, CommandStore. General/raw writes denied to typed tables.
Receipt identities derive consumer from actual worker role, not client input.
Receipt success means durable CONSUMPTION; actual effect status derives action/attempt.
One attempt per (action_id,execute|undo). prepared can reclaim expired fence; dispatched/
unknown may only reconcile; generic post-dispatch exception is unknown. Identity and
terminal states immutable. Event+ledger+receipt commits atomic; no I/O transaction.

Commands pause/resume/revoke: owner outside scope; connection/account mandatory,
optional resource_id and complete class_key/action pair. Pending pause/revoke denies
immediately. Resume only clears pause, never revocation. Revision last relevant
completed intent ID (baseline0). Root bounded restrictions seam supplied to Executor.

Narrow mail protocol snapshots actual labels/native identity/revision and applies/
reconciles by stable operation ID+payload hash. SimWorld journals provider receipt
atomically with its world effect. Missing durable capability fails closed. Real
Gmail/D4 is a future adapter and separately authorized acceptance gate.

## Parallel ownership and task order

- Storage agent: lifecycle SQL/repositories/records, migrations/connection/guards,
  typed grants, storage tests. No API/Executor/corehistory edits.
- API/Resolver agent: response/review/control/read seams, router wiring, shared
  review validation, genuine response/footprint processing and focused API tests.
- Execution agent: Executor lifecycle, mail operations/durable IO, SimWorld journal,
  before-state/hold/undo/reconciliation/fault tests. No shared schema/type edits.
- Parent: core bounded projections, D2 evidence/posterior baseline, drift/PSI,
  restrictions/Brain followups/scheduler/replay wiring, integration and records.

1. [x] Verify baseline, ownership, approved plan and concrete shared contracts.
2. [x] Write failing boundary/concurrency/temporal/permission/action tests first.
3. [x] Implement reviewed schema and typed shared stores; review actual constraints.
4. [x] Implement independent API/Resolver and Executor/mail work against contracts.
5. [x] Integrate bounded events, restrictions, drift and Brain-owned followups.
6. [x] Demonstrate qualifying positive and correctly blocked scenarios with fixed seeds.
7. [x] Focused tests, isolated full scripts/check.py, application and strict typing;
   ledger/protected hashes/diff check; no weakened/skipped tests.
8. [x] AST Graphify update, local original feature logs/index and Phase5 D3 handoff.
9. [x] Commit and integrate after the green check under the owner's later explicit authorization.

## Required acceptance scenarios

Suggest->Accept->one archive+decision; explicit0approval without promotion;
Reject->noeffect; action/body edit exactbinding; qualifying heldreply->cancel0sends;
archive/trash->actualundo once; crashaftereffect->reopen->confirmorunknown/noresend;
two corrections acrossrestart->alarm/demotion->later exactpair exam;
behavior-vs-input shift planted/negative controls; safe explicitforward and denied
wrongrecipient/attachment/oversize/changedquote cases; 50 seeded futuremutationcuts.

All synthetic/fake/offline. .env never read, provider credits0, installs0, deployment0.
The final result reports exact tests/versions/counts/hashes, not a predicted count.
Missing production auth/live connector/real model quality remains explicit.

## Handoff and rollback

Separate report docs/reports/phase-5-d3.md; preserve D2/historicalreports and link new
handoff from phase5. Update original local featurelogs plus summary/index; do not
commit local construction records or overwrite otheragents' logs.
Review incomplete whole-WP6 families, D4 account/polling/providerreceipts, D6 UIv2,
paid-model parallel/recovery and real forward provisioning as downstream obligations.
Stopworkers beforemigration. Retain durablejournals/accounting/ledger during repair;
never restore an oldDB and blindly replay dispatched operations. Prefer forwardfix.

## Final acceptance

833 passed, 0 failed, 2 pre-existing deprecation warnings / 778.15s; ruff lint/format, application typing and strict core/engine typing passed. Protected fixture/result hashes unchanged; no CONTRACT changes. Graphify AST update completed (6,243 nodes / 16,578 edges / 275 communities). See reports/phase-5-d3.md.
