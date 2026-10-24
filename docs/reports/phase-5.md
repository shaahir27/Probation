D3 email-slice continuation: see [phase-5-d3.md](phase-5-d3.md) for the separate implementation, acceptance and integration record. Whole-WP completion remains separate.

# D2 pre-merge review update ? 24 October 2026

The owner explicitly authorized merging Phase 5/D2 into main, pushing both branches,
and then creating the D3 branch from updated main. This supersedes the earlier
no-push/no-merge instructions retained in the historical D2 handoff below.

Independent review found and repaired three additional D2 validation gaps before
integration: stored proof must match the authoritative operator catalogue with
integer distinct-base coverage; model/history snapshots must exist by exam start;
and a fail-closed pipeline error on a directional edit cannot count as a successful
safety response. The new conditional-cap failure regression first demonstrated an
incorrect passing exam, then passed after the repair. Catalogue metadata was moved
unchanged into a pure shared module; licences still import no web/connectors.

Focused review gate: 47 passed in 59.50s, plus the red/green injected cap-failure
regression (green 1 passed in 5.52s). Final isolated pre-merge gate: 689 passed in 476.08s; exit0; lint/format/application typing/strict core-engine typing pass; protected fixture/result hashes unchanged.
AST Graphify update: 5755 nodes / 14162 edges / 265 communities. No dependencies,
accounts, provider calls, costs, CONTRACT changes or ledger rewrites for this repair.
GitHub access in this continuation is limited to the owner's explicitly authorized
Git verification/push. Source/runtime account access remains unauthorized.

This update and correction are committed as `phase-5: harden exam proof before integration`.
D2 email acceptance remains separate from whole-WP5 obligations. D3 starts only
from verified main containing this correction; its implementation is separate.

---

# Phase 5 / WP5 D2 handoff: permissions and meaningful exams

24 October 2026. **D2 implemented; review pending. Whole WP5 is not accepted.**
Branch: `phase-5-demo-permissions-exams`. Base: local main and local origin/main
`fd459420d45c22a259a32db409faa665828941db`; Phase 3 `398729e` is an ancestor.
This verifies available refs without accessing an account or fetching the remote.
The implementation commit is the `phase-5: meaningful exams and derived permissions`
commit containing this handoff; inspect `git log -1` for its exact hash.
No push, merge, deployment or next package is authorized or performed.

## Done

The requirement/task/test/ownership matrix is in
[WP5_D2_IMPLEMENTATION_PLAN.md](../WP5_D2_IMPLEMENTATION_PLAN.md), D2-01 through
D2-12. Implementation remains in the isolated `data/wp5/worktree` checkout,
created directly from verified main without copying unfinished work. Root's two
preexisting dirty construction records and the other WP4/WP9 worktrees were
preserved. No CONTRACT change, dependency install or schema migration.

- Eligible evidence is reconstructed through HistoryView from committed prospective
  proposals and their first genuine immutable decision. Exact class/action scope,
  strong/all/recent counts and audit holdouts remain distinct. Automated effects,
  no-op/ABSTAIN, backfill, corrections and duplicate votes cannot inflate authority.
  Rejection is disagreement without an invented alternative training label.
- One read-only licence path serves API, replay/Brain, Examiner and Executor's final
  authority recheck. Fresh evidence, configured thresholds, strong-only higher
  levels, current caps, meaningful exams, expiry and applicable alarms determine
  permission. Caches never authorize; aged-out/disappeared pairs demote. Existing
  golden bounds, audit semantics and production cold-start 200 are preserved.
- Real exams freeze a fitted policy, bounded history, novelty references and shared
  WP3/WP4 prediction settings. Physically materialized read-only history excludes
  future rows. No edited-case refit or operational proposal/action/evidence write.
  Original base identity preserves audit draws. Full identity includes policy,
  feature/model/history cutoffs, novelty/provider, seed and exact cohort IDs.
- Exact class/action/candidate-level, month-stratified action-taking bases undergo
  every required operator. Each operator needs the configured minimum distinct
  bases. Missing readers/models/coverage and failed edits stay visible and fail
  closed. Code grades action/gate invariance, directional autonomy and hazard caps;
  there is no invented confidence, LLM verdict or default passing result.
