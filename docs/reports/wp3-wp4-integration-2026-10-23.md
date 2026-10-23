# WP3 P06-P11 and WP4 integration handoff

> Later continuation: the owner approved W3-D03/CCR-002 on 23 October 2026; durable accounting is now being verified. See [current Phase 3 handoff](phase-3.md). The earlier blocker and branch-state statements below describe the original checkpoint, not the later merge result.


23 October 2026. Branch: `phase-3-wp3-reader-pipeline`. Starting observed HEAD: `5460951`. Status: **implementation integrated in this branch; offline acceptance verified; full WP3 closure remains blocked by the pre-existing P04/P05 accounting approval**. No main-branch merge, push, deployment or paid provider run is claimed.

## Done

The owner stopped the other P06/P07 agent and authorized this agent to take over those packages and integrate WP4. Existing dirty planning-document relocation was preserved. WP4's uncommitted component work was integrated with a three-way comparison against `a5610a0`; backups and hashes are under local `data/wp3-wp4-integration-before/`. The one substantive shared-history conflict retained both the WP3 current-item counterfactual override and WP4 bounded training/statistics queries. Other apparent conflicts were line-ending differences. The original WP4 worktree was not deleted or overwritten.

| Package | Implemented behavior | Completion boundary |
|---|---|---|
| P06 | Strict registered reader service; explicit missing/invalid/optional-disabled states; current-source access; redacted header context; real header/reader conflict; validated deterministic values; shared semantic feature version and operational-independent feature hash. | Missing asset/model/reader fails closed. No real provider accuracy or account access is asserted. |
| P07 | Pure shared prediction/gate seam, bounded feature composition, current/live-tick adapter and frozen exam adapter. Replay uses actual status flags. Counterfactuals recompute current-item clues and reader fields with the same pipeline. No `.99` exam fallback. Missing snapshot cannot pass. | Always-on supervisor/connection polling remains WP12. Full WP5 exam coverage and licence/evidence lifecycle remain their own acceptance. |
| P08 | Registered reply writer, up to three conservatively linked owner examples, request-scoped person restoration, local validation before/after restoration, one bounded regeneration, actual status/provenance and non-autonomous needs-user-input state. | Historical Sent without proven user actor/linkage is excluded, so style may truthfully be unavailable. Style quality is not empirically certified. |
| P09 | Exam edits/alias, wording, synthetic text jobs, quarantined stored-page jobs and digest use registered bounded/redacted capabilities. Obsolete `complete_json` and literal fallback models were removed. B3 without actual validated predictions is explicitly not run. Operator smoke uses the registry and requires explicit opt-in. | B3's actual ten-example benchmark is WP10. Full official-domain provenance, Search/Extract budgets and Radar/Reading workflows are WP7. Synthetic generation fixtures were not regenerated. |
| P10 | Generated draft/proposal unit of work, immutable retry-presence checks, exact edited-body payload hashing, protected local provenance, and Executor hydration of the stored validated original-sender-only body. | No edited-response schema/API/frontend lifecycle was silently added. Full editing/approval/reconciliation and real send acceptance remain WP6/WP9/WP12. |
| P11 | Isolated checks and protected hashes; installed-wheel prompt/schema smoke; real offline MiniLM/shared-prediction/frozen-ONNX smoke; source/job inventory and handoff. | **Full closure is blocked by W3-D03/W3-D04 and later explicitly authorized provider validation.** A green offline suite is not durable multi-worker accounting evidence. |

### WP4 requirement coverage after integration

