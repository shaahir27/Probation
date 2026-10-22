# Verification of changes.md

Review date: 22 October 2026 (Asia/Kolkata). Reviewed commit: `808e72f8b9694d978f5bce64ad20ecc9a82c7bab`, plus the working-tree `AGENTS.md`, `.gitignore`, and `changes.md`. This is a review record, not a phase-completion report.

Implementation plan: [CHANGES_IMPLEMENTATION_PLAN.md](../CHANGES_IMPLEMENTATION_PLAN.md).

Scope update, 22 October 2026: the implementation plan is now revision 2. The [full-product specification](../FULL_PRODUCT_SPEC.md) makes every F01-F42 capability mandatory, including native connectors and previously deferred extensions. The [coverage register](full-product-coverage.md) and [opinion review](../PRODUCT_OPINION_REVIEW.md) record the expanded request. This audit's baseline measurements and qualifications remain unchanged; earlier conditional delivery recommendations below do not remove requirements from the new full scope. No repaired application or live-account run is claimed by the planning update.

## 1. Conclusion and limits

The integrity concerns in `changes.md` are substantially supported. Its implementation prescriptions and eight-day schedule should not be approved unchanged. Several prescriptions conflict with the contract or leave essential failure cases unspecified. There are also additional correctness problems that the existing tests do not detect.

This review combined Graphify navigation, a repository-wide text/AST inventory, targeted source tracing, documentation comparison, isolated existing tests, and small synthetic runtime probes. It is not a formal proof of every line of code. A source finding, a reproduced experiment, and an unverified historical measurement are explicitly distinguished below.

The inventory covers 231 tracked text files and 41,481 lines, including all 113 backend source Python modules and 21 frontend source files. Fixtures, binary artifacts, lockfile internals, ignored private data, and secrets were not semantically audited as application source. `changes.md` was read separately because it is untracked. The file inventory is [changes-review-inventory.csv](changes-review-inventory.csv); its presence records static coverage, not an assertion that every file has been proven correct.

Graphify reported 3,212 nodes and 6,928 edges, built from the same commit. Its inferred edges were treated as navigation hints; source code was checked before accepting a relationship. Queries covered architecture, replay, execution, exams, policy, data generation, and evaluation. The broad graph report and source inventory supplied the remaining module paths.

No application source, contract, secret, original result file, original fixture, or existing ledger was modified by this review. No live provider calls or real account connections were made. Scratch work is under the already ignored `data/changes_review/`.

## 2. Reproduced baseline

| Check | Result | Interpretation |
|---|---|---|
| Ruff lint | Pass | Existing style checks are green. |
| Ruff format | Pass, 153 files already formatted | Existing formatting check is green. |
| Mypy over all backend source | Fail, four errors in four files | The configured `make check` sequence is not green. |
| Existing non-live pytest suite | 198 passed, two deprecation warnings, 60.31 seconds | Passing tests do not cover the failures reproduced below. |
| Frontend `tsc --noEmit` | Pass | Static TypeScript validation only; browser behavior and a production bundle were not rerun. |
| DDL comparison | All named schema objects and normalized SQL match | The current `schema.sql` matches the first SQL schema block in `DATA_MODEL.md`. This does not prove that the schema supports the proposed lifecycle. |
| Result-file isolation check | Copied `docs/results/main.json` and `tables.md` changed during tests | The original tree was protected by running tests in a copy. |

Mypy findings:

- `backend/src/probation/packs/mail/resolver.py:96`: `WorldView` does not declare `user_addresses`.
- `backend/src/probation/workers/resolver.py:55`: the same missing protocol attribute.
- `backend/src/probation/packs/mail/__init__.py:94`: `None` assigned after inference of `list[str]`.
- `backend/src/probation/packs/calendar/__init__.py:67`: the same optional-list typing error.

The checks used the installed Miniconda interpreter/tools. The default `python` on PATH is a different Python installation. `make` was not available on PATH; its four check commands were executed individually. Mypy was run with the repository configuration, not misreported as a successful full `--strict` invocation.

Tests ran from an isolated, tracked-file snapshot with `.env*`, key files, archives, and private data excluded. An audit hook blocked secret-file reads and non-loopback network connections; loopback was allowed for Windows asyncio self-pipes. An initial harness attempt had temporary-directory and loopback restrictions that caused harness errors; those were corrected without modifying tests. Only the successful corrected run above is the baseline.

## 3. Synthetic probes

The reproducible scratch script is `data/changes_review/probe.py`; results are `data/changes_review/probe-results.json`. These are local verification aids, not production additions.