- Durable unfinished exam claims precede inference and consume scheduled quota.
  Completed retries cannot replace results; explicit new ordinals distinguish new
  attempts. Deterministic oldest-candidate ordering and unchanged-insufficient
  suppression survive review/restart. Completion and its cases/ledger are atomic.
  No automatic lease recovery or parallel dispatch was added.
- Missing/failed/incomplete/stale/future/pre-alarm/incompatible exam proof cannot
  authorize higher autonomy. Pair/family alarm aliases and historical reads are
  covered. Legacy bare passing rows remain present but cannot supply missing proof.
  API exposes agreement, strong/all bounds and exam validity separately.

## Files changed

All source paths below are relative to `backend/src/probation/`:

| Area | Files / purpose |
|---|---|
| Bounded evidence/history | `core/history.py`, new `core/permission_history.py`; `db/guards.py`, new `db/history_snapshot.py` for consistent read-only physically bounded exam history |
| Derived authority | `engine/evidence.py`, `engine/licence.py`, new `engine/exam_validity.py`; additive `core/types.py` fields; missing default tunables in `config.py` |
| Exams | `engine/exam.py`, `exam_prediction.py`, `exam_storage.py`; new `exam_candidates.py`, `exam_context.py`, `exam_grading.py`, `exam_mutations.py`, `exam_other_ops.py` |
| Operators | `packs/mail/exam_ops.py`, `packs/calendar/exam_ops.py`: provider failure cannot fall back to fabricated valid edits |
| Shared consumers | `api/routes/licences.py`, `engine/replay.py`, `workers/examiner.py`, `workers/scheduler.py`, narrow `workers/executor.py` authority consumption |
| Feature identity | New `llm/feature_identity.py`; unchanged semantic identity extracted from `llm/feature_pipeline.py` to keep licence validity independent of pack/connector imports |

New regressions under `backend/tests/`: unit `test_wp5_evidence.py`,
`test_wp5_licence_derivation.py`, `test_wp5_exam_validity.py`, `test_wp5_exams.py`,
`test_wp5_scheduling.py`; integration `test_wp5_permission_parity.py`,
`test_wp5_permissions_exams.py`; property `test_wp5_no_peeking.py`.
Fixture helpers: `unit/wp5_fixture_ledger.py`, `unit/wp5_exam_fixtures.py`.
Existing evidence/exam/WP1 fixture tests now carry genuine immutable commitments
or explicit proof fixtures; existing assertions/golden tests were not weakened.

Records: this report and [sanitized acceptance manifest](phase-5-d2-acceptance.json),
D2 plan, decision note and DATA_MODEL implementation note. No executable DDL changes.
Local feature logs updated in their original Phase 5/7 locations with historical
text retained and marked superseded. Local Phase 5 summary/index updated. Existing
tracked construction changes are intentionally unstaged under BUILD_LOGGING_PROTOCOL;
no root construction record was overwritten.

## Tests

Tests were written red before repairs for evidence, derived licences, exam validity,
gate parity and no-peeking. Red failures exposed mutable-outcome/cache authority,
legacy empty exam proof, future alarms, missing full-pipeline context/operator
coverage and physical future rows in the initial frozen copy. Repairs addressed
those behaviors; no test was skipped/deleted/weakened to pass.

**PASS: 682 tests in 377.68 seconds; exit 0.** Ruff lint and format pass
(287 files); application mypy passes 175 source files; strict core/engine mypy
passes 41 source files. Protected fixture/result hashes are unchanged in source
and isolated snapshot. Two installed Typer/Click deprecation warnings remain;
no dependency change is in scope. Git emitted a sandbox global-ignore-read warning;
the isolated checker completed successfully. `git diff --check` passes.

The required portable `python -B scripts/check.py` is the repository's isolated
make-check equivalent. It checks lint/format, application typing, strict core/engine
typing, full non-live regressions and unchanged protected fixture/result hashes in
source and its synthetic isolated snapshot. Local log:
`data/wp5/final-check-current.log`. Tests use a secret-free synthetic cwd/config,
existing installed toolchain and workspace-local pytest temp directories.
The previous complete source run passed **681 tests in 328.89 seconds**; after the
last bounded-snapshot hardening, its focused suite passed **25 tests in 51.75 seconds**.
The final current-source result above governs acceptance. The 25-test focused
command selected unit/test_wp5_exams.py, unit/test_exam_board.py and
integration/test_wp5_permissions_exams.py through pytest with workspace-local
--basetemp and the isolated synthetic cwd.