| Source task | Integrated implementation/evidence |
|---|---|
| 8.1 | Production cold start 200, independent of licence counts; two effective classes; explicit test override only. |
| 8.2 | Replay retraining consumes `HistoryView` cohorts, immutable legacy event projection and strict reader/deterministic/budget status. Ambiguous corrections and unsupported labels are excluded with reasons. Live actor/event provenance remains a downstream blocker, not guessed user behavior. |
| 8.3-8.4 | Chronological calibration with fold-local encoders/vocabularies and delayed-known purging; labelled T=1 fallbacks; final fit only afterward; failed refits clear stale state. |
| 8.5 | Top-15 eligible file folders with five-example floor, case preservation, OTHER abstention and fold-local filename tokens. Prediction and explanation use the same fitted token mapping. |
| 8.6 | Full fitted-state/version digest, ordered columns, statistics, classes, coefficients/intercepts, temperature, semantic provenance and configuration. |
| 8.7 | Verified local MiniLM provider is injectable into replay; explicit local paths, offline loading and project-local cache/temp setup before runtime import. Real ONNX smoke passed. |
| 8.8 | Strict novelty comparison, duplicate/self identity rules, invalid-vector failures, bounded-memory neighbors and family-specific references. |
| 8.9 | Actual mail/calendar/file clue consumers use bounded aggregate helpers. Calendar final-state RSVP is not historical truth. Nine measured scaling/parity cases cover 250/1,000/4,000 situations. |
| 8.10 | Actual aligned coefficient explanations and bounded eligible similar examples attached to proposals. Unsupported owner-style examples remain absent. Logits are not presented as probability or causal contributions. |
| 8.11 | Report scopes, explicit numerators/denominators, abstention coverage, nullable empty rates and matched baseline coverage. No global trust score or fabricated missing baseline result. |

Runtime retraining reports include `training_manifest`: cutoff/family, eligible/excluded counts, policy/cohort digests, calibration status/folds, temperature and novelty/provider readiness. Historical proposals/ledger bytes are not rewritten to retrofit a new reader version. Start a separate fresh run for incompatible semantic changes; stale stored features cannot silently authorize a new proposal.

## Files changed and interfaces

- `llm/reader.py`, `feature_pipeline.py`, `consumers.py`: typed required-reader and registered-job composition, shared semantic version, cached-only operation without a credential/client constructor.
- `workers/brain.py`, `workers/prediction.py`, `engine/prediction.py`, `engine/exam_prediction.py`, `engine/replay.py`: event-time extraction, pure gate, role-level current adapter and counterfactual composition. Frozen exam state copies fitted arrays/model while sharing the read-only ONNX runtime capability.
- `llm/writer.py`, `reply_examples.py`, `draft_validation.py`, `draft_persistence.py`: writer, conservative user-linked examples, local validation/restoration, immutable reviewed operation binding and draft preparation.
- `db/proposals.py`, `db/reply_payload.py`, `workers/executor.py`: atomic persistence, retry consistency and server-owned draft hydration. No browser-supplied body becomes a send capability.
- `packs/*/__init__.py`, pack clue modules, `core/history*.py`: exact bounded current source, current-item-only counterfactual override, aggregate/history projection and training interfaces.
- `engine/{training,calibration,vocabulary,features,policy,novelty,report}.py`, `core/{file_tokens,training_labels}.py`, `local_embeddings.py`: integrated WP4 components. `config.py` forwards effective thresholds/decay/vocabulary settings and explicit embedding paths.
- `packs/{mail,calendar}/exam_ops.py`, `engine/habits.py`, `packs/radar/{digest,out_of_band}.py`, `links/extractor_jobs.py`, `synth/llm_jobs.py`, `eval/baselines.py`: migrated consumers and conservative unavailable states. A search result's rank alone cannot establish an official extraction URL; callers supply a reviewed official-domain allowlist.
- `scripts/wp4_benchmark.py`, `scripts/test_live_nebius.py`: reproducible query evidence and explicit operator-only live smoke; no paid smoke was run.
- New focused tests: `test_wp3_reader_prediction.py`, `test_wp3_writer_component.py`, `test_wp3_consumer_migration.py`, `test_wp4_*.py`; existing gate/persistence/conformance/no-peeking/exam fixtures were updated to provide valid inputs through the new interfaces while retaining their behavior assertions.

