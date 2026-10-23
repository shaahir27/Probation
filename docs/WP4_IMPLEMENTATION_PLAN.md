# WP4 execution record and acceptance

Approved scope: policy, chronological calibration, local-embedding novelty, bounded history, explanations and honest report cohorts. This records implementation of the user's approved four-section plan; it does not replace CONTRACT or the source WP4 requirements in CHANGES_IMPLEMENTATION_PLAN section 8.

Branch: `phase-4-wp4-policy-calibration`. Worktree: `data/wp4/worktree` relative to the primary repository. Base: `a5610a082e35ff99fb4c60aecdcb2e945cf55fc8`. Active WP3 files were not copied into this branch or overwritten.

## Ownership and sequence

1. W4-0: isolated branch and committed WP2 baseline, synthetic-only work, no credentials or provider calls.
2. W4-1: encoder, canonical family labels, file folder/token vocabulary, explicit 200-row defaults, immutable historical training records.
3. W4-2: purged five-block expanding calibration, exact decay weights, final fitting, full-precision complete model digest and component explanations.
4. W4-3: injected bounded-memory novelty and explicit offline MiniLM artifact loader. Fake embeddings test math only; real runtime and shared snapshot acceptance now passed (see reports/phase-4.md).
5. W4-4: bounded sender/file/calendar statistics, additive event-time index, synthetic scaling benchmark, explicit report denominators and nullable CLI presentation. Pack clue and explanation call sites are now integrated; final nine-case parity/plan evidence is in reports/phase-4.md.
6. W4-5: implemented on this branch after verified WP3 commit 398729e reached main. Ten conflicts were resolved per hunk, retaining both WP4 algorithms and WP3 boundaries; no wholesale replay/history replacement.
7. W4-6: real offline MiniLM, installed wheel, query/explanation wiring and 50 trained file/calibration/novelty/explanation cuts pass. Final full check and branch merge evidence is recorded in reports/phase-4.md.

## Integration contract for the WP3/WP4 owners

- Preserve `Policy.fit` and `Policy.predict`; extended fit keywords are `known_at`, `situation_ids`, `provenance`. Prefer `build_cohort(history, family, semantic_version)` and `fit_cohort(policy, cohort, as_of)` over replay's old direct SQL training query.
- Pass effective `cold_start_min_situations`, `train_half_life_days` and `files_topk_folders` explicitly. Defaults are 200, 90 and 15; no licence-evidence threshold is used as cold-start count.
- Supply filename `name_tokens` derived through the bounded current-item adapter at both fit and predict. The policy removes old fixed `tok_*` fields and generates only the current fitted vocabulary. Missing name-token wiring is not complete file acceptance.
- Supply genuine validated feature provenance. The compatibility fit method defaults known time to supplied timestamps only for existing callers; production training must use cohort metadata and actual known time.
- Inject a verified `LocalMiniLM` provider into each family novelty detector; no global model download or TF-IDF fallback. Propagate `NoveltyUnavailable` to WP3's failure result/gate inputs, never a fake successful novelty score. Small cold cohorts remain explicitly cold/novel.
- Use the same fitted policy/encoder/vocabulary/novelty snapshot in replay, live adapters and nonpersisting counterfactuals. WP4 did not edit replay, workers or WP3 shared result types during parallel development.
- `Policy.explain` supplies real unscaled signed-binary-margin or class-logit contributions. `historical_examples` selects up to three eligible caller-bounded examples from real supplied similarity scores; attach examples/provenance through the final WP3 result contract, never invented explanations.
- Replace legacy pack scans with the new historical aggregate helpers only after parity, timezone, thread and provenance tests on the integrated code. Calendar conflict helper ignores final `my_status` and uses known immutable RSVP decisions.
- Current legacy projection deliberately excludes ambiguous/conflicting/correction histories. Modern D2 event storage requires its reviewed adapter; do not silently guess links or rewrite outcomes/ledger. WP2's un-attributed Executor-world changes remain an upstream provenance risk for real execution, not a defect this branch claims to repair.
- Preserve report keys with valid meanings; new rates are nullable and carry explicit counts. CLI handles unavailable/mismatched baselines. Complete dashboard/API task-period integration remains a later acceptance dependency.

## Safety, migration and completion

No dependency or model artifact was installed, no live request was made, no fixture regenerated, and no CONTRACT change was made. The only schema addition is `idx_ledger_kind_time` on existing ledger columns, adopted after query-plan inspection. Existing bootstrap index migration reads it from schema.sql, requires an unbound clean connection and preserves ledger bytes. A bootstrap-only rollback can drop this index; it must not alter ledger rows or remove WP1 objects.

Merge only after the final full-check evidence in reports/phase-4.md is accepted. This completes WP4 only; it does not establish full-product or live-provider release acceptance.

## Final acceptance

W4-0 through W4-6 complete: integrated branch check629 passed, strict typing/lint/format and protected hashes pass; actual offline MiniLM/shared snapshot, packaged assets, nine query benchmarks and trained file50-cut properties pass. Detailed eleven-requirement mapping and downstream limits: [Phase4 handoff](reports/phase-4.md). Git publication follows the owner-approved merge sequence.