CONTRACT Git blob is unchanged: `7c29f227420d2334ad9e5ce5696fc1ae215f213e`
(normalized SHA256 `09c515bd60facc504e7890fd292fb49c9b1b6487ffa9f0f07da67dd405e8e1c5`).
Working-checkout CRLF normalization was accounted for; no CONTRACT edit.

Coverage mapping: T-EVIDENCE/T-LB (golden pooling and strong/all maths), T-CAPS/T-GATE
(caps, audit/economics and missing proof blocks), T-EXAM (actual fitted sound/shortcut
policies, coverage/claims/retries), T-NOPEEK (50 seeded permission cuts plus existing
replay properties), T-LEDGER/T-SEC/T-WEBISO (append-only, roles, independence),
T-API/T-E2E permission parity and all-family regressions. Existing T-CUSUM/T-PSI/
T-EXEC remain regressions; D3's new lifecycle algorithms were not implemented.

### Deterministic acceptance (synthetic providers)

Reproduce with the full checker or focused test modules
`integration/test_wp5_permissions_exams.py` and `unit/test_exam_board.py`.
The tracked JSON manifest contains exact IDs, ledger heads, cutoffs and snapshot
identities. Local complete manifests are in `data/wp5/acceptance.json`.

| Case | Actual exam result | Permission consequence |
|---|---|---|
| Qualifying prospective scenario | 27 bases x 10 operators = 270 cases; flip rate 0; critical violations 0; no pipeline/invalid-edit loss | `mail|fyi|frequent` / ARCHIVE, 105/105 strong and recent 105; strong LB 0.9742644357171694; level 1 before exam, level 2 after pass, level 1 after same-cutoff alarm |
| Nonsemantic embedding control | 270 cases; flip rate 0.75; fails | No higher permission; retained as a negative result |
| Actually fitted shortcut classifier | 23 bases x 10 = 230 cases; flip rate 0.5; fails | Cannot qualify an exam |

The prospective fixture is `d2-scenario-v1`, seed 705, 340 chronologically committed
situations; production cold-start 200 and two effective actions. Model cutoff
`2026-05-09T08:00:00Z`, exam/history cutoff `2026-05-15T05:00:00Z`.
All three ledgers verify and independent replay identities/heads match. There are
zero operational actions from exam cases. Stale/missing/future/insufficient/alarmed
controls remain blocked in the regression suite.

These are explicitly fake readers/editors and semantic fixture embeddings. The
SHA256 embedding control correctly fails rather than being tuned into promotion.
The shortcut uses a fitted Policy over validated reader features, not a replacement
exam predictor. No generation-truth file enters prediction. These prove code
behavior, not Nemotron language quality or real-model permission readiness.

### Offline provisioned MiniLM regression

Existing manifest-pinned `all-MiniLM-L6-v2` revision
`d13954661f83248295ba75c1ed411eef3b7b936e` passed `scripts/verify_embeddings.py`:
2 x 384 finite normalized repeatable vectors; duplicate novelty false/distance 0.
The shared frozen-context smoke retains the actual ONNX runtime, cold-start 200,
SHADOW at level 0 and ASK for missing reader. Provider identity:
`e7874ae8decaf9bd21b3b36df6eb1cf6556be6dcb89b5e805ab7221840ef1ac6`.
Rerun after final snapshot hardening passed with **0 network attempts**.
This is an offline adapter regression, not a passing real-model counterfactual exam.

## Invariants touched

- I-1/I-2/I-3/I-4/I-5: schema-validated model data, Executor-only target effects,
  fail-closed gates, unchanged hard caps/hands-off rules and code-only verdicts.
- I-6/I-7/I-8/I-9: HistoryView-only bounded evidence, genuine prospective time/seq
  ordering, append-only hash-chained ledger and injected clock. Frozen history
  excludes physical future rows and does not commit the caller's transaction.
- I-10/I-11/I-12/I-13: read-only derived authority, strong-only higher levels,
  one eligible decision per proposal/audit holdouts, and fresh post-alarm exams.
- I-14/I-15/I-16/I-17: shared redaction/registered budgeted consumers, deterministic
  identity/cache path and the same synthetic/production prediction code.