| ID | Probe | Observed result | Consequence |
|---|---|---|---|
| R01 | Action metadata for `MOVE_TO_FOLDER:College/Lab` | Recallable false, loss 10, central cap 0 | Normalize only the action type for metadata lookup; preserve the parameter and validate it separately. The problem is wider than an incorrect hold. |
| R02 | Invalid enum without `type`, oversized nullable string, invalid regex string, too many array items | All four accepted by `validate_json_schema` | Typed job validators are a P0 prerequisite, including semantic checks and non-finite number rejection. |
| R03 | Create action for nonexistent proposal | SQLite foreign-key error | Persist the final proposal before creating actions. |
| R04 | Current ledger API aggregation on three entries | Returned head differs from actual last entry | Query count and last hash separately in one consistent read snapshot. |
| R05 | Append ledger then roll back outer connection | All three entries survive | `append_ledger` commits internally; transaction ownership must move to the caller. |
| R06 | Quoted `vet_report` query from the spec | Rejected by query guard | Correct the query specification; do not broaden the privacy guard to fit it. |
| R07 | Generate tiny persona 0, seed 7; import all three families with its explicit identity | 200 truth records, 200 situations, zero matching IDs | The mismatch reproduces even without the audit's excess-situation counts. |
| R08 | Featurize those situations without a reader/key | 200 rows with `reader_json IS NULL` and `reader_ok=1` | Required-reader failures currently masquerade as success. Optional file-reader behavior must remain distinct. |
| R09 | Resolve that world with the default replay clock | 28 outcomes returned | The fixed initial clock is not an export/as-of horizon. This count is not evidence that 28 are valid past outcomes. Some resolvers return future-known outcomes. |
| R10 | Compare file world with generated truth | All 50 file paths are in Downloads; truth specifies 25 moves | Rendering and time-aware world observation must agree with hidden truth. |
| R11 | Local brand derivation with successful empty search results | `amazon.in` and `google.co.in` classified lookalike | Regional official domains need verified domain sets. The other domains from E15 were not reproduced as lookalikes with this deliberately empty result fixture. |

R11 does not establish the real official status of any domain, nor substitute for a legitimate-domain benchmark with recorded results. E15's exact search fixtures were unavailable.

## 4. Traceability to the supplied audit

Status vocabulary: **Reproduced** = independently observed locally; **Source-confirmed** = traced in current code; **Qualified** = concern is valid but the proposed conclusion/fix needs correction; **Unverified** = original measurement or service behavior not independently rerun.

