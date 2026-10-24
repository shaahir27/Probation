# Phase 5 D3 handoff — feedback, controlled mail actions and drift

Branch: `phase-5-demo-feedback-actions`, created directly from verified main
`200ab938ff0986bdbb96005cd47bcc70dcfb1fb0` in `data/wp6/worktree`.
Status: D3 email-slice acceptance PASSED; whole WP6 remains open. The owner authorized commit, push and merge on 24 October 2026, superseding the previous review-only stop.

## Done

The API durably records an exact reviewed decision. Resolver records the actual human
decision separately; Executor performs only its authorized operation. Approval can
work at licence 0 without promoting autonomy. Reject creates disagreement without an
invented alternative; Leave creates no remote action. Edits retain the original
proposal/draft and bind a separate exact payload. Missing owner/grants fail closed.

Mail operations now capture actual before-state, enforce undo deadlines and detect
conflicting changes, including a label removed and reapplied by another actor. Reply
and restricted explicit forward validate sender, recipient, content and native thread
identity. Stable operation IDs, fenced attempts and fake-provider receipts handle the
crash gap; unknown sends remain needs-reconciliation without automatic resend.

Autonomy rechecks current derived licences/exams/expiry/alarms and actual conditional
caps. Pending drift/pause/revoke blocks. Authority loss requests a fresh Brain-owned
restricted prediction linked to its cancelled action; the original stays unchanged.
Separate role connections, bounded batches and injected Clock support stop/restart.

Correction events feed durable deduplicated CUSUM without adding agreement votes.
Configured thresholds and the specified posterior baseline are retained. Family PSI
uses actual fitted coefficient-aligned features, reference-only numeric bins and
disjoint windows; insufficient/unavailable results are explicit.

## Files changed

- `core/lifecycle.py`, `core/review_binding.py`, `core/types.py`, bounded HistoryView
  helpers/projections and `db/history_snapshot.py`.
- `db/lifecycle.sql`, typed `db/lifecycle_*.py`, bootstrap migrations, proposal
  followup migration/persistence and narrow role guards.
- `api/authority.py`, `api/review_models.py`, response/control routes and existing
  queue/action/item/insight/readiness integration.
- `workers/{response_resolver,resolver_observations,mail_responses,mail_execution,
  restrictions,brain_followups,lifecycle,shift}.py` and existing worker integration.
- `packs/mail/{lifecycle_io,lifecycle_operations,executor}.py`, synthetic mail journal.
- `engine/{drift,shift,drift_baseline,evidence,licence,replay}.py`, configuration.
- `backend/tests/unit/test_wp6_*.py`, `backend/tests/integration/test_wp6_*.py`,
  and existing API/Executor fixture upgrades retaining their effect assertions.
- `docs/WP6_D3_IMPLEMENTATION_PLAN.md`, `docs/WP6_D3_MAIL_CONTRACT.md`, DATA_MODEL
  implementation addendum and this handoff. Local construction logs are kept local.

## Tests

Final command: `C:/Users/shaah/miniconda3/python.exe -B scripts/check.py` (exit 0).
Result: **833 passed, 0 failed, 2 existing Typer/Click deprecation warnings in 778.15s**. Ruff check/format: 340 files formatted. Application mypy: 206 source files passed; strict core/engine: 49 files passed. Protected fixture/result hashes unchanged in both source and isolated snapshot. Safe local output: `data/wp6/integration-check.log`.
This is the portable `make check`: lint/format, application typing, strict core/engine
typing, then the complete suite in a secret-free isolated snapshot, with protected
fixture/result hashes checked before/after.

Focused results already measured:

- API/Resolver/controls/schema readiness/evidence/coordinator: 60 passed / 9.30s.
- Seeded temporal cuts after future events/control completion: 50 passed / 14.12s.
- Populated migration rollback plus linked followup/frozen-history integration:
  2 passed / 4.33s; later derived-permission refinement: 2 passed / 4.40s.
- Genuine exam/evidence/default-Executor held replies and two corrections across
  restart: passed / 6.47s before final followup extension.