- I-18/I-19/I-20/I-21: synthetic evidence/no secrets, unchanged recallability and
  pending-drift restrictions; web facts cannot increase permissions. Existing
  web isolation regressions remain green; no web integration was added.

## Deviations and assumptions

D2 email acceptance is narrower than entire WP5 and the historical Phase 5 report
below. Calendar's `introduce_conflict` payload-only mutation is invalid: the real
pipeline derives conflict from accepted-event history. It requires a genuine bounded
history overlay before whole-family acceptance; no fake counter passes it here.
Reading/Chains remain unavailable pending their approved suppliers. Other families
have shared dispatch/regression compatibility, not newly claimed whole-family exams.

Existing trusted arithmetic-test seams remain optional Python arguments; production
API/Executor do not accept supplied evidence/exam success from clients. No migration
backfills fabricated proof. Unfinished attempts remain durable and fail closed;
operator-directed recovery/explicit new attempts are downstream work.

## Contract change requests

None. CONTRACT.md is unchanged; existing approved cold-start/CCR-002/sequential
scope and unavailable-supplier decisions remain in force.

## New dependencies

None. No install, credentials, account access or new network destination.
Graphify warnings are recorded below; no optional dependency was installed.

## LLM cost incurred

**USD 0; 0 real provider calls.** Synthetic fake dispatch only. No .env access.
No deployment, push or merge.

## Open questions / remaining blockers

- D2 is ready for owner review after the final gate; whole-WP5 acceptance remains
  open for actual calendar conflict overlays and remaining full-family coverage.
- No live Nemotron quality/evaluation, paid dispatch or external-provider acceptance
  was attempted. Offline MiniLM proof does not replace those later evaluation gates.
- D3/WP6 response/effect/hold/cancel/undo/correction lifecycle, approved Reading/Chains
  suppliers, connectors, frontend and later release packages remain downstream.
- Parallel model dispatch and automatic lease recovery remain deferred.
- `graphify update .` completed: 5,740 nodes, 14,136 edges, 270 communities.
  Local AST outputs are ignored. Warnings: synthetic text files named .pdf have no
  PDF content; optional tree_sitter_sql is unavailable (3 SQL files not extracted).
  No dependency installation or fixture modification was made. These limit graph
  extraction, not the application/test results.

## Suggested next step

Review this D2 branch, acceptance manifest, changes and deliberately blocked controls.
Do not merge/push without explicit authorization. Stop here; D3/WP6 has not started.

Backout: stop scheduled examinations and hold autonomous execution pending review.
Prefer a forward fix retaining existing attempts/evidence/ledger. There is no schema
migration to undo. Do not reset attempts, rewrite ledger/history, drop spend accounting
or restore cached authority. Local construction records must survive integration.

---

## Historical Phase 5 handoff retained (superseded, not current D2 acceptance proof)

The original report below describes an earlier broad phase and includes claims that
were not independently accepted by this D2 package. Use the new handoff above for
current scope/results. Its lifecycle work is not a claim of D3/WP6 completion.

# Phase 5 Handoff: Evidence, Licences, Gate, Executor, and Drift

**Branch / Commit:** `phase-5-evidence-licences-gate` / `4770806`  
**Phase:** 5 — Evidence, Licences, Gate, Executor, and Drift  
**Lane:** Lane A (Member 1)  

---

## Done
1. **Caps & Hands-Off Rules (`backend/src/probation/engine/caps.py`, `handsoff.py`)**:
   - Codified complete `ACTION_CATALOG` across `email_action` and `calendar_action` families with base caps, loss matrix values, recallable flags, and derived economic interruption bars ($p^* = 1 - 1/\text{loss}$).
   - Codified contextual conditional caps: VIP sender, external recipients, bulk recipients (>5), thread lengths (>10), sensitive keywords (financial, legal, security), blocked dangerous extensions (`.exe`, `.bat`, `.cmd`, `.msi`, `.ps1`), double extensions (`.pdf.exe`), and Unicode RLO (`\u202e`).
   - Implemented `effective_cap(base, context)` using integer `min` aggregation.

