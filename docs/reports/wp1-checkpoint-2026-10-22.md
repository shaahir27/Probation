# WP1 verified checkpoint

Date: 22 October 2026. Branch: `phase-1-wp1-trusted-foundation`.
Worktree: `D:/Desktop/project/Probation/data/wp0_wp1/worktree`.
Status: **WP1 remains incomplete**, pending role ownership closure (5.2.3).
WP0 is completed and committed as `c92131c`. The WP2 checkout remains unchanged.

## Done

Strict shared output models and bounded schemas; parsed actions and pack catalogs;
caller-owned storage transactions; linear concurrent ledger appends; actual-target
SQL guards and dedicated role connections; deferred execution imports; immutable,
atomic proposal/draft and durable action intent; consistent ledger views; canonical
new payloads; shared clocks, UTC microseconds and stable semantic identifiers.

Recovered 102 modified/new implementation, test and documentation files from Git
tree `3f5b35dbc60a228baa8a4af1dc96f87f915149f4`, then restored the missing timestamp
repairs and added strict text, canonical payload and indirect-clock regressions.
The separately preserved recovery manifest is local under `data/wp0_wp1/recovered-wp1/`.
Recovery was not treated as validation; all checks below were rerun on this worktree.

## Numbered completion audit

Scope: `docs/CHANGES_IMPLEMENTATION_PLAN.md`, section 5. Evidence means the concrete
implementation and passing regressions listed here; it does not establish later
work-package behavior or production readiness.

| Item | Status and evidence |
|---|---|
| 5.1.1 Strict job models/shared provider schema | Implemented for registered JSON jobs in `llm/jobs.py`, pack readers and quarantine extraction. Strict finite/closed/bounded models and cross-field checks; `test_wp1_validation.py`. Writer orchestration and prompt loading remain WP3. |
| 5.1.2 R02, nested/enum/nullable/items/cache checks | Implemented; `test_wp1_validation.py` covers malformed/missing/unknown/unsupported data, bool/int distinction, finite values and validation on JSON cache hits. `test_wp1_context.py` also rejects non-string text on fresh/cache paths. |
| 5.1.3 Explicit generic schema surface | Implemented in `llm/schema.py`; documented in `docs/LLM_SCHEMA_SUPPORT.md`. Unsupported features fail before HTTP; no added dependency. |
| 5.1.4 Parsed action/type/parameter | Implemented in `core/actions.py`, caps, gate and evidence. Case-sensitive parameters survive parsing; type metadata is canonical. `test_wp1_actions.py`. |
| 5.1.5 Pack membership/no-op exclusion | Implemented in descriptors, gate and action creation; no-op predictions cannot create actions/evidence licences. Foreign-pack and malformed actions fail closed. `test_wp1_actions.py`, `test_wp1_action_storage.py`. |
| 5.2.1 Caller-owned units of work | Ledger/cache/exposure/proposal/exam/miner helpers repaired, with parent rollback and injected-failure tests. `test_wp1_storage.py`, `test_wp1_transaction_owners.py`, `test_wp1_proposals.py`, `test_wp1_chain_storage.py`. Remaining application authority gaps are tracked under 5.2.3. |
| 5.2.2 Concurrent ledger serialization | Implemented; four appenders/48 entries yield one valid chain. Append-only triggers preserved. `test_wp1_storage.py`. |
| 5.2.3 Application-wide role enforcement | **Incomplete.** Actual-target/trigger/DDL guards, read-only handles, role-switch denial, typed chain insertion and transitive executor-import regressions pass. Legacy API admin and Executor/replay drift writes remain; see below. `test_wp1_execution_authority.py`, `test_wp1_storage.py`. |
| 5.2.4 Atomic immutable proposal/draft | Implemented in `db/proposals.py`, replay and chain proposer. Ledger/proposal/draft order respects the foreign key; tests inspect a separate connection before dispatch and exercise rollback. Missing target/draft data fails closed. `test_wp1_proposals.py`, `test_wp1_replay_persistence.py`, `test_wp1_chain_storage.py`. |
| 5.2.5 Durable local intent before effects | Implemented in `db/actions.py`; retry preserves completed action state and Executor rejects uncommitted caller intent. `test_wp1_action_storage.py`, `test_wp1_replay_persistence.py`. Remote reconciliation remains WP6. |
| 5.2.6 New canonical payloads/legacy reads | Proposal/action/exam/licence names repaired, replay CUSUM includes `cusum`/`kind`, family shift uses `kind`, resolver outcomes use the compact payload. Historical licence spelling is accepted and other historical payloads are returned unchanged. `test_wp1_payloads.py`, `test_wp1_ledger_views.py`; DATA_MODEL documents old spellings. Existing hashes/bytes were not rewritten. |
| 5.2.7 Consistent ledger API metadata | Implemented empty/one/multiple/corrupt snapshot count/head/verification; `test_wp1_ledger_views.py`. |
| 5.3.1 One context clock | Injected/scoped across repaired worker/client/budget/quarantine/API paths. Replay rejects an event earlier than its injected clock. `test_wp1_context.py`, `test_wp1_api_time.py`, `test_wp1_clock.py`. |
| 5.3.2 Stable semantic IDs/attempt ordinal | Exam/case/habit/chain IDs and explicit attempt ordinals implemented. Independent populated exam runs compare case rows/ledger heads; habit/chain tests compare independent IDs and parent rollback. `test_exam_board.py`, `test_chains_habits.py`, `test_wp1_clock.py`. Whole replay equivalence remains WP2. |
| 5.3.3 UTC precision/backwards time | UTC normalization and collation preserve microseconds; backward clocks and excess precision rejected. Equal/earlier responses return 409, one microsecond later succeeds; no invented tick. `test_wp1_clock.py`, `test_wp1_time_boundaries.py`, `test_wp1_api_time.py`. |
| 5.3.4 Wider clock scan/duration rule | Application-wide AST scan covers imports, callable aliases, literal dynamic imports and indirect attributes. Duration timing is confined to `core/clock.py` and documented. `test_wp1_clock.py`. Static analysis is not a sandbox for arbitrary dynamic Python. |