- Application mypy: 205 files passed; strict core/engine: 49 files passed before
  final integration. The final gate supersedes these intermediate counts.

RED/GREEN regressions included arbitrary exam/permission validity before D2 merge;
D3 shared-store ownership/races and rollback, forged/changed review semantics,
attachment flags, missing schema, pending Pause overridden by Resume, duplicate
followup evidence, configured drift eligibility/baseline, real effect failures,
clock-expired completion and touched-label ABA undo conflict. No weakened/skipped
test was used to obtain success.

Tests trace to T-EXEC, T-EVIDENCE, T-CUSUM, T-PSI, T-API, T-E2E, T-NOPEEK,
T-LEDGER and T-SEC. Synthetic reader/editor/novelty and controlled training data are
declared fixtures, not claims of Nemotron quality or live provider acceptance.

## Invariants touched

I-2/I-3: API writes intent; owned workers append decisions/corrections/receipts;
only Executor receives the fake target effect capability. I-6/I-7/I-8: bounded
HistoryView, immutable temporal events and hash-chained ledger, prospective eligible
evidence only. I-9: injected shared Clock. I-10/I-12/I-20: derived permission,
hard caps/hands-off/audit, meaningful exams and fail-closed current checks. No web
input raises policy/evidence/licence authority. Golden maths/coldstart remain gated
by the full existing suite.

## Deviations and assumptions

D3 is the approved email release slice and shared safety/drift foundations. It is
not completion of all WP6 families. Source/account/owner grants are explicit test
dependencies; there is no production authentication or source-ID authorization
fallback. The coordinator uses role callbacks; D4/WP12 supplies actual observation
polling, process supervision and connector grants. The restricted forward decision
is recorded in `docs/WP6_D3_MAIL_CONTRACT.md`, empty allowlist by default.

The proposal uniqueness extension is required by CONTRACT section 8's fresh linked
Brain followup. The old initial uniqueness remains via a partial index; typed
persistence validates cancellation provenance and at most one linked replacement.
Frozen history copies canonical temporal events and minimal inert cancelled-action
references, excluding operational approval bodies/attempts/write credentials.

## Contract change requests

None. CONTRACT.md was not edited.

## New dependencies

None. No installations.

## LLM cost incurred

USD 0; zero provider calls. No `.env`, accounts, personal records or live services used.

## Open questions and downstream obligations

D4 must supply actual Gmail authorization/scope checks, grants, MIME/native receipts,
sync/cursor recovery and real controlled-account acceptance; the fake journal does
not prove Gmail exactly-once behavior. D6 must adapt review/response/status/controls
to v2 and complete browser/accessibility acceptance. Other WP6 family effects and
undo remain separate gates; Reading/Chains remain unavailable without their approved
suppliers. Paid parallel model dispatch and automatic model lease recovery remain
deferred. No real forward recipient/account has been provisioned.

## Suggested next step

Owner-authorized commit and fast-forward integration follow the completed green check. D2 was previously merged/pushed: main and `phase-5-demo-permissions-exams`
were remotely verified at `200ab938ff0986bdbb96005cd47bcc70dcfb1fb0`.

## Final integration fixes supplied by the owner

The fitted-snapshot guard now narrows PredictPolicy to the actual Policy class before accessing fitted/time/family metadata. Existing fake mail IO implements the durable snapshot/CAS/reconciliation protocol; payload PSI tests provide an actual fitted policy; observation tests request an actually executable proposal for autonomous cases. These retain the production guards. Tests that open SimWorld now copy the protected world fixture to tmp_path before schema initialization. Original protected files are preserved; no assertions were removed to obtain a pass.

## Graph and workspace verification

AST-only `graphify update .` completed: 6,243 nodes, 16,578 edges, 275 communities. The graph remains local/ignored according to the existing repository policy. Existing synthetic text files with PDF suffixes and the missing optional SQL parser produced indexing diagnostics; no dependencies were installed. Original root construction records retained their pre-integration SHA-256 values. WP4, WP5 and WP9 worktrees were preserved.
