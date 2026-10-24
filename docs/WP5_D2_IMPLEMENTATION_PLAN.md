# Phase 5 / WP5: D2 permissions and meaningful exams

Status: implementation and local acceptance complete; owner review pending.
Approved for implementation by the owner's 24 October follow-up to finish
as soon as possible with focused testing. No push/merge authorization.
Prepared 24 October 2026 (Asia/Kolkata). Owner: the Phase 5 agent in this worktree.

## Baseline and ownership

- [x] Read AGENTS.md, CONTRACT.md, the D2 release plan, WP5 remediation scope,
  ENGINE_SPEC, DATA_MODEL, PACKS_SPEC, PROMPTS, TEST_PLAN, and Phase 3/4 handoffs.
- [x] Run Graphify query before source searches/reads. No wiki index exists.
- [x] Verify local main and local origin/main both resolve to
  `fd459420d45c22a259a32db409faa665828941db`; Phase 3 `398729e` is an ancestor.
  No fetch/account access was performed; this verifies available refs, not a new
  remote-server observation.
- [x] Inspect branches and worktrees. WP4 remains at fd45942; WP9 remains at
  a5610a0. Both were clean when inspected. The historical Phase 5 branch is not
  the baseline or evidence that the repaired D2 requirements are met.
- [x] Create branch `phase-5-demo-permissions-exams` directly from main in
  `data/wp5/worktree`. HEAD is fd45942; no unfinished working files copied.
- [x] Preserve root dirty construction records:
  `build_history/index.md` and
  `build_history/phase_04_engine_core_backtest/feature_policy_novelty_lb.md`.
  Do not reset/stash/replace them, or modify other worktrees.
- [x] Verify handoff scope: Phase 3 sequential accounting accepted; Phase 4
  records 629 passing tests, real offline MiniLM and shared snapshot acceptance.
  Those are historical accepted results, not newly executed Phase 5 checks.
- [x] Reuse explicit approval for cold-start 200, CCR-002 limits, sequential
  dispatch and unavailable Reading/Chains suppliers. Earlier Phase 3/4 merge
  authorization does not authorize a Phase 5 merge or approve this new plan.
- [x] Obtain approval of this concrete task/test/file checklist, as required by
  AGENTS.md and AGENT_PLAYBOOK section 5.0, before writing regression tests/code.

## Scope and acceptance matrix

Authority: CONTRACT unchanged; ENGINE_SPEC sections 6-9/15-16;
CHANGES_IMPLEMENTATION_PLAN section 9; OCT29_DEMO_BUILD_PLAN sections 6-8 and
acceptance catalogue. D2 is WP5 email acceptance with other-family regressions.
It is not whole-WP5 completion or the original whole Phase 5 lifecycle gate.

| ID | Requirement and required proof |
|---|---|
| D2-01 | Eligible as-of evidence through HistoryView; one decision per committed proposal; exact class/action scope; strong/all/recent counts independently verified. Exclude ABSTAIN/no-op/invalid actions, automated effects/silence, corrections, and retrospective/backfill from live authority. Genuine rejection counts as disagreement without an invented alternative label. Audit holdouts remain eligible. |
| D2-02 | Preserve clipped parent pooling, strong-only higher levels, raw minimum/recent count, all golden numbers and configurable thresholds. Keep production cold start 200 and two effective training classes. |
| D2-03 | One read-only derived licence path for Examiner, API, Brain/replay and Executor recheck. Cache only for presentation/performance; no authoritative cache fallback. Include disappeared/aged-out pairs, truthful counts/bounds/exam ID/caps/reasons/valid_until. |
| D2-04 | Exact-pair tested-level exam validity: finished and known by cutoff, within configured age, after applicable pair and family alarms. Missing/failed/incomplete/future/stale/pre-alarm/incompatible exams cannot authorize levels 2/3. Level 3 also requires recallability and cap. Historical queries cannot consume future alarm/cache state. |
| D2-05 | Real counterfactual base and edited predictions share WP3/WP4 feature/reader/redaction/encoder/policy/novelty/cap/hands-off/gate pipeline. Freeze model/version/history cutoff, seed and audit identity; never refit on edits or create operational proposals/actions/evidence from exams. Missing fitted policy/reader/novelty/operator support fails closed. |
| D2-06 | Deterministic month-stratified exact class/action/candidate-level eligible base cohort. Minimum is distinct action-taking base cases, not repeated edits. Enforce coverage of each required operator; invalid edits and pipeline/reader failures remain visible and cannot be hidden by easy operators. |
| D2-07 | Cover all ten mail operators in PACKS_SPEC 1.8. Code validates edits and grades invariant action+gate and directional rank semantics; add explicit expected conditional caps for unfamiliar sender/money/personal-info hazards. Injection cannot raise autonomy. Recompute sender history and action-specific loss/recall/caps after changes. |
| D2-08 | Deterministic run/case identity and provenance include exact cohort IDs, tested level, seed, model/prompt/feature/policy/novelty/history versions and cutoffs. Record coverage, failed/discarded edits and reasons; repeated retries cannot rewrite a result. Preserve ledger bytes and role ownership. |
| D2-09 | Review scheduling uses valid fitted contexts, highest numerically eligible capped level, persisted deterministic oldest-candidate ordering and bounded attempts. Restart cannot reset the configured quota; unchanged insufficient evidence is not retried every tick. Explicit new attempts remain identifiable. |
| D2-10 | Real fitted shortcut-sensitive policy fails an eligible perturbation; supported fitted policy passes. Deterministic prospective synthetic replay earns level 2 only on genuinely qualifying evidence/exams; separate insufficient/invalid/stale/alarmed controls remain Watch/Suggest. No threshold lowering or held-out tuning to force promotion. |
| D2-11 | API returns exact evidence, bound and exam status separately through the same derivation path, with compatible response shape. Preserve historical licence-change readers including prev_level; new ledger payloads canonical. No frontend work. |
| D2-12 | Retain all-family conformance/regressions, file alias/action parameters, audit/economic boundaries, role isolation, no-peeking and ledger determinism. Reading/Chains remain unavailable without approved suppliers. Report unsupported whole-WP cases as obligations. |