P08/P10 caller seam: `generate_reply(...) -> WriterOutcome`; `prepare_reply_persistence(proposal, situation, history, writer) -> (Proposal, DraftRecord | None)`; then `persist_proposal(...)` in one Brain unit and commit before Executor. The writer never changes the policy prediction or grants a licence. An exact explicit approval remains distinct from autonomous authority.

The current/live adapter is `predict_current(...) -> (Features, Prediction)`. It validates the decision cutoff, uses the same bounded feature computation and pure gate, and performs no proposal persistence or target effect itself. Supplying this adapter is not an always-on deployment claim.

## Tests and evidence

Interpreter: `C:/Users/shaah/miniconda3/python.exe`; all application checks execute in a secret-free isolated snapshot using `scripts/check.py`.

- Earlier WP3-only snapshot: **557 passed**; lint/format, application typing and strict core/engine typing passed; protected fixture/result bytes unchanged.
- Combined WP3/WP4 snapshot: **583 passed**, two existing Typer/Click deprecation warnings; application typing passed for 164 files and strict core/engine typing for 34 files. Source and isolated fixture/result hashes unchanged.
- Final source follow-up: missing-asset failure handling plus two current-adapter/asset regression cases. Final check result is recorded below after completion; do not substitute the earlier count for that run.
- `python scripts/wp4_benchmark.py`: nine actual cases, scan parity true for all families/sizes. See [query evidence](wp3-wp4-query-scaling-2026-10-23.json). Constant query counts: files 1, mail 1, calendar 3. At 4,000 situations the final recorded observations were approximately 0.014s / 0.014s / 0.087s on this machine; these are measurements, not universal latency promises.
- Wheel built with project-local Hatchling, installed with no dependencies/network into an isolated target; all **15 registered prompt assets** and the SQL schema loaded outside the checkout. Latest package hash/smoke metadata is retained under local `data/wp3-package/`.
- `python -B data/models/smoke_integrated.py`: actual 384-dimensional ONNX inference, normalized/repeatable outputs, strict duplicate novelty false at distance/threshold zero, zero socket attempts and Python-observed writes inside the project. The actual shared seam returned SHADOW at level 0 and ASK on required-reader failure. Freezing a snapshot with the actual ONNX runtime passed without pickling the runtime. Calibration for this deliberately same-time smoke was correctly `insufficient_time_groups`, not falsely calibrated.
- Operator smoke `--help` runs without application configuration import. The live flag was **not** run. No Nebius/Tavily API spending or private account operation occurred.
- Graphify AST update, final diff checks and final wheel metadata are recorded in the final verification note below.

Invariant coverage: I-1/I-3 strict data/failure states; I-2 target effects remain Executor-owned; I-6/I-7 bounded history and existing 50-cut chronology test; I-8 atomic append-only proposal ledger; I-9 injected clock; I-10-I-13 no writer-issued authority, fresh execution checks preserved and shared code-graded exam path; I-14 redaction/restoration; I-15/I-16 legacy budget/cache protections preserved, with durability explicitly blocked below; I-17 same prediction semantics; I-18/I-19 synthetic isolated tests; I-20 no post-send recall promise; I-21-I-26 web restrictions/quarantine and source-supported claims remain separate from learned probability/evidence.

## Deviations and assumptions

- This is code integration in the Phase 3 branch, not a claim that the old WP4 worktree's branch tip or `main` advanced. The worktree remains available and unchanged for comparison. No branch/worktree removal or force operation was performed.
- No new outcome-event/edited-response/connector/budget table or role grant was invented. The only imported schema addition is `idx_ledger_kind_time`; schema bootstrap installs it idempotently. Its rollback is dropping that index through approved administration, never rewriting ledger data.
- Legacy immutable event projection is conservative. It cannot manufacture trustworthy actor attribution from absent source metadata. Exclusions/cold start are valid outcomes; full live operation remains dependent on WP2/WP6/WP12 provenance and lifecycle work.
- Wording uses conservative semantic token preservation with approved synonyms; unsupported paraphrases fall back to the exact deterministic template. Digest fallback is bounded, and URL citation comparison uses exact membership instead of unsafe prefixes.
- Unknown historical actor/linkage means fewer/no style examples. The system does not pretend three examples exist or measure voice fidelity from a schema pass.
- FORWARD recipients, real editing, provider OAuth, public multi-session runtime, deployment and the whole F01-F42 release remain outside this acceptance result.

