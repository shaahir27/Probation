# WP4 parallel implementation checkpoint

Status: **independent components implemented; WP4 NOT COMPLETE and NOT READY TO MERGE**.

Branch `phase-4-wp4-policy-calibration`, base `a5610a082e35ff99fb4c60aecdcb2e945cf55fc8`. Worktree `data/wp4/worktree` relative to the main checkout. See [execution/integration record](../WP4_IMPLEMENTATION_PLAN.md).

## Requirement-by-requirement disposition

| Source task | Implemented component / evidence | Remaining acceptance |
|---|---|---|
| 8.1 Cold start | Policy and Settings default 200, independent of L1; two effective classes; failed refit clears state. Boundary tests 199/200 | Final WP3 gate must distinguish valid cold start from failed featurization |
| 8.2 Eligible history | `HistoryView.get_training_records`, immutable legacy event projection, typed cohort metadata/exclusion counts, canonical family catalog and bounded known times. Corrections do not overwrite prior knowledge | Modern D2 adapter and genuine actor attribution at integration; do not assume the upstream world-write provenance question is solved |
| 8.3 Chronological calibration | Six time-group blocks yielding five expanding validation blocks, delayed-label purge, prefix-only encoders/vocabularies, missing-class counts and explicit T=1 reasons | Final WP3 feature semantic compatibility |
| 8.4 Final fitting | Specified solver/weights, final fit after calibration, finite probability checks, stable order and input preservation | Forward all effective settings through final orchestration |
| 8.5 File targets | Top 15/five-example minimum, deterministic ties, case preservation, OTHER -> ABSTAIN, prefix-learned 50 document-frequency tokens | Fit/predict raw-token input binding and end-to-end proposal gating |
| 8.6 Alignment/version | One encoder name/value layout, full coefficients/intercepts/vocabularies/scaler/T/provenance/config/dependency/cohort hash. Exact float JSON prevents sub-micro coefficient changes being lost to ledger JSON rounding | Final upstream provenance handshake |
| 8.7 Local embeddings | Manifest/hash/path-verified explicit offline MiniLM loader and CPU flags; strict output shape; fake-runtime test proves flags, not real support | **No actual model artifacts/manifest supplied; real smoke NOT RUN. No TF-IDF fallback** |
| 8.8 Novelty | Injected embeddings, chunked distances, strict >, self-ID-only LOO exclusion, duplicate equality, cold/zero/nonfinite/family/shape behavior and failed-state reset | Provider injection, required-failure routing and real embedding smoke |
| 8.9 History performance | Sender/file/calendar helpers; no nested calendar situation search or future snapshot RSVP; existing thread helper retained; additive time index; measured synthetic file-query parity/scaling | Wire helpers into final clue adapters, finish all-family/thread parity and scaling; one file benchmark does not certify every clue |
| 8.10 Explanations | Actual aligned coefficients, intercept, signed binary margin/class-logit labels, bounded selection helper and unavailable state | Attach genuine historical examples and explanations through final WP3 DTO/persistence path |
| 8.11 Reporting | Strong-cohort agreement including/excluding abstentions, coverage, separate weak/unresolved/ineligible counts, would_ask independent of resolution, nullable rates, matched baseline counts, filters and safe CLI formatting | Full UI/task-period acceptance under WP9; preserve distinct baseline coverage |

## Verification evidence

- New regression tests were collected against the original code first and failed because the required validation/unavailable interfaces did not exist.
- Initial targeted policy/novelty tests: 12 passed. Expanded component plus existing policy/novelty/files tests: 25 passed; later expanded run: 29 passed.
- New component suite after calendar helper addition: 20 passed. It includes 50 seeded bounded-cohort/model-digest future mutations and an offline fake-runtime artifact validation test.
- Original licensed 50-cut no-peeking assertion was retained. The tiny harness now explicitly overrides the production cold-start threshold and injects deterministic nonzero embeddings, so it actually fits a policy without real model downloads. The targeted temporal run passed 7 tests, including that full property test. Production Settings remain 200.
- Full isolated checks initially exposed two unused baseline call-arg ignores; only those comments were removed. No resolver runtime behavior was changed. Both normal and strict core/engine typing subsequently passed.
- A full isolated run before the explicit tiny-harness update passed 424 tests and failed the one nonvacuous licensed no-peeking assertion. That result is superseded only by the final result appended below, not silently reported as green.
- Windows global pytest temp permissions were avoided using the repository runner's contained workspace-local `--basetemp`. No tests were skipped to avoid the problem.
- Synthetic fixtures/results stayed unchanged in the isolated filesystem-purity checks. No live provider request, model download or real embedding smoke was performed.
- Graphify AST update succeeded using a process-local Git excludes-file override after the inaccessible external global ignore file blocked the first attempt. Synthetic placeholder PDF/SQL-extractor warnings do not establish code verification; no dependency was installed to silence them.

## Measured query evidence and limits

[Recorded file-query benchmark](wp4-query-scaling-2026-10-23.json) contains actual 250/1,000/4,000-item runs, query plans and independent scan parity. Each performs one aggregate query; timings are hardware/run-specific. Query-plan inspection exposed repeated CTE execution in an intermediate implementation; bounded materialization removed it. This is not proof of constant-time historical projection or a universal runtime SLA. Calendar/mail/thread scaling still needs integrated measurement.

## Remaining gates and rollback

1. Final verified WP3 must be available on main before replay/prediction/result integration. Main was still the WP2 baseline during this checkpoint.
2. Receive approved preprovisioned MiniLM artifacts and a complete SHA-256 manifest outside the artifact directory. Run actual offline CPU inference and record model/runtime/artifact identity. Fake vectors are not substitute evidence.
3. Complete pending rows in the requirement table, then run the integrated suite and a no-peeking scenario with real shared WP3 status/provenance semantics.
4. Preserve WP2's explicit unresolved Executor-world attribution issue; do not train live authority from incorrectly attributed system effects.

