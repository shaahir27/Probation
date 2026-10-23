# WP4 final integration and acceptance handoff

Branch: `phase-4-wp4-policy-calibration`; preserved foundation commit `24f7629`; incoming verified main / WP3 commit `398729e`. The owner authorized Phase 4 completion, a separate Phase 4 integration commit, and subsequent merge/push to main. No force operation, branch deletion or worktree removal is used.

## Result and scope

The eleven WP4 requirements are implemented and integrated with WP3's reader/status/provenance and shared prediction path. Final check/commit results are appended below after completion. This is WP4 acceptance, not full F01-F42 completion, live provider validation, full WP5 exams/permissions, WP6 feedback lifecycle, WP9 dashboard or WP12 connector/runtime acceptance. Reading/Chains remain unavailable without their later suppliers as explicitly approved.

The original parallel WP4 work was first preserved and checked (427 tests). Ten conflicts with main were then reviewed hunk by hunk. Main already contained the ported WP4 encoder/policy/calibration/vocabulary/report foundation; its later fixes additionally supplied current-item exam overlays, strict status filtering, project-local model caches, example scoring, corrected aggregate scans, and valid reader/no-peeking fixtures. Those improvements and the original WP4 algorithms/tests are retained. No wholesale replay/history replacement was used. The initial bulk restore attempt was rejected by automatic approval review; individual reviewed hunks were edited, checked and staged instead.

## All eleven requirements and evidence

| Source WP4 task | Implementation and integration | Verification |
|---|---|---|
| 1 Cold start | Policy/config default 200, two effective classes, independent of licence counts; failed/ineligible refits clear fitted state | test_wp4_policy.py boundary/refit cases |
| 2 Eligible training | HistoryView bounded records + immutable as-of ledger projection; strong genuine decisions, compatible reader/features, hands-off/status/action exclusions; explicit system actors excluded; ambiguous legacy corrections excluded, never reconstructed from overwritten current outcomes | test_wp4_history_report.py and test_wp4_integration_acceptance.py; 50-cut tests |
| 3 Chronological calibration | Six timestamp-group blocks, five expanding validations, labels purged by known_at, fold-local encoders/folder/token vocabularies; skipped folds/unseen labels reported; T=1 explicit unavailable/failure status | test_wp4_policy.py; purging/optimizer cases and controlled calibration manifest |
| 4 Final fitting | Temperature selected from held-out predictions before final eligible-cohort fit; occurrence decay/finite normalized probabilities; final failure unavailable | test_wp4_policy.py, shared gate encoder-failure case |
| 5 Files | Count >=5, top15 case-preserving folders, OTHER diagnostic distribution but ABSTAIN proposal; LEAVE valid, DELETE unsupported label; 50 document-frequency filename tokens learned per prefix/fold | test_wp4_policy.py; test_wp4_bounded_fit.py across 50 trained file cuts |
| 6 Encoder/hash | One ordered numeric/categorical specification; mean/missing/unknown handling; complete coefficients/intercepts/classes/scales/vocabulary/T/provenance/config/dependency/cutoff/cohort digest, 12-character public version | test_wp4_policy.py, including changes after coefficient20 and actual contribution reconstruction |
| 7 Local embeddings | Exact preprovisioned MiniLM ONNX artifacts, complete reviewed SHA256 manifest, offline CPU initialization, project-local caches/temp, runtime identity includes FastEmbed/ONNX Runtime/NumPy | real verify_embeddings.py and shared runtime smoke; test_wp4_local_embeddings.py; runtime-version identity regression |
| 8 Novelty | Family-specific eligible references, leave-one-out exact identity exclusion, chunked cosine neighbors, strict distance > threshold, duplicate zero-distance equality, unavailable/missing-vector failure and cold novelty | test_wp4_novelty.py; 50-cut fitted file novelty parity; real duplicate-vector smoke |
| 9 Historical clues/indexes | Bounded sender/reply/thread, organizer/calendar and file-origin helpers; raw known_at filter on file counts; current-item exclusion; immutable decision projection; additive idx_ledger_kind_time | nine measured query cases with independent scan parity; correction/timezone/no-future-status tests |
| 10 Explanations | Aligned standardized contributions/intercept with signed binary margin or class-logit labels; up to3 actual bounded similar eligible examples; same redacted context for novelty and example scoring | policy explanation reconstruction; 50-cut explanation equality; integrated replay tests |
| 11 Honest reports | Strong resolved all-item/nonabstained agreement and coverage with distinct counts; weak/unresolved/ineligible separate; ASK/ABSTAIN count independent of resolution; nullable zero rates; matched baseline/missing coverage; scoped task/action/time | hand-count tests in test_wp4_history_report.py; integrated CLI/report consumer tests |