2. **Pure Gate Engine (`backend/src/probation/engine/gate.py`)**:
   - Implemented pure `decide_gate` with strict fail-closed precedence order:
     1. Hands-off violation $\to$ `NEVER` / `ASK`
     2. Budget exhausted $\to$ `ASK`
     3. Licence level $\to$ bounds max permitted gate
     4. Economic interruption test: $p(\text{action}) < p^*$ $\to$ demote to `ASK`
     5. Novelty / ambiguity $\to$ demote to `ASK`
     6. Audit holdout: reproducible 10% draw $\to$ demote to `ASK`
     7. Cap reduction $\to$ demote to `min(decision, cap)`
   - Verified 100% agreement with all 14 rows of Golden Table 3.2 in `CONTRACT.md` (`T-GATE`).
   - Implemented reproducible audit draw via SHA-256 HMAC of `(audit_seed, situation_id, class_key)`.

3. **Evidence Aggregation & Hierarchical Empirical Bayes (`backend/src/probation/engine/evidence.py`)**:
   - Implemented `aggregate_evidence` filtering out auto-executed items (Invariant I-12) and undo outcomes from Beta counts.
   - Tracked weak evidence (supports Level 1 only) vs strong evidence (explicit accepts/edits/undos).
   - Tracked audit holdouts and undo counts ($n_{\text{undo}}$).
   - Applied hierarchical Empirical Bayes pooling: action-level $\to$ class-key level $\to$ global prior, computing exact lower bounds (`Beta.ppf`).

4. **Dynamic Licence Ladder & Cache (`backend/src/probation/engine/licence.py`)**:
   - Implemented `derive_licence_level` (Levels 0..3) based on lower bound thresholds ($\ge 0.70, 0.85, 0.95$), sample size thresholds ($n \ge 5, 20, 50$), exam pass status, non-recallable cap at Level 2 (Invariant I-20), and drift alarm invalidations.
   - Built `derive_and_cache_licences` with TTL caching and ledger event emission.

5. **Statistical Drift & Anomaly Monitoring (`backend/src/probation/engine/drift.py`)**:
   - Built `CUSUMTracker` tracking sequential error deviation: $S_t = \max(0, S_{t-1} + e_t - k)$, raising alarms at $S_t \ge 5.0$, with fast-path 2-undo/30-day immediate alarm.
   - Built Population Stability Index (`compute_psi`) floored at $1\times 10^{-4}$ with 10 quantiles.
   - Built `check_family_shift` running weekly checks over top 5 feature dimensions.
   - Zero direct system clock calls (Invariant I-9).

6. **Executor Worker & SimWorld Execution (`backend/src/probation/workers/executor.py`)**:
   - Implemented `Executor` strictly under `Role.EXECUTOR` (Invariant I-2).
   - Built 10-minute hold queue for irreversible and hold actions, advancing deterministically with clock.
   - Re-verified licences at execution time, falling back to `SUGGEST` if revoked.
   - Executed mutations on `SimWorld` for mail and calendar.
   - Implemented undo handling, emitting strong negative feedback outcomes to evidence.

7. **Replay Engine & Scheduler Integration (`replay.py`, `scheduler.py`)**:
   - Integrated dynamic gate dispatch, daily licence review events, weekly drift checks, and executor queue flushing into `ReplayTimeline`.

---

## Files Changed / Created
- `backend/src/probation/config.py` (updated: audit seed)
- `backend/src/probation/engine/__init__.py` (updated: exported caps, gate, licence, drift)
- `backend/src/probation/engine/caps.py` (updated: catalog, loss matrix, conditional caps)
- `backend/src/probation/engine/drift.py` (updated: CUSUM tracker, PSI, shift check)
- `backend/src/probation/engine/evidence.py` (updated: aggregation, filtering, pooling)
- `backend/src/probation/engine/gate.py` (updated: pure decide_gate, audit draw)
- `backend/src/probation/engine/handsoff.py` (updated: dangerous & double extensions, Unicode RLO)
- `backend/src/probation/engine/licence.py` (updated: ladder derivation, cache, exam check)
- `backend/src/probation/engine/replay.py` (updated: licence reviews, drift checks, gate dispatch)
- `backend/src/probation/packs/base.py` (updated: runtime_checkable protocol)
- `backend/src/probation/workers/__init__.py` (updated: exported Executor)
- `backend/src/probation/workers/executor.py` (updated: queue, simworld execution, undo)
- `backend/src/probation/workers/scheduler.py` (updated: nightly review, weekly shifts)
- `build_history/index.md` (updated: Phase 5 entries)
- `build_history/phase_05_evidence_licences_gate_drift/feature_caps_handsoff_pure_gate.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/feature_evidence_pooling_and_licence_ladder.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/feature_executor_worker_and_simworld.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/feature_statistical_drift_cusum_psi.md` (new)
- `build_history/phase_05_evidence_licences_gate_drift/phase_05_summary.md` (new)
- `backend/tests/unit/test_caps_and_handsoff.py` (new: T-CAPS, T-HANDSOFF)
- `backend/tests/unit/test_gate_pure.py` (new: T-GATE Golden Table 3.2)
- `backend/tests/unit/test_drift_cusum_psi.py` (new: T-CUSUM, T-PSI)
- `backend/tests/unit/test_evidence_aggregation_and_licence.py` (new: T-EVIDENCE)
- `backend/tests/unit/test_executor_simworld.py` (new: T-EXEC)
- `docs/reports/phase-5.md` (new: handoff report)