| changes.md item | Status | Current evidence and required disposition |
|---|---|---|
| P0-1 live connections and replay controls | Source-confirmed / scope decision | No live connector or supervisor is present. `api/routes/replay.py` mutates process-local state. Live tools are a stretch in the existing specs; absence is not by itself a contract violation. |
| P0-2 response consumption | Source-confirmed | Queue and Actions endpoints insert requests; there is no response-consumption loop. `Executor.process_undo` is not wired into a worker loop. |
| P0-2 idempotency and ordering | Reproduced / source-confirmed | R03; `Executor.create_action` replaces action rows; `process_undo` replaces outcomes; main replay dispatch precedes proposal insertion. An insert-ignore alone does not solve external crash/retry ambiguity. |
| P0-2 parameter actions | Reproduced | R01; central metadata and licence lookups disagree with pack-local prefix handling. |
| P0-3 truth alignment | Reproduced / qualified | R07 and R10. Replies already are generated and written to the simulated world; diagnose identity/thread matching before adding duplicate replies. |
| P0-4 reader/prompt/writer gaps | Source-confirmed / reproduced | R08; generic reader system text in `workers/brain.py`; only two prompt files; no application insertion into `drafts`; obsolete `complete_json` calls and non-Nemotron fallback IDs in exam operators. |
| P0-5 exams | Source-confirmed | `engine/exam.py:run_exam` queries all situations with outcomes, omits class/action and outcome-known cutoff, uses text/raw payload instead of trained features, defaults probability to .99, and reuses base cap. Scheduler and examiner-worker paths omit a real policy. |
| P0-6 evaluation | Source-confirmed | Five literal ablation outcomes; empty-proposal fallback manufactures predictions from truth; truth lookup silently substitutes another dataset; B3 is not supplied a real client by the runner. Remove invalid evidence from claims. |
| P0-7 ledger | Reproduced / source-confirmed | R04/R05; resolver pre-pass appends outcomes before replay proposals; random exam IDs prevent deterministic replay heads when exams occur. |
| P0-8 drift | Qualified | Replay updates CUSUM without filtering strength or ABSTAIN; PSI chooses the first five deterministic dictionary keys. **Do not skip all SHADOW proposals:** they are valid non-executed evidence under ENGINE_SPEC 6.1. |
| P0-9 Tavily | Source-confirmed | Out-of-band verifier has no application caller; Extract lacks the Search budget check; entity worker does not implement the complete trigger/known-domain policy. |
| P0-10 hygiene | Reproduced / source-confirmed | Four mypy errors; unsafe synthesis default; CLI stub test invokes evaluation with production-default export paths; local build logs are already tracked. Adding an ignore rule alone will not untrack them. |
| P1 calibration/cold start/novelty | Source-confirmed | In-sample calibration; policy default ties cold start to level-1 evidence count; config sets 20 instead of 200; TF-IDF with `>=` novelty boundary. |
| P1 tunables | Source-confirmed | Several documented constants are missing from Settings or bypassed by module defaults; configured values are not consistently passed into pure functions. |
| P1 gate inputs/cross-check | Source-confirmed | `reader_required=False`, `deterministic_ok=True`, `budget_ok=True` in replay; attention cost also literal. |
| P1 web/family mapping | Source-confirmed | Replay applies sender-domain web lookup without pack restriction; file uses class prefix `file` while pack is `files`; exam family mapping omits chains, Radar, Reading. |
| P1 habits/history | Source-confirmed | `mine_habits` filters situation occurrence but not outcome known time; raw history queries also appear in replay, exams, chains, evidence and licence-related code. Temporal access needs a coherent bounded interface. |
| P1 report-card ABSTAIN | Qualified | Counting ABSTAIN as a miss matches EVALUATION_PLAN 3. Keep both all-items and non-abstained metrics; do not improve the headline by dropping misses. `would_ask` semantics and unresolved denominators need separate repair. |
| P1 quadratic clues | Source-confirmed; timing unverified | Mail clues rescan historical raw records and situations. E9's 280 seconds is an original measurement, not reproduced here. Index behind HistoryView and benchmark scaling. |
| P1 LLM errors/retries | Source-confirmed | Non-200 structured responses disable structured mode regardless of cause; ConnectTimeout omitted; fallback can accept reasoning content; concurrency unused. |
| P1 identity/redaction | Source-confirmed | Blank identity can become an empty substring; matching is substring-based; pack redaction does not supply header display names. Centralize exact normalization and identity propagation. |
| P1 roles/licences | Source-confirmed | Executor writes drift state directly and reads cached licence level by default; API directly updates habits; `RoleAccess` verifies a supplied table string but does not constrain arbitrary raw-connection SQL. |
| P1 ledger payload | Source-confirmed | Licence producer uses `prev_level`; route expects `old_level`. Freeze a canonical payload and support old records without rewriting the ledger. |
| P1 Tavily clock | Qualified | Client uses newly constructed `Clock()` instances, not a literal direct real-clock call. They do not share the caller's as-of time, so accounting and logged time can diverge. |
| Section 7 API/UI | Source-confirmed, visual unverified | Fixture-only fields; detail client unused by the queue; edited body not submitted; fake status copy; state-only navigation; no UI test/lint scripts; unsafe source href rendering. More already contains Settings/Exposure views; repair their data rather than claim they are entirely absent. |
| Section 8 lookalike threshold change | Qualified | Comparing against every unrelated brand creates false positives, but a label-length cutoff of six is only a heuristic. Validate it against legitimate and fictional adversarial fixtures before selecting it. |
| Section 8 Extract/date/auth | Source-confirmed / live unverified | Options are not all forwarded; URL vetting uses hostname inconsistently; fee/date rules need support-aware validation. Documentation supports bearer headers; this does not prove current body auth fails. |
| Section 9 models/cascade | Source-confirmed / live unverified | Multiple model IDs and reasoning fallback exist. Exact endpoint-supported IDs, cost, latency and reasoning controls require a separate approved smoke run. |
| Section 10 contradictions | Confirmed | API outcome permissions, pack input signature, prompt/draft persistence ordering, query grammar, frontend task scores, and obsolete scaffold descriptions need explicit decisions. |
| Sections 11-12 roadmap | Proposal, not verified feasibility | Three live services, MCP client and server, integrity repair, evaluation and deployment in eight days have no demonstrated capacity estimate. Schedule gates must replace promises. |
| Sections 13-14 upgrades | Scope proposals | None may be treated as completed or as a prerequisite for repairing the earned-permission loop. Dispositions appear in the plan. |
| Section 15 unverified services | Still unverified locally | Public documentation checks reduce uncertainty; they do not establish account access, quota, billing, retention or live latency. |
| Section 16 reproduction | Requires correction | Use isolated paths, explicit identity/as-of, the chosen interpreter, and corrected CLI forms. Never resolve/reveal outcomes before committing proposals as a final acceptance workflow. |

