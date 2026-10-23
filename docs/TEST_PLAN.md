# TEST_PLAN

What must be tested, and what must pass at each phase. Test IDs (`T-...`) are referenced by `IMPLEMENTATION_PLAN.md`. Authority: below `CONTRACT.md`.

---

## 1. Principles

1. **Invariants first.** Every invariant in `CONTRACT.md` section 2 has at least one test.
2. **No live LLM in tests.** Use `StubReader` (a deterministic reader that derives reader fields from synthetic truth attributes) and a fake HTTP server for `LLMClient`. Exactly **one** optional live smoke test, marked `@pytest.mark.live`, is excluded from `make check`.
3. **Deterministic.** Every test seeds its randomness. Replays with the same seed give an identical final ledger hash.
4. **Small fixtures.** `tests/fixtures/tiny_synth/` holds one persona with about 200 situations across all packs. Full-size data is only for evaluation runs.
5. **Test the contract, not the implementation.** Prefer table-driven tests over mocks of internals.

Commands: `make check` runs lint, types and all tests except `live`. Coverage targets: 85% or more for `core/`, `db/`, `engine/`; 70% or more overall.

---

## 2. Test catalogue

### Foundations

| ID | Covers | What to test | Pass condition |
|---|---|---|---|
| **T-ID** | Deterministic IDs | `det_id` for the same parts returns the same value; ingesting the same source twice creates no duplicates | Row counts unchanged on re-import |
| **T-CLOCK** | I-9 | Replay clock is monotonic and settable; a static check finds no `datetime.now(` or `time.time(` outside `core/clock.py` | Zero violations |
| **T-LEDGER** | I-7, I-8 | Append 1,000 rows; `verify()` returns ok; direct `UPDATE` and `DELETE` raise; changing one stored payload makes `verify()` report that `seq`; genesis hash is 64 zeros; canonical JSON is stable across key order and float noise | All pass |
| **T-REDACT** | I-14 | Fixtures per type (PROMPTS section 1.3), including negatives; counts correct; `restore_map` never serialised into the LLM request | All pass |
| **T-LLM** | I-1, I-3, I-15, I-16 | Against a fake server: retries with backoff on 429 and 5xx; honours `Retry-After`; JSON-schema rejection triggers the fallback; one repair retry then `LLMValidationError`; second identical call hits the cache (no HTTP); budget cap raises `BudgetExceeded` before the call that would exceed it; `exposure_log` row written | All pass |
| **T-SEC** | I-2, I-19 | Static import-graph check: `workers/brain.py` and `workers/examiner.py` do not import executor credentials or pack `execute` modules; no secret strings in logs; no network library used outside the allowed modules | Zero violations |

### Engine