Release mapping: A01 isolation, A03 offline model regression, A04 reader failure,
A05 policy eligibility/identity, A06 temporal replay, A07 actor/provenance separation,
A08 meaningful exams, A09 derived permission parity; V08-V15, V29 and V32;
T-EVIDENCE, T-LB, T-CAPS,
T-GATE, T-EXAM, T-NOPEEK, T-LEDGER, T-WEBISO and relevant T-API/T-E2E regressions.
Existing T-CUSUM/T-PSI/T-EXEC must remain green; D3's new lifecycle/drift algorithms
are not included in this package.

## Test-first task order

1. [x] Add failing evidence/licence/exam-validity/gate/no-peeking regressions
   before repairing production logic. Record focused red output and exact causes.
2. [x] Extend bounded HistoryView projections for evidence and exam selection,
   with explicit provenance qualification and historical alarm reads. Prefer
   existing immutable ledger projection; do not begin WP6 outcome ingestion or
   its migration. Ambiguous legacy provenance is excluded with reasons.
3. [x] Implement pure configurable evidence calculations and one read-only
   licence derivation plus valid-exam selection. Keep Examiner cache persistence
   separate. Verify zero writes through API/Executor capabilities.
4. [x] Strengthen frozen exam context/time/version checks; registry-based exact
   pack dispatch; real full-pipeline inference; candidate-level/action-taking
   bases, operator coverage, critical hazard assertions and code-only verdicts.
5. [x] Persist complete deterministic provenance/results within existing
   examiner-owned exam tables/details JSON. Include failed/discarded counts and
   per-operator coverage; no new table/role/credential needed is assumed.
6. [x] Wire snapshot/context provisioning into existing Examiner/admin/replay
   callers and scheduling; enforce persisted quota/retry semantics using existing
   exam/admin records where sufficient. No parallel dispatch or lease recovery.
7. [x] Move existing consumers to shared read-only derivation. Executor changes
   are limited to authority recheck consumption; no action/response lifecycle work.
8. [x] Run frozen qualifying/blocked/shortcut synthetic acceptance with fake
   providers, no generation-truth inputs to prediction. Capture exact counts,
   versions, seeds, cutoffs, exam reasons, gate outcomes and ledger heads.
9. [x] Run focused regressions, isolated full checker and strict typing; verify
   protected fixture/result and CONTRACT hashes, Graphify AST update, diff check.
10. [x] Write local construction logs/index, decision notes if behavior changed,
    and Phase 5 D2 handoff; preserve and label historical Phase 5 claims. Stop for
    review; no push/merge and no next release package.

## Regression checklist (implemented focused test modules)