The supplied E1/E3 results reproduce. Its other exact tiny/full-persona totals, 0/2 licence counts, runtime measurements, agreement percentages, 248-case exam experiment, and 20-persona expectations are not new measurements from this review. The introduction also says 2,900 situations while other passages say 3,989; report primary situations, imported artifacts and derived follow-ups separately.

## 5. Additional findings the plan must cover

1. **Schema validation is incomplete (R02).** The current generic validator drops sibling constraints for nullable unions and ignores enum-only schemas, regex patterns and array length. Existing schemas use these constructs. Validate every cached response as well as fresh output and fail on unsupported schema constructs.
2. **Action parameters are empty in main replay.** Fixing the foreign key exposes another failure: mail requires message IDs; files require paths; RSVP requires event identity. Construct parameters with pack-owned typed builders and validate them in the Executor.
3. **File boundaries check destination more thoroughly than source.** `packs/files/executor.py` can accept an absolute existing source outside allowed roots; undo does not revalidate either root. It also reports simulated success for absent files. Add synthetic boundary tests before enabling file execution.
4. **Undo-window and held-cancel logic are incomplete.** `process_undo` accepts DONE only, so a HELD reply cannot be cancelled through it. It does not enforce the configured undo age. Failure must not mark an action UNDONE.
5. **The two-undo rule has transient memory.** A new CUSUMTracker is created from persisted scalar state per event, while its undo history is in memory. Query durable events for the rolling 30-day count so restart does not forget the first undo.
6. **No-peeking tests can pass without proving the main invariant.** The property test copies already-computed features into every mutation run and asserts `<=` instead of the contract's `<`. Add tests that recompute features, modify future raw observations, activate training/exams, and verify ledger sequence ordering.
7. **Temporal interfaces expose mutable connections.** HistoryView has `conn`; RoleAccess has a raw connection and trusts the caller's declared target table. Tests of `verify_write()` alone do not prove process isolation. Introduce enforceable repository/connection capabilities and attack them through real public entry points.
8. **World snapshots can reveal future state.** Calendar outcomes can be returned with future known times; files and final labels require observation horizons. `WorldView` is not explicitly as-of bounded. Public-data fixtures are a documented restriction-only web exception, not permission to use future personal footprints.
9. **WebFactsView ignores its as_of parameter and TTL.** Replay omits as_of when calling it. Distinguish present-knowledge fixture facts from live historical observations, and never reuse expired entries as current facts.
10. **Budgets fail open and do not reserve concurrency.** Tavily returns budget-allowed on query errors or missing DB and suppresses audit-write errors. LLM `check_and_reserve` does not reserve anything, new clients start at zero unless synchronized, and only final-success usage is counted. Parallel calls would magnify these defects.
11. **Feature names can be misaligned with model columns.** `FeatureEncoder.fit` records names while visiting sorted mixed keys; transform emits numeric columns first, then categoricals. Verify alignment before producing coefficient explanations or selecting PSI features. Policy version hashes only the first 20 flattened coefficients and omits the full encoder state.
12. **Evaluation fabricates more than ablation deltas.** The empty-proposal fallback predicts from truth with level 2/confidence .95. Remove it. An absent sample must be unavailable with denominators, not perfect accuracy, perfect exam pass rate or successful empty-chain retrieval.
13. **Build history is already tracked.** The local-only logging protocol is currently violated by tracked files. A prospective ignore rule does not repair that; untracking requires an explicitly reviewed index change. No files were untracked here.
14. **Radar/chain intake and failure reporting need repair.** Ingestor dispatches by the raw record's existing pack, so Radar's mail reader branch is not a substitute for a post-reader derivation step. Chain outcome fallback does not check its window; Radar DISMISS suppresses exceptions while returning success.
15. **Deployment needs runtime separation and tenancy.** Shared public mutation endpoints must not let one visitor consume another visitor's budget or action queue. CORS is currently wildcard with credentials. Rate limits, read-only/precomputed mode, isolated sessions, and admin authorization need concrete tests.

These are source-review findings unless explicitly tied to a probe. File-boundary behavior, restart races, browser exploits, provider crash ambiguity and a complete trained replay were not exercised against live systems.

## 6. Contract change requests and document decisions

No edits to `docs/CONTRACT.md` are authorized or proposed for automatic application. Its sections 3 and 13 require decisions before the dependent implementation. The plan is conditional at these boundaries.