| ID | Covers | What to test | Pass condition |
|---|---|---|---|
| **T-NOPEEK** | I-6, I-7 | **Property test.** Run a full replay on the tiny persona and record proposals. For random cut times `t`, mutate every outcome with `known_at > t` (flip actions, delete some), re-run, and compare. All proposals with `proposed_at <= t` must be identical (probabilities, `features_hash`, gate). Also assert `proposal.proposed_at < outcome.known_at` for every situation | Zero differences across 50 random cuts |
| **T-LB** | ENGINE_SPEC 6.2, 16 | Golden numbers table (below) | All within tolerance |
| **T-POLICY** | ENGINE_SPEC 4 | Cold start gives `ABSTAIN` and `SHADOW`; fewer than 2 observed actions gives no model; training uses only strong, reader-ok, non-hands-off rows with `known_at <= as_of`; time-decay weights computed as specified; temperature stays within `[0.5, 5.0]`; probabilities sum to 1 | All pass |
| **T-NOVELTY** | ENGINE_SPEC 5 | Known points not flagged; a far synthetic point flagged; fewer than `NOVELTY_K + 1` training rows gives `novel=True` | All pass |
| **T-EVIDENCE** | ENGINE_SPEC 6.1, 9, 10, I-11, I-12 | Auto-executed items never appear in the evidence set; weak outcomes counted only in `all`; audit-holdout items are counted; undo creates a strong disagreement outcome that feeds drift but not the Beta counts | All pass |
| **T-CAPS** | ENGINE_SPEC 8 | Each action has the specified base cap, loss, recall flag and economic bar; conditional caps (unknown sender, money, personal-info) combine with `min`; level 3 is impossible for non-recallable actions | Table-driven, all pass |
| **T-HANDSOFF** | ENGINE_SPEC 8.2 | Every listed extension, a double extension, and the U+202E character are blocked; ordinary files are not | All pass |
| **T-GATE** | ENGINE_SPEC 7 | Table-driven (below) | All rows pass |
| **T-CUSUM** | ENGINE_SPEC 11.1 | A run of successes keeps `S` at 0; a burst of errors raises it and alarms at 5; the two-undos-in-30-days rule alarms immediately; an alarm records `last_alarm_at`, after which level 2 and 3 are unavailable until an exam finishes later, so the effective level is at most 1 | All pass |
| **T-PSI** | ENGINE_SPEC 11.2 | Identical distributions give PSI near 0; a shifted distribution exceeds 0.25; shares floored at 1e-4 (no infinities) | All pass |
| **T-EXAM** | ENGINE_SPEC 15 | A deliberately cheating policy (decides on a keyword) fails the invariance or directional checks; a sound policy passes; fewer than `EXAM_MIN_VALID_CASES` gives `insufficient_cases`; invalid edits are discarded and counted; verdicts are computed without any LLM call; a pass at `level_tested = 3` also satisfies level 2; at most `EXAM_MAX_PER_DAY` exams start per review tick and only for pairs that meet the numeric bar; an exam older than `EXAM_VALID_DAYS`, or older than the latest drift or family-shift alarm, no longer counts | All pass |
| **T-HABIT** | ENGINE_SPEC 13, PROMPTS 7 | Planted pattern found; random data yields no habits after BH correction; wording validator rejects a changed number and accepts a reworded sentence with identical numbers; a denied habit is excluded from explanations | All pass |
| **T-CHAIN** | ENGINE_SPEC 14 | Planted chain found with correct `k`, `n`, lift; weak links give level 1 at most; explicit user accepts can raise evidence to strong; each follow-up is its own situation (`variant`) with its own proposal; a window with no response and no link gives the weak outcome `NONE` | All pass |

### Packs and execution

| ID | Covers | What to test | Pass condition |
|---|---|---|---|
| **T-PACK** | PACKS_SPEC 7 | The seven conformance checks for every registered pack | All pass per pack |
| **T-RESOLVE** | PACKS_SPEC outcome tables | Crafted fixtures for every row of each pack's outcome table, including priority order (reply beats forward beats trash and so on), censoring near the export date, and `known_at` rules | All pass |
| **T-EXEC** | CONTRACT section 8, I-2, I-10, I-20 | Same action ID twice causes one effect; `HOLD_THEN_EXECUTE` does nothing before `hold_until`; licence lost during a hold gives `CANCELLED` and a new `SUGGEST`; undo restores the world exactly for every recallable action; an action type outside the catalog is refused; file moves never leave `FILES_ALLOWED_ROOTS` and never overwrite | All pass |

### Data, API, end to end