## Contract change requests / release blockers

**W3-D03/W3-D04 remain open.** [The accounting review](../wp3/W3_D03_SPEND_ACCOUNTING_REVIEW.md) explicitly states “Nothing here is approved, migrated or implemented.” CONTRACT section 3 says proposed budget tables are “not a blanket role-allowlist extension.” Therefore this work did not silently add their DDL or grants.

Unclosed upstream requirements: cross-process cap serialization, crash-durable attempts, failed-attempt audit and cross-worker semantic single-flight/fencing. Existing per-process reservations and successful-request exposure/cache records do not prove these. P11's full acceptance and full WP3 completion cannot be signed off until they are resolved.

The proposed review also needs correction before implementation: its blanket BEFORE UPDATE trigger rejects every forward transition, nullable uniqueness is insufficient for durable request identity, model-scoped caps need an explicit shared account-budget rule, and reservation/lease/operator resolution semantics need one enforceable transition design. Approving a general architectural direction is not evidence that this exact DDL is production ready. No contract amendment was made here.

Separately authorize any actual model/Tavily/provider validation with exact destinations, model IDs, resources and hard budgets. Approving storage design alone does not approve spending or private-account access.

## New dependencies

No production dependency was added. The already-declared Hatchling build backend and its dependencies were installed, through approved escalation, only into ignored `data/wp3-build-tools/`: Hatchling 1.32.4, packaging 26.3, pathspec 1.1.1, pluggy 1.7.0, tomlkit 0.15.2 and trove-classifiers 2026.9.21.13. No global package installation was performed. Runtime models/caches remain local and ignored.

## LLM cost incurred

Zero paid LLM/Tavily calls in this implementation/acceptance work. HTTP tests use fake transports; the actual embedding smoke is local CPU inference. Package downloads are tooling installation, not model-provider use.

## Suggested next step

Review this integrated branch and resolve the corrected W3-D03/W3-D04 accounting design through the required approval process. Finish that upstream implementation and its crash/concurrency tests before declaring WP3/P11 fully complete or enabling a multi-worker paid deployment. Keep the email demo frontend and private connector work pending their own approved release packages.

## Final verification

- `C:/Users/shaah/miniconda3/python.exe -B scripts/check.py`: passed in isolated snapshot `data/checks/run-5gf6ic7e`. **585 tests passed** (207.96 seconds), with two existing Typer/Click deprecation warnings. Ruff lint/format, application typing (164 files), strict core/engine typing (34 files) passed. Protected fixture/result hashes unchanged in source and snapshot.
- Final wheel: `data/wp3-package/verified/probation-0.1.0-py3-none-any.whl`; SHA-256 `640d726b4f5e656c1ae73c5f0f3dedbc16150ba8ed2d772caf9e685376fd5bd5`. Installed without dependencies/network into fresh `verified-installed`; secret-free outside-checkout smoke loaded 15 prompts, 29 schema tables and the final feature/exam adapter imports.
- `graphify update .`: succeeded; no code-graph topology changes detected on the final repeat. Output retained locally in `data/graphify-update.log`.
- No commit, push, branch merge into main, production deployment or live provider smoke was performed. These checks establish the tested offline integration, not closure of the accounting/single-flight blockers above.

Final documentation checks: `git diff --check` passed; four scoped WP3/handoff documents have no broken local links. The coverage CSV retains all 23 source requirements (including blocked 7.3.6/7.3.7); pre-existing unquoted status commas were normalized through CSV serialization. CONTRACT.md has no working diff.
