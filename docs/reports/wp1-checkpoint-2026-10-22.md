# WP1 verified checkpoint and outstanding requirements

Date: 22 October 2026. Branch: `phase-1-wp1-trusted-foundation`.
Status: implementation checkpoint, **not completed WP1 acceptance**.
WP0 is complete and committed as `c92131c`. No next work package was started.

## Done

Strict JSON job validation and shared provider schemas; canonical parsed actions and
pack catalogs; caller-owned ledger/cache/proposal transactions; serialized ledger
appends; SQL-target guards and dedicated role capabilities; deferred executable pack
imports; durable action intent; immutable proposal/draft persistence; consistent
ledger metadata; scoped clocks, UTC microsecond ordering, deterministic identifiers,
and response-time rejection instead of fabricated timestamps.

Missing executable parameters or drafts remain fail-closed. This work does not
establish live connector readiness, complete chronology, correct product-wide
licences or measured autonomy. Those have later work-package acceptance criteria.

## Numbered WP1 audit

Scope: `docs/CHANGES_IMPLEMENTATION_PLAN.md`, section 5. Verified means covered by
the listed implementation and passing regressions, within the stated boundary.

| Requirement | Disposition and evidence |
|---|---|
| 5.1.1 Strict job models and exported schemas | Implemented for the registered JSON jobs in `llm/jobs.py`, pack reader schemas and quarantined extractors. `test_wp1_validation.py`. Prompt loading, writer orchestration and transport behavior remain WP3. |
| 5.1.2 R02 and cache validation regressions | Implemented: nested/nullable/enum/pattern/items, bool/int, nonfinite/missing/extra/unsupported shapes and current validation of JSON cache hits. `test_wp1_validation.py`. |
| 5.1.3 Explicit schema surface | Implemented and documented in `docs/LLM_SCHEMA_SUPPORT.md`; unsupported constructs fail before transport. No new dependency. |
| 5.1.4 Parsed action and preserved parameter | Implemented in `core/actions.py`, caps, evidence and policy labels. `test_wp1_actions.py`. |
| 5.1.5 Pack-specific catalog and no-op handling | Implemented in descriptors, gate and action creation. No-op evidence/licence exclusion and malformed/foreign-pack rejection tested. `test_wp1_actions.py`, `test_wp1_action_storage.py`. |
| 5.2.1 Caller-owned units of work | Ledger/cache/exposure, proposal/draft, exam, habit and chain helpers repaired; rollback tests cover parent work and inference pairs. `test_wp1_storage.py`, `test_wp1_transaction_owners.py`, `test_wp1_proposals.py`, `test_wp1_chain_storage.py`. Full application enforcement remains incomplete under 5.2.3. |
| 5.2.2 Linear concurrent ledger appends | Implemented. Four concurrent appenders, 48 entries, one verified chain; UPDATE/DELETE triggers retained. `test_wp1_storage.py`. |
| 5.2.3 Role capabilities and executor import separation | **Partial.** Actual-target SQL guards, trigger/DDL denial, read-only handles, role-switch prevention and transitive import tests pass. API habit/exam operations and Executor drift writes remain outside their contract rows; see CCR-F below. Replay also retains direct drift-state writes. `test_wp1_execution_authority.py`, `test_wp1_storage.py`. |
| 5.2.4 Atomic complete proposal and draft | Implemented in `db/proposals.py`, replay and chain proposer. Ledger/proposal/draft order respects the existing foreign key; parent rollback and independent-connection durability are tested. Missing target/draft fails closed. `test_wp1_proposals.py`, `test_wp1_replay_persistence.py`, `test_wp1_chain_storage.py`. |
| 5.2.5 Durable intent before external effects | Implemented local intent and immutable retry in `db/actions.py`; Executor refuses an uncommitted caller transaction. Remote reconciliation is explicitly WP6. `test_wp1_action_storage.py`, `test_wp1_replay_persistence.py`. |
| 5.2.6 Canonical payloads and historical readers | **Partial.** Proposal, action, exam and licence payloads repaired; legacy licence spellings remain readable and old hashes untouched. Replay/family-shift alarm and resolver-outcome payload coverage remains incomplete; exact gaps below. |
| 5.2.7 Consistent ledger API snapshot | Implemented empty/one/multiple/corrupt count and head from one read snapshot. `test_wp1_ledger_views.py`. |
| 5.3.1 Shared context clock | Implemented scoped clocks across repaired worker/client/API paths; budgets and quarantine use the context. Injected replay clocks reject earlier events rather than silently retaining a later horizon. `test_wp1_context.py`, `test_wp1_api_time.py`, `test_wp1_clock.py`. |
| 5.3.2 Stable semantic identifiers | Implemented exam/case/habit/chain IDs and explicit attempt ordinals; independent database runs compare IDs, populated exam cases and ledger heads. `test_wp1_clock.py`, `test_wp1_time_boundaries.py`, `test_wp1_chain_storage.py`. This is not a whole-replay WP2 equivalence result. |
| 5.3.3 UTC precision and ordering | Implemented UTC normalization, six-digit microsecond precision, instant-aware SQLite collation and backward-clock rejection. Equal/earlier response times return HTTP 409; one microsecond later is accepted. `test_wp1_api_time.py`, `test_wp1_time_boundaries.py`. |
| 5.3.4 Complete indirect clock scan | **Partial.** Application-wide direct/import-alias scan and duration boundary exist. Callable assignment aliases, dynamic imports and indirect attribute access are not yet covered. `test_wp1_clock.py`. |