| ID | Covers | What to test | Pass condition |
|---|---|---|---|
| **T-SYNTH** | EVALUATION_PLAN section 2 | Same seed gives byte-identical output; observed habit adherence is within 2 points of `1 - noise`; truth file never imported by the engine (static check) | All pass |
| **T-API** | CONTRACT section 9 | Each endpoint returns the documented shape; the error shape is uniform; `POST /queue/{id}/respond` writes a response row and a strong outcome; `POST /actions/{id}/undo` writes a `user_responses` row only (the Executor performs the undo); `GET /items/{id}` and `GET /settings` return the documented shapes; `GET /ledger/verify` detects tampering | All pass |
| **T-E2E** | Whole system | Run `import -> backtest -> licences -> exam` on the tiny persona: ledger verifies; one proposal per situation; report card counts sum correctly; two runs with the same seed give the same final ledger hash | All pass |
| **T-WEBQ** | I-23 | The query guard: allowed characters and length; rejects `@`, `<`, `>`, `http`, 6-digit runs, `<PERSON_n>`, tokens from `USER_NAME_TOKENS`; a rejected query makes no HTTP call and gives `not_checked`; every sent query is recorded in `tavily_calls` with its exact text | All pass |
| **T-WEBISO** | I-21 | Static import check: `engine/policy.py`, `evidence.py`, `licence.py`, `features.py` do not import `web/`; `WebFactsView` returns a type with no probability, evidence or licence fields; adding entity restrictions never raises autonomy above baseline; removing restrictions may restore baseline autonomy, while entity facts never change policy probabilities, evidence or derived licences (property test over the tiny persona); **exhaustive gate check**: for every combination of action, probability, novelty, licence level, cap and hands-off, the gate with `web_cap = 1` has an autonomy rank (ENGINE_SPEC 15.2) no higher than with `web_cap = 3` | Zero violations |
| **T-VET** | `TAVILY_AND_NEW_PACKS.md` section 5 | EntityFacts derivation on **recorded Tavily fixtures**: homoglyph and hyphen lookalikes, brand-in-label, legitimate domain, no presence, two-hit reports, one-hit reports (not enough); status precedence; local brand list gives immediate status; budget exhaustion or failure gives `not_checked` and unchanged caps | All pass |
| **T-QUAR** | I-22, I-26 | A page or snippet containing "ignore previous instructions..." leaves typed fields and decisions unchanged; validators null out an unsupported deadline, fee flag, or eligibility line; the digest validator rejects an uncited statement; the writer never receives page text (assert on the request body) | All pass |
| **T-LINK** | I-24, `TAVILY_AND_NEW_PACKS.md` section 7 | Sanitiser: bad scheme, IP host, localhost, private ranges, token parameters, long and high-entropy values, sensitive paths, tracking parameter stripping; Extract is never called for a mail-body link or for a `lookalike` or `reports_found` domain | All pass |
| **T-EVAL** | EVALUATION_PLAN metrics | Metric functions on hand-computed fixtures (agreement, precision, coverage, interruptions, autonomous error rate, calibration error) | Match to 1e-9 |

---

## 3. Golden tables

### 3.1 T-LB (from `ENGINE_SPEC.md` section 16)

| Case | Expected |
|---|---|
| No parent, `k=n=58` | `LB >= 0.95` |
| No parent, `k=n=57` | `LB < 0.95` |
| No parent, `k=n=148` | `LB >= 0.98` |
| No parent, `k=n=147` | `LB < 0.98` |
| No parent, `k=n=60` | `0.952 +/- 0.001` |
| No parent, `k=41, n=42` | `0.894 +/- 0.003` |
| Parent mean 0.99, `kappa=10`, `k=n=48` | `LB < 0.95` |
| Parent mean 0.99, `kappa=10`, `k=n=49` | `LB >= 0.95` |
| Parent mean 0.99, `kappa=10`, `k=n=40` | `0.9417 +/- 0.002` |

### 3.2 T-GATE (table-driven; each row is one test)

Defaults: `attention_cost=1`, `audit_fraction=0.10`, `audit_draw=0.5` unless stated.

| Case | Inputs (changes from default) | Expected gate |
|---|---|---|
| Budget exhausted | `budget_ok=False` | `ASK` |
| Reader failed, reader required | `reader_ok=False` | `ASK` |
| Reader and header facts disagree | `deterministic_ok=False` | `ASK` |
| Hands-off file | `hands_off="executable"` | `SHADOW` |
| Level 0 | `licence_level=0` | `SHADOW` |
| Level 1 | `licence_level=1` | `SUGGEST` |
| Cap below licence | `licence_level=3, cap=1` | `SUGGEST` |
| Novel item | `licence_level=2, novel=True` | `ASK` |
| Economic test fails | `REPLY` (loss 40), `p=0.95`, `licence_level=2` | `ASK` |
| Economic test passes, not recallable | `REPLY`, `p=0.99`, `licence_level=2` | `HOLD_THEN_EXECUTE` |
| Economic test passes, recallable | `ARCHIVE` (loss 5), `p=0.9`, `licence_level=2` | `EXECUTE_UNDO` |
| Audit draw selected | `licence_level=2, ARCHIVE, p=0.9, audit_draw=0.05` | `SUGGEST` with `audit_holdout=1` |
| Level 3 | `ARCHIVE, licence_level=3, p=0.9` | `EXECUTE_SILENT` |
| Predicted no-op | `action=LEAVE` | `SHADOW` |