## Final integration fixes

Five new red regressions proved real gaps before repairs: future-known raw file records inflated origin counts; explicit Executor/system actions could enter the legacy user projection; required-reader training rows could lack reader fields; novelty consumed unbounded/raw rather than a stable redacted context; embedding identity omitted ONNX Runtime. All five are fixed with dedicated tests. A real fitted-encoder failure is now caught by the shared gate and yields ABSTAIN/ASK rather than an uncaught exception.

`llm/feature_pipeline.py` prepares hidden `__novelty_text` at the role boundary: max4000 redacted characters, or filename tokens + origin + extension for files. Pure policy inputs exclude it and all status metadata. Shared prediction, bounded training references and similarity selection consume the same context. Semantic provenance changes to history-v2 / redacted-context-v1, so incompatible stored features cannot be silently reused. Existing historical ledger bytes and proposal IDs are not rewritten.

Strict typing now imports RedactionResult and LLMValidationError from their defining modules rather than relying on implicit re-exports. No type ignore or test weakening was introduced. The file-cut test checks case-preserving full action labels ranked by actual prefix counts; it does not assume display folder names or equal counts.

## Real offline model and setup evidence

- Model identity: sentence-transformers/all-MiniLM-L6-v2; reviewed Qdrant ONNX distribution at d13954661f83248295ba75c1ed411eef3b7b936e; seven artifacts, 91,334,489 bytes, under root project data/models. Weights/caches are not committed.
- `config/embeddings/all-MiniLM-L6-v2.manifest.json` publishes only reviewed relative artifact paths and SHA256 hashes plus model/distribution/revision. README describes explicit provisioning, manifest trust, worktree path overrides and readiness. No automatic download or global-cache fallback.
- `python -B scripts/verify_embeddings.py --model-dir <approved project model directory> --manifest config/embeddings/all-MiniLM-L6-v2.manifest.json`: actual 2x384 finite, normalized, repeatable vectors; duplicate novelty false at distance0; zero Python socket attempts. Published-manifest provider identity: e7874ae8decaf9bd21b3b36df6eb1cf6556be6dcb89b5e805ab7221840ef1ac6.
- Actual shared prediction/exam snapshot smoke using the Phase 4 source and the real ONNX session: fitted 200-row controlled policy, chronological calibration status calibrated, level0 SHADOW, required-reader failure ASK, frozen snapshot retains read-only runtime capability without trying to pickle it. Zero socket attempts. This is mechanism/compatibility evidence, not policy accuracy, provider inference or prospective permission.
- Local evidence: data/wp4/shared-smoke.log, data/wp4/policy-calibration-manifest.json and data/models/all-MiniLM-L6-v2/{offline-smoke-wp4-final,wp4-final-prediction-smoke}.json. Controlled manifest records actual fold ranges/indices, usable counts, temperature, cohort/policy digests, encoder and embedding identity. Real replay also exposes per-retrain training_manifest with eligible/excluded counts and actual semantic provenance.

## Query scaling and package evidence

[Final query records](wp3-wp4-query-scaling-2026-10-23.json): 250/1000/4000 situations per family, actual traced SQL/query plans and returned rows, parity with an independent scan in all9 cases. Query counts remain file1/mail1/calendar3. At4000, measured times were approximately .0142s/.0144s/.0917s on this machine. No hardware-independent performance or accuracy promise.

Final wheel built from the Phase 4 worktree and installed without dependencies/network outside the checkout. SHA256: `0ab0d5fb38b5f4b43aa8b9494fd2c0f25ff95da0cc46abc88bce24d2556d2acf`; local data/wp4/package and data/wp4/installed. Installed smoke loads15 prompts,32 schema tables, the actual shared adapters and cold-start200. Prompt/model assets are not silently replaced by a generic fallback.

## Safety and downstream obligations

No production dependency, destination, live account, secret access, provider call, Tavily spending, fixture regeneration, UI implementation or CONTRACT amendment. Source/test result hashes are protected by the isolated checker. All engine policy/evidence/licence imports remain free of web. Web restrictions cannot change learned probabilities or raise autonomy.

The only WP4 schema addition is idx_ledger_kind_time, installed through existing reviewed bootstrap index migration; bootstrap rollback drops that index without changing ledger bytes. WP3 accounting migration/role grants remain intact and have their separate rollback/audit requirements in phase-3.md. Do not drop accounting or reset its audit to make a fresh spend allowance.