No branch was merged or pushed. No implementation commit is asserted by this report. Reviewable changes are in the isolated worktree. The primary WP3 branch and its uncommitted files were not edited by this work. To abandon this work, preserve/review its diff before removing the worktree; do not delete branches or use force cleanup. The schema rollback is dropping only `idx_ledger_kind_time` via an unbound bootstrap connection; no data migration or ledger rewriting is needed.

## Final check results

- Interpreter: `C:\Users\shaah\miniconda3\python.exe`.
- `python scripts/check.py`: exit 0; **426 passed**, two Typer/Click deprecation warnings. Ruff lint/format, normal application typing and strict core/engine typing passed. Source and isolated snapshot fixture/result hashes were unchanged.
- Final focused command: `python -m pytest backend/tests/unit/test_wp4_policy.py backend/tests/unit/test_wp4_novelty.py backend/tests/unit/test_wp4_history_report.py backend/tests/unit/test_wp4_local_embeddings.py --basetemp data/wp4-components-v2 -q --disable-warnings --tb=short`: **20 passed**. This followed the final cohort-provenance metadata and local output-shape refinements; those focused results supplement the full-run snapshot rather than pretending the snapshot was atomic with concurrent editing.
- Final `python -m mypy --strict --config-file backend/pyproject.toml backend/src/probation/core backend/src/probation/engine`: exit 0, 32 source files. Only unused configuration-section notes remain; no type suppression was added.
- `git diff --check`: exit 0.
- Last inspected main: `a5610a082e35ff99fb4c60aecdcb2e945cf55fc8`. WP3 branch had advanced to `778a2d04f378570d11538f0f9288e193d49e46f7`, a foundation commit; it was not a verified full WP3 merge into main. No W4-5 integration was attempted.
- Actual MiniLM artifact/runtime smoke: **NOT RUN**. The user has been asked for preprovisioned artifact/manifest paths. Do not replace this missing evidence with the fake runtime/vector tests.

These successful component/regression checks do not close the requirement-table integration gates or change the **WP4 NOT COMPLETE** status.

Final loader edge-case follow-up: missing paths/invalid artifact input now raise typed NoveltyUnavailable before runtime construction. The two local-loader tests passed; loader Ruff lint/format and strict typing also passed. This targeted follow-up is additional to the recorded 426-test full snapshot and the 20-test component run; no real model inference was substituted for the missing smoke.


## Model provisioning update - 23 October 2026

The owner explicitly authorized downloading the local embedding model and keeping all model files/caches inside this project. This supersedes the earlier NOT RUN/missing-artifact entries for the runtime smoke only.

- Model: sentence-transformers/all-MiniLM-L6-v2; FastEmbed's registered ONNX distribution Qdrant/all-MiniLM-L6-v2-onnx, revision d13954661f83248295ba75c1ed411eef3b7b936e.
- Artifacts: root repository data/models/all-MiniLM-L6-v2/d13954661f83248295ba75c1ed411eef3b7b936e (outside the WP4 worktree but inside the same project).
- Manifest: root repository data/models/all-MiniLM-L6-v2/manifest.json. Paths and complete runtime results: paths.json and offline-smoke.json alongside it.
- Seven files, 91,334,489 bytes; upstream LFS SHA-256 or Git blob identities verified before recording per-file SHA-256.
- Real offline smoke PASSED: shape 4 x 384, finite L2-normalized vectors, repeatable outputs, duplicate novelty false at distance/threshold zero. Synthetic near-pair cosine 0.895887 and unrelated-pair cosine -0.053667 are smoke observations, not an accuracy benchmark.
- Runtime: FastEmbed 0.9.0, ONNX Runtime 1.31.0, NumPy 2.5.2. No dependency was installed. CPU load approximately 1.076 seconds, four-text inference approximately 0.015 seconds on this machine/run; no throughput guarantee.
- Socket connections were denied during the smoke; zero connection attempts occurred. Python filesystem writes were constrained to the project and cache/temp locations were set under root data/models/.cache. A secret-read guard blocked the initial application .env lookup; it read no secret, and the successful rerun used the isolated model directory as cwd.
- Integration must preserve project-local cache/temp configuration BEFORE embedding-library imports. The download/smoke scripts under root data/models/ provide the exact environment mapping. No model-name-only automatic download/global-cache fallback is permitted.

The model-artifact smoke blocker is now cleared. WP4 remains NOT COMPLETE: verified WP3 integration, effective settings/provenance/failure routing, clue/example wiring and integrated acceptance remain open. No frontend or application source was modified for this provisioning task.

## Later integration checkpoint

WP4 components have now been ported into the Phase 3 integration branch and verified with 585 passing offline tests, real offline MiniLM and installed-wheel checks. The original WP4 worktree remains unchanged. Earlier statements about integration not having occurred describe the earlier checkpoint. Current scope, evidence and upstream W3-D03/W3-D04 blockers: [integration handoff](wp3-wp4-integration-2026-10-23.md). This is not a full WP3/P11 or main-merge sign-off.

## Final Phase 4 branch integration continuation

WP3 commit 398729e is pushed and merged into main. Original WP4 work is preserved in 24f7629; main is integrated on the Phase 4 branch with ten reviewed hunk resolutions. All eleven requirements, new regression repairs, actual offline model/shared-snapshot smoke, published artifact manifest, package and nine-case scaling evidence are recorded in [current Phase 4 handoff](phase-4.md). Earlier NOT COMPLETE statements describe their earlier checkpoints; final full-check/merge results are recorded in the current handoff. No F01-F42 or live-provider completion claim.