---

## 4. Test data and stubs

- `StubReader(truth)`: returns reader fields exactly as the synthetic truth attributes dictate, with an optional configurable error rate for robustness tests.
- `FakeLLMServer`: a local HTTP server mimicking the OpenAI-compatible API; supports scripted failures.
- `tiny_synth`: generated once by `probation synth generate --persona-id 0 --seed 7 --size tiny` and committed (synthetic data only).
- `SimWorld` fixtures: small mailbox, calendar and file tree for executor and resolver tests.

---

## 5. Phase gates

A phase is **done** only when its tests pass in `make check` and its acceptance items in `IMPLEMENTATION_PLAN.md` are demonstrated.

| Phase | Required tests |
|---|---|
| 0 | spikes recorded (no tests), including one real Tavily search and extract call |
| 1 | T-ID, T-CLOCK, T-LEDGER, T-REDACT, T-LLM, T-SEC (partial) |
| 2 | T-SYNTH, importer parts of T-RESOLVE |
| 3 | T-PACK and T-RESOLVE for mail and calendar |
| 4 | T-NOPEEK, T-POLICY, T-NOVELTY, T-LB, T-E2E (backtest only) |
| 5 | T-EVIDENCE, T-CAPS, T-GATE, T-CUSUM, T-PSI, T-EXEC (mail, calendar) |
| 6 | T-PACK, T-RESOLVE, T-EXEC, T-HANDSOFF for files |
| 6b | T-WEBQ, T-WEBISO, T-VET |
| 7 | T-EXAM |
| 8 | T-HABIT, T-CHAIN |
| 8b | T-LINK, T-QUAR, and T-PACK, T-RESOLVE, T-EXEC, T-EXAM operators for radar and reading |
| 9 | T-API |
| 10 | T-EVAL |
| 11 | T-E2E on the deployed build; `ledger verify` clean on the demo database |
| 12 | Full `make check`; secrets scan; fresh-clone run of `make setup && make synth && make backtest` |


## Approved contract v2 acceptance additions (22 October 2026)

These are required future implementation regressions, not claims of passing tests.
Keep the existing invariant tests. See CONTRACT_AMENDMENT_2026-10-22.md for authority.

| Scope | Required additional acceptance |
|---|---|
| D1/D6; T-API/T-SEC/V16 | API only inserts typed intent and returns 202; owner-scoped response status; first initial decision wins; retries/worker restart consume once; decision and remote effect results stay separate. |
| D2; T-NOPEEK/T-LEDGER/V08-V10 | Append linked corrections without replacing earlier events; as-of projections reproduce history; one evidence vote per proposal; no invented rejection labels; migration preserves ledger bytes/hashes and rollback. |
| D3/D4; T-EXEC/V17-V20 | Explicit approval at licence 0 binds exact account/resource/recipient/body and obeys hands-off/validators; changes require reapproval; autonomous licence/cap/hold checks unchanged; edit provenance survives restart. |
| D5; T-ID/T-PACK | Source/since and internal observation mapping agree across import/live profiles; cursor/page commit is atomic. |
| D7; T-API/V29 | Exact family/class/action/time cohorts and denominators; no copied family metric; empty score unavailable; permission bound/exam/authority separate. |
| DOC-A; T-LEDGER/V03 | Ledger, proposal, draft atomically persist in FK-safe order; rollback leaves no partial state; commit precedes dispatch. |
| DOC-B; T-WEBISO/V27 | Adding entity restrictions never increases autonomy; removing restrictions may restore baseline. Entity facts never change policy probabilities, evidence or licences. |
| DOC-C; T-WEBQ/V25/V30 | Unquoted supported query grammar with unchanged privacy guard; one Spruce & Brass dark theme; readiness reflects verified real workflow. |
| D9/FP gates; V24-V26/V33 | Prospective live evidence separated from backfill; role-isolated secret lifecycle; MCP/runtime no bypass; receipt binding/revocation/replay checks; bounded checker quota; consented synthetic-stimulus study; authorized live resources only. |