| Decision | What must be resolved | Recommended direction and alternative |
|---|---|---|
| CCR-A: feedback ownership | Section 3 allows API writes only to user_responses; section 9 says respond writes a strong outcome. A new responder is not a listed database role. | API records intent; Executor consumes executable requests; resolver records normal explicit-feedback outcomes; examiner owns drift. Clarify eventual result semantics. Alternative: explicitly revise the role table; do not bypass it. |
| CCR-B: multiple outcomes | A single situation primary key cannot retain original footprint, later explicit correction, and undo as independent temporal facts. | Approve an append-only outcome-event model plus an as-of projection and migration; keep original ledger bytes. Alternative: ledger-backed correction projection with an explicitly documented HistoryView reader. Neither may overwrite historical truth. |
| CCR-C: explicit approval | Actions require level_required 1-3; unconditional licence recheck can cancel a human-approved action for a level-0 class. | Document a human-approval authority path that still enforces catalog, hands-off, parameters, draft rules and credential boundaries. Never silently set level_required=0 against current DDL. |
| CCR-D: edited drafts | `respond` supports edited_action, not edited_body, and API may not write drafts. | Approve an immutable response payload carrying validated edits and define Executor-only use; keep generated draft provenance. Alternative: disable body editing visibly until supported. |
| CCR-E: pack boundary | Contract expects `iter_situations(source, since)`; current implementation consumes raw records. | Keep the public contract, add an internal raw-item helper and explicit ingestion adapter. Approving the alternative public signature requires a human contract edit. |
| CCR-F: habit deny/admin jobs | API is read-only except user_responses, while habit deny and examiner routes invoke other writes. | Approve a typed command/ownership mechanism or expressly clarify the allowed role delegation. Do not widen permissions incidentally. |
| CCR-G: task-scoped score | Frontend plan already requests a contract change for task/action report-card scope. | Approve additive exact-scope filters and response schema; otherwise show family summary and task score unavailable. |
| DOC-A: draft order | ENGINE_SPEC 7.1 says drafts before proposals, but drafts has an immediate proposal FK. | Generate/validate draft in memory first; persist proposal then draft in one transaction. Update the lower-authority spec after review. |
| DOC-B: web monotonicity | T-WEBISO says removing web restrictions never raises autonomy, which reverses the restriction-only direction. | Adding a veto cannot raise autonomy; removing it may restore baseline autonomy. Preserve probability, evidence and licence independence. |
| DOC-C: query/theme/scope | Quoted query conflicts with grammar; MEMBER_SPLIT theme conflicts with frontend brief; scaffold readiness text is stale. | Keep query guard; remove unsupported query syntax. Choose current design brief explicitly. Update readiness statements to measured capabilities. |

Adding live accounts, new provider destinations, signing keys, a new dependency, or real-data processing requires separate approval under AGENTS.md. This review does not exercise those paths.

## 7. External checks, 22 October 2026

The [official rules](https://nebiusglobalaihackathon.devpost.com/rules) confirm the 30 October deadline at 10:00 PDT (22:30 IST), judging through 15 December, NVIDIA-model/Nebius use, public source and licence requirements, video/testing access, and runtime Tavily eligibility. The video guidance is under three minutes; 2:50 is a useful production target. The trademark restriction has a permission exception; `changes.md` overstates it as absolute. Access may be a website, functioning demo or test build, with testing credentials if private. Avoid turning one preferred hosting approach into an externally mandated architecture.

The [organizer FAQ](https://nebiusglobalaihackathon.devpost.com/details/faqs) explicitly says an NVIDIA model call through Token Factory qualifies; the entire frontend/backend need not be hosted on Nebius AI Cloud. Nebius hosting remains the local Phase 11 target until changed deliberately. The [judging update](https://nebiusglobalaihackathon.devpost.com/updates/46204-here-s-how-judging-works) describes the four equally weighted criteria and interest in memory and real actions. That guidance is not a mandate to connect three private accounts in eight days.

The [resources page](https://nebiusglobalaihackathon.devpost.com/resources) lists two $25 Token Factory credit opportunities. That does not prove this account has $50 or raise its approved budget.

Official [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) and [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) references document bearer authentication, usage reporting options, and query/extraction controls. Prefer the documented header flow; verify account-specific billing and rate limits in an approved smoke test.

The [Nebius Nemotron catalog](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference) and [official cookbook](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md) list Nano, Super and Ultra offerings. Exact model IDs and supported request options must still be confirmed against the selected account endpoint; this review does not certify the current defaults.

The optional MCP, Notion, IMAP, private-iCal, OpenShell, Hermes, NemoClaw, signing and serverless ideas are intentionally left behind feasibility/authorization gates. Their existence in a proposal is not evidence of compatibility or a supported deployment.