## Files changed

- `backend/src/probation/{core,db,llm,engine}/`: typed validation, actions, storage,
  history, clocks, IDs and their integration. New repositories: `db/actions.py`,
  `db/inference.py`, `db/proposals.py`, `engine/exam_storage.py`.
- `backend/src/probation/packs/`: read/decision descriptors, deferred execution imports,
  shared job schemas, preserved action parameters, chain persistence.
- `backend/src/probation/{workers,api,web,links}/` and CLI/evaluation entry points:
  context clocks, transaction ownership and ledger metadata integration.
- `backend/tests/unit/test_wp1_*.py`, API tests and existing integration fixtures:
  synthetic regressions. No published results or synthetic source fixtures rewritten.
- `docs/{DATA_MODEL,ENGINE_SPEC,DECISIONS_AND_OPEN_QUESTIONS}.md`,
  `docs/LLM_SCHEMA_SUPPORT.md` and WP execution reports: actual behavior and limits.
- Local `build_history/` feature records/index updated; excluded from this commit.

## Tests

Final command: `C:\Users\shaah\miniconda3\python.exe scripts/check.py`.
GNU Make is unavailable; this portable command runs the required backend checks.

- Ruff lint passed; 187 files passed formatting.
- Project mypy: 130 modules; strict core/engine mypy: 24 modules; both passed.
- Non-live pytest: **328 passed**, two existing Typer/Click deprecation warnings.
- Isolated snapshot: `data/checks/run-k415klc4`; source and snapshot protected
  fixture/result hashes unchanged. No production `.env` or personal data loaded.
- Regression coverage relates to T-LLM, T-SEC, T-LEDGER, T-CLOCK, T-ID and gate/action
  boundaries; passing these tests is not acceptance of every broader test-plan claim.
- `graphify update .` completed: 3,863 nodes, 8,587 edges. Optional SQL extraction
  unavailable because `tree_sitter_sql` is not installed; no LLM labeling was run.

## Invariants touched

I-1/I-3: validated data and fail-closed malformed output/clock/action handling.
I-2: executable adapters deferred; application-wide process ownership still has the
listed legacy gaps. I-4/I-10: hard-coded metadata and read-only licence re-derivation;
this is not completion of WP5 licence mathematics. I-6/I-7/I-9: bounded history,
UTC ordering, one context clock and no invented response ticks; full WP2 chronology
is outstanding. I-8: caller-owned serialized appends, preserved old bytes/triggers.
I-14/I-16: current JSON-cache validation and atomic cache/exposure writes; full WP3
redaction/transport/accounting acceptance remains outstanding. I-18/I-19: synthetic
isolated tests, secret files excluded. Web restriction invariants were not relaxed.

## Deviations and assumptions

DOC-A lower-authority prose was corrected to match the existing draft foreign key:
validate in memory, ledger, proposal, draft, commit, then dispatch. CONTRACT is unchanged.
No automatic action path is claimed production-ready from this checkpoint.

Remaining engineering work independent of approval:

1. Complete Examiner ownership of replay/Executor drift updates without widening the
   Executor allowlist; preserve immediate conservative handling of corrections.
2. Canonicalize new replay CUSUM payloads (`cusum`, `kind`), family-shift payloads
   (currently `alarm_type`) and compact resolver outcome payloads (currently includes
   `details`/`observed_at`), with regressions and historical read compatibility.
3. Extend clock scan regressions to callable aliases and dynamic/indirect imports.
4. Re-run the required checks after those repairs and the approved admin-command fix.

## Contract change request: CCR-F, typed administrative commands

**What:** clarify the API-to-Examiner command boundary for habit denial and explicit
exam requests. Proposed design: API persists only a validated, typed administrative
command; Examiner consumes it and owns all `habits`/`exam_runs` writes. Any new command
table, allowed API write and request/status schema must be approved explicitly.

**Why:** CONTRACT section 3 permits API writes only to `user_responses`, while section 9
requires habit denial and exam-run endpoints. Current routes bypass that boundary.
Approving WP0/WP1 implementation did not amend the contract. This is the previously
recorded CCR-F, not a new permission requirement invented during implementation.

**Invariants:** process authority in section 3, I-1/I-2/I-3/I-5 and the HTTP contract.
Exam verdicts remain computed by code; no LLM receives tools or credentials.

**Alternatives:** a human may explicitly authorize narrowly defined role delegation,
or remove/defer those mutation endpoints. Unrestricted API connections or broadening
API writes to Examiner tables are not accepted implicitly.

**Required next action:** human ruling and human-authored CONTRACT clarification under
section 13, then implementation and negative authority tests. No contract edit was made.

## New dependencies

None. No new network destination or credential.

## LLM cost incurred

Zero application LLM/Tavily calls during these isolated checks. This does not measure
or report the coding assistant session's own credit usage.

## Open questions and suggested next step

Resolve CCR-F, finish the explicitly listed engineering gaps, and repeat acceptance
on this branch. Do not mark WP1 complete, start WP2, merge or publish from this report.