Conservative legacy projection excludes ambiguous corrections and unknown provenance rather than inventing decisions. Modern event ingestion/migrations, prospective evidence qualification, live supervisor/recovery, provider compatibility, connection consent and public presentation remain their owning work packages. A passing model smoke is not earned permission. No guaranteed accuracy improvement, promotion date or full-product completion is asserted.

---

## Historical Phase 4 report (superseded implementation/results)

> WP4 integration in progress on `phase-4-wp4-policy-calibration`, after merging verified Phase 3 (`398729e`). See [WP4 checkpoint](wp4-checkpoint-2026-10-23.md) and [earlier integrated component evidence](wp3-wp4-integration-2026-10-23.md). The historical report below is preserved; its 20-row/in-sample calibration claims are superseded. Final acceptance is recorded separately below after verification.

# Phase 4 Handoff: Engine Core and Backtest

**Branch:** `phase-4-engine-core-backtest`  
**Phase:** 4 — Engine Core and Backtest  
**Lane:** Lane A (Member 1)  

---

## Done
1. **Empirical Bayes Beta Lower Bound (`backend/src/probation/engine/evidence.py`)**:
   - Implemented exact pooled lower-bound formula:
     $$\alpha_0 = \max(1.0, \kappa \cdot p), \quad \beta_0 = \max(1.0, \kappa \cdot (1 - p))$$
     $$\text{LB} = \text{Beta.ppf}(q, \alpha_0 + k, \beta_0 + (n - k))$$
   - Verified 100% agreement with all 10 Golden Numbers from `ENGINE_SPEC.md` Section 16 (`T-LB`).
2. **Feature Standardization & Canonical Hash (`backend/src/probation/engine/features.py`)**:
   - Built `FeatureEncoder` with one-hot encoding for categoricals, zero-variance safe `StandardScaler` for numerics, and deterministic lexicographic column sorting.
   - Built `compute_features_hash` computing canonical SHA-256 hash across deterministic clues, reader fields, and featurizer version.
3. **Calibrated Policy Model (`backend/src/probation/engine/policy.py`)**:
   - Multinomial Logistic Regression (`solver="lbfgs"`, `C=1.0`, `max_iter=1000`).
   - Exponential time-decay sample weighting: $0.5^{\text{age} / \text{half\_life}}$.
   - Cold start guard: emits `action="ABSTAIN"` with reason `cold_start` when training rows $< 20$ or distinct actions $< 2$.
   - Temperature scaling calibration: bounded scalar optimization ($T \in [0.5, 5.0]$) when rows $\ge 100$.
4. **K-NN Novelty Anomaly Detection (`backend/src/probation/engine/novelty.py`)**:
   - Computed mean cosine distance to $K = 10$ nearest training situations.
   - Fit dynamic threshold $\theta$ using leave-one-out percentile thresholding.
5. **Event-Sourced Replay Engine (`backend/src/probation/engine/replay.py`)**:
   - Merged chronological timeline processing `OUTCOME_KNOWN` (priority 0), `LICENCE_REVIEW` (priority 1), `RETRAIN` (priority 2), and `SITUATION` (priority 3).
   - Strict no-peeking invariant (Invariant I-6): data with `known_at > t` is never read before $t$.
   - Monotonic clock advancement using `Clock(mode=ClockMode.REPLAY)` (Invariant I-9).
   - Emits immutable proposals with `gate = GateDecision.SHADOW` (Phase 4).
   - Appends all proposals to the hash-chained tamper-evident ledger (Invariant I-7).
6. **Outcome Resolver Worker (`backend/src/probation/workers/resolver.py`)**:
   - Resolved outcomes from `SimWorld` under `Role.RESOLVER`.
   - Appended outcome events to the hash-chained ledger and populated SQLite `outcomes` table.
7. **Baselines & Report Card (`backend/src/probation/engine/baselines.py`, `report.py`)**:
   - Implemented B0 (majority class), B1 (always ask), and B2 (generic heuristic rules).
   - Generated report card evaluating `same`, `different`, `would_ask`, and `censored` items against strong observed outcomes.
8. **CLI Subcommand `probation backtest` (`backend/src/probation/cli.py`)**:
   - Wired `backtest --family <family> --until <until>` rendering rich report card tables.

---