| Module under backend/tests/ | Cases required before implementation |
|---|---|
| unit/test_wp5_evidence.py | Deduped first decision; eligible audit/user-handled cases; strong vs weak; rejection disagreement; ABSTAIN/no-op/system/undo/cancel/backfill exclusions; evidence window and microsecond boundaries; configured pooling and counts. |
| unit/test_wp5_licence_derivation.py | Exact pair; level 2/3 positive and negative maths; all tunables; no weak promotion; cap/recall constraints; zero evidence and expired pair; poisoned/future cache ignored; no writes. Existing golden tests retained. |
| unit/test_wp5_exam_validity.py | Missing/failed/unfinished/stale/future/pre-alarm/wrong-pair/wrong-level/incompatible pass; exact expiry/alarm boundaries; newer valid pass; level 3 qualifies level 2; all family aliases; future alarm does not contaminate historical result. |
| unit/test_wp5_exams.py | No snapshot/operator/reader support; distinct eligible base minimum; exact cohort and month stratification; coverage for every mail operator; invalid/failed edits; conditional cap assertions; deterministic IDs/provenance/retry and stable audit draw; action metadata recomputation. |
| unit/test_wp5_scheduling.py | Eligible highest candidate, hard caps, deterministic oldest ordering, configured quota across restart/review retry, unchanged-insufficient suppression, explicit attempt identity, fail-closed missing snapshot. |
| integration/test_wp5_permissions_exams.py | Actually fitted sound and shortcut policies using shared features; same read-only result across consumers; qualifying prospective replay level 2 and blocked controls; code-graded real exams and ledger verification; no exam operational effects/evidence pollution. |
| property/test_wp5_no_peeking.py | Seeded cuts/future raw+decision+alarm+exam mutations do not alter pre-cut evidence, permission, exam cohort or predictions. Frozen fitted model/history identity checked; deterministic rerun heads. |

Use existing deterministic fixtures/fake consumers and registered schema validation.
Split modules below roughly 400 lines. Do not weaken or delete existing tests.
These modules now exist; exact final verification is recorded in the handoff.

## File ownership

Exclusive Phase 5 changes in this isolated worktree only:

- Primary: `backend/src/probation/engine/{evidence,licence,exam,exam_prediction,exam_storage}.py`;
  small new focused engine helpers if needed to keep files manageable.
- Bounded projection seam: `backend/src/probation/core/history.py` and focused
  history helpers, `db/guards.py` and new `db/history_snapshot.py` for physically
  bounded read-only copies, reusing `history_wp4.py` where its existing projection applies.
- Consumers: `workers/{examiner,scheduler,admin}.py`, narrow derivation adapters in
  `workers/{brain,executor}.py` and `engine/replay.py`; no WP6 lifecycle changes.
- Dispatch/operators: `packs/registry.py`, `packs/mail/exam_ops.py`; other pack
  exam adapters only for shared dispatch compatibility and existing regressions.
- API: `api/routes/licences.py`, scoped permission/exam detail adapters only where
  required for shared results. Preserve existing wire compatibility.
- Supporting types/config: `core/types.py`, `config.py` only if existing fields
  cannot represent D2; preserve defaults. Extract unchanged feature identity into
  `llm/feature_identity.py` without importing pack/connector code into licences. No dependency changes or CONTRACT edits.
- Tests: proposed modules above plus narrowly extended existing contract tests.
- Records: this plan, `docs/reports/phase-5.md`, relevant decision notes, Graphify
  outputs and Phase 5/exam local build logs/index in this worktree. Root dirty
  logs remain owned by their current author; never overwrite them during integration.

No ownership claimed for frontend, web/links services, connectors, model weights,
other worktrees, protected fixtures/results or unfinished suppliers. If a required
schema/role change or unresolved spec conflict is discovered, prepare exact scope
and stop the affected change for review rather than silently expanding this plan.

## Verification and handoff gate

- [x] Focused red/green test commands and results recorded.
- [x] Existing isolated `python -B scripts/check.py` (documented make-check
  equivalent), application mypy and strict core/engine typing pass. Use the
  installed interpreter/toolchain; no install, .env load or provider access.
- [x] New checks run in secret-free isolated cwd/config with synthetic temp data;
  protected fixture/results untouched in source and checker snapshot.
- [x] Golden mathematical and production cold-start 200 tests pass unchanged.
- [x] Qualifying and blocked acceptance artifacts are reproducible; counts and
  all unrun/unsupported cases explicit. Full WP5 acceptance is not claimed.
- [x] `graphify update .` and `git diff --check` pass after implementation.
- [x] CONTRACT unchanged; ledger verifies; no secrets/accounts/credits/network
  destinations/dependencies/deployment introduced.
- [x] Construction logs use BUILD_LOGGING_PROTOCOL and log_schema; update local
  index without losing preexisting records. Keep construction updates local under
  BUILD_LOGGING_PROTOCOL; existing tracked records remain present and unstaged.
- [x] Handoff follows AGENT_PLAYBOOK section 6 with exact branch/commit/dirty
  identity, requirements, tests, provenance, rollback, blockers and obligations.
  Preserve historical handoff as explicitly superseded context, not current proof.
- [x] If committing, run required check first and use `phase-5: ...`; no push or
  merge. Stop after D2 handoff for review. D3/WP6 and full WP5 remain downstream.