## Files changed

- `backend/src/probation/{core,db,llm,engine}/`: validation, actions, guarded storage,
  clocks, history, identities and integration. New storage modules include
  `db/{actions,guards,inference,proposals}.py` and `engine/exam_storage.py`.
- `backend/src/probation/{packs,workers,api,web,links}/`, CLI and evaluation entry
  points: shared schemas/clocks, transaction ownership and descriptor separation.
- `backend/tests/unit/test_wp1_*.py`, existing exam/habit/chain and API tests.
- DATA_MODEL, ENGINE_SPEC, decisions, schema support and execution reports updated.
- Local feature logs/index updated; `build_history/` is excluded from the commit.

## Tests

Final command: `C:\Users\shaah\miniconda3\python.exe scripts/check.py` in this worktree.
This is the portable backend `make check` equivalent; GNU Make is unavailable.

- Ruff lint and formatting passed (188 files).
- Project mypy: 130 modules; strict core/engine: 24 modules; both passed.
- **344 tests passed**, two existing Typer/Click deprecation warnings.
- Sanitized snapshot `data/checks/run-rrbte2_w`; fixture/result hashes unchanged in
  source and snapshot. No `.env`, private export or live provider was loaded.
- Relevant test groups: T-ID, T-CLOCK, T-LEDGER, T-LLM, T-SEC, T-CAPS, T-EXEC boundaries.
  This does not prove every broader test-plan requirement.
- `graphify update .` completed: 3,764 nodes, 8,493 edges. Optional SQL parser absent;
  synthetic placeholder PDFs yield extraction warnings. No dependency installed.

## Invariants touched

I-1/I-3: strict data and failure handling. I-2: deferred executors and guarded writes,
with explicit remaining process-ownership gaps. I-4/I-10: canonical metadata and
read-only licence re-derivation; full licence maths remains WP5. I-6/I-7/I-9: bounded
history, one clock and strict response chronology; full event chronology remains WP2.
I-8: serialized caller-owned appends and retained immutable bytes/triggers.
I-14/I-16: atomic inference records and validated cached output; full redaction,
transport and budget-concurrency acceptance remains WP3. I-18/I-19: synthetic isolated
checks. Web restriction rules were not relaxed.

## Deviations and assumptions

DOC-A lower-authority prose now follows the existing foreign key: validate draft in
memory, ledger, proposal, draft, commit, dispatch. CONTRACT is unchanged.
This checkpoint does not complete product-wide connectors, safety, evaluation or deployment.

## Contract change request: CCR-F, administrative command ownership

**Conflict:** CONTRACT section 3 limits API writes to `user_responses`; section 9
requires habit denial and exam-run endpoints. Current `api/routes/insights.py` writes
`habits` directly and invokes Examiner work via an unrestricted API connection.
This is the previously recorded CCR-F in the changes audit.

**Proposed resolution for human review:** API accepts a strict discriminated command
(`deny_habit {habit_id}` or `run_exam {class_key, action, attempt_ordinal}`), persists
its stable idempotency key and request time, and returns a command ID/status. Examiner
consumes the command and owns all habit/exam mutations. A proposed `admin_commands`
table and its narrow API enqueue/Examiner status permissions must be approved in
CONTRACT section 3 and the request/status behavior in section 9 before implementation.
Rejected commands fail closed; retries do not run an extra exam attempt.

**Alternatives:** a human explicitly authorizes narrow role delegation, or defers
those mutation endpoints. Broad API write access is not an inferred permission.
Authority: CONTRACT section 13 permits human changes only and requires an agent to
write a request and wait; AGENTS requires stopping when documents disagree.
Affected rules: process authority, I-1/I-2/I-3/I-5 and the HTTP contract.

## Remaining engineering work

1. After the human CCR-F ruling, implement the agreed API/Examiner boundary and
   negative tests proving API cannot mutate Examiner tables.
2. Complete Examiner ownership of drift updates. `workers/executor.py` still writes
   `drift_state`; `engine/replay.py` updates it with a raw cursor. Executor should
   emit correction evidence and Examiner should consume it, with execution failing
   closed until required review. Do not silently broaden the Executor allowlist or
   replace outcome storage without the existing D2/WP6 decision.
3. Re-run required checks after those changes, finish 5.2.3 audit and final acceptance.
   No next work package, merge or publication is authorized by this checkpoint.

## New dependencies

None. No new network destination or credential.

## LLM cost incurred

Zero application LLM/Tavily calls during isolated checks. Coding-assistant session
credits are separate and are not measured here.

## Open questions and suggested next step

Resolve CCR-F and correction-review ownership, finish the remaining role integration,
then repeat WP1 acceptance. Do not mark WP1 complete from the current green suite.