## Files Changed / Created
- `backend/src/probation/engine/evidence.py` (updated)
- `backend/src/probation/engine/features.py` (updated)
- `backend/src/probation/engine/policy.py` (updated)
- `backend/src/probation/engine/novelty.py` (updated)
- `backend/src/probation/engine/replay.py` (updated)
- `backend/src/probation/engine/report.py` (updated)
- `backend/src/probation/engine/baselines.py` (new)
- `backend/src/probation/workers/resolver.py` (updated)
- `backend/src/probation/cli.py` (updated)
- `backend/src/probation/config.py` (updated)
- `backend/tests/unit/test_engine_evidence_lb.py` (new)
- `backend/tests/unit/test_engine_policy.py` (new)
- `backend/tests/unit/test_engine_novelty.py` (new)
- `backend/tests/property/test_no_peeking.py` (new)
- `backend/tests/integration/test_backtest_e2e.py` (new)
- `build_history/phase_04_engine_core_backtest/phase_04_summary.md` (new)
- `build_history/phase_04_engine_core_backtest/feature_replay_engine.md` (new)
- `build_history/phase_04_engine_core_backtest/feature_policy_novelty_lb.md` (new)
- `build_history/index.md` (updated)

---

## Test Results
`.\make.cmd check`:
- `ruff check backend`: Passed (0 errors).
- `ruff format --check backend`: Passed (121 files clean).
- `mypy`: Passed (0 errors across 92 source files in strict mode).
- `pytest`: 87 passed in 22.37s.

Key test breakdown:
- `T-LB`: All 10 golden numbers verified within exact tolerances.
- `T-POLICY`: Cold start returns `ABSTAIN`, time-decay sample weighting verified, temperature scaling $T \in [0.5, 5.0]$.
- `T-NOVELTY`: Cosine distance separation between in-distribution and far synthetic anomalies.
- `T-NOPEEK`: Zero peeking differences across 50 random cuts on `tiny_synth`.
- `T-E2E`: Full replay, ledger verification (`is_intact == True`), exact 1:1 proposal-to-situation ratio, and cryptographic head hash determinism.

---

## Baseline B0 Note on Synthetic Data
On the student persona (`Meena`, persona 0 in `tiny_synth`), approximately 93.8% of historical emails are `ARCHIVE` due to the prevalence of service notifications and newsletters. The naive unpersonalized majority-class baseline B0 achieves 93.81% by predicting `ARCHIVE` for every situation, but possesses 0% personalization and fails on human-specific replies. Probation's calibrated policy accurately identifies minority classes (`REPLY`, `TRASH`) and abstains during cold-start. On diverse balanced personas and full evaluation datasets, Probation's agreement exceeds B0 per `EVALUATION_PLAN.md` Section 4.

---

## Next Phase
Ready for **Phase 5: Evidence, Licences, Gate, and Drift** (`docs/ENGINE_SPEC.md` Sections 6-11):
- Licence ladder level derivation (Level 0 $\to$ Level 1 $\to$ Level 2 $\to$ Level 3).
- Full deterministic gate function dispatch (`SHADOW`, `SUGGEST`, `ASK`, `HOLD_THEN_EXECUTE`, `EXECUTE_UNDO`, `EXECUTE_SILENT`).
- CUSUM error tracking and PSI family shift alarm triggering.
- Audit holdout draws (10% sampling at Level $\ge 2$).

## Final WP4 acceptance result

`C:/Users/shaah/miniconda3/python.exe -B scripts/check.py` exited0 on the integrated Phase4 source: **629 passed**, two pre-existing Typer/Click deprecation warnings, 106.85 seconds. Ruff lint/format passed; application typing166 files and strict core/engine34 files passed. Source and isolated snapshot fixture/result hashes unchanged (`data/wp4/worktree/data/checks/run-9emzuwsm`). Separate Ruff checks cover verify_embeddings.py and wp4_benchmark.py.

The additional trained-file property test passed all50 seeded cuts with actual fitted policies, held-out calibration, fold/prefix vocabulary, novelty thresholds/scores and aligned explanations; the existing50-cut mail/cohort and full replay properties also pass. The new required-reader, system-actor, future-observation, bounded-context, runtime-identity, invalid-encoder gate and missing-setup cases pass.

Actual model/shared snapshot, published-manifest verification, nine-case query parity, installed-wheel assets/schema, final Graphify AST update and diff checks all pass. No applicable WP4 blocker remains. **WP4 is complete within its defined offline policy/calibration/novelty/history/explanation/report scope.** Downstream live-provider/connector/permission/feedback/UI/release obligations above remain open; passing this checkpoint does not close those phases. Final Git/remote identifiers are supplied in the completion message and history.