---

## Tests
`.\make.cmd check`:
- `ruff check backend`: Passed (0 errors).
- `ruff format --check backend`: Passed (126 files clean).
- `mypy`: Passed (0 errors across 92 source files in strict mode).
- `pytest`: 114 passed in 45.43s.

Acceptance Tests Passing:
- `T-CAPS`: Base caps, loss matrix, and context condition caps combinable by min.
- `T-HANDSOFF`: Extension blocking, double extensions, Unicode RLO, VIP/external demotions.
- `T-GATE`: All 14 rows of CONTRACT Table 3.2 Golden Gate decisions tested and matching.
- `T-EVIDENCE`: Beta counts, auto-action filtering (I-12), undo exclusion, weak evidence constraints.
- `T-CUSUM`: Sequential error accumulation, $S_t \ge 5.0$ alarm, fast-path 2-undo alarm.
- `T-PSI`: Flooring at $10^{-4}$, 10 quantiles, sensitive to feature shifts $> 0.25$.
- `T-EXEC`: Role.EXECUTOR gating, 10-minute hold queue, SimWorld email & calendar mutations, undo handling.

---

## Invariants Touched
- `I-2` (Only the Executor acts): Maintained. All mutations in `SimWorld` are dispatched solely via `Executor` requiring `Role.EXECUTOR`.
- `I-3` (Fail closed): Maintained. Precedence order in gate fails closed to `ASK` or `SUGGEST` on anomaly, drift, missing licence, or economic bar.
- `I-6` (No peeking): Maintained. Replay timeline and history view strictly restrict queries to `known_at <= as_of`.
- `I-7` (Tamper-evident ledger): Maintained. All proposals, gate decisions, executions, and undos append to the cryptographic ledger.
- `I-9` (Clock): Maintained. Zero direct calls to `datetime.now()` or `time.time()` in `core/` or `engine/`. Replay timestamps injected everywhere.
- `I-10` (Caps are hard-coded): Maintained. Action catalog caps and loss matrices are immutable code constants, never overridden by model weights.
- `I-11` (Derived licences): Maintained. Licences are derived purely from aggregated evidence on demand; never stored as independent ground truth.
- `I-12` (Independent evidence): Maintained. Automatic executions without human validation are excluded from Beta evidence updates.
- `I-13` (Audit holdouts): Maintained. 10% deterministic audit draws demote Level $\ge 2$ actions to `ASK` and tag them for evaluation.
- `I-20` (Non-recallable actions capped at Level 2): Maintained. Actions marked `recallable=False` cannot attain Level 3 (`EXECUTE_SILENT`).

---

## Deviations and Assumptions
None. All components were built in strict compliance with `CONTRACT.md` and `ENGINE_SPEC.md`.

---

## Contract Change Requests
None.

---

## New Dependencies
None.

---

## LLM Cost Incurred
$0.00 (0 calls). All Phase 5 components are deterministic code and statistical computations.

---

## Open Questions
None.

---

## Suggested Next Step
Proceed to **Phase 6: Files Pack** (`docs/PACKS_SPEC.md` Section 3, `docs/ENGINE_SPEC.md` Sections 4 and 8.2, `docs/IMPLEMENTATION_PLAN.md`).
