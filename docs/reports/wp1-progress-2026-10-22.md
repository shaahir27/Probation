# WP1 progress record

Status: verified implementation checkpoint; WP1 remains incomplete. WP0 is committed as `c92131c`.
Current branch: `phase-1-wp1-trusted-foundation`. Scope remains every numbered item in
section 5 of `docs/CHANGES_IMPLEMENTATION_PLAN.md`.

## Implemented and regression-tested

- Strict Pydantic job models and bounded schema compilation, including current
  validation on cache hits, finite numbers, enum/nullable/pattern/item constraints,
  boolean/integer separation and fail-closed unsupported schemas. Supported surface:
  `docs/LLM_SCHEMA_SUPPORT.md`.
- Parsed action types with case-preserving parameters, pack/family catalog checks,
  non-executable no-ops and rejection of invalid gate probabilities. No-op predictions
  do not enter evidence or acquire a derived licence.
- Actual SQLite write-target guards, read-only views, dedicated role connections,
  nested units of work, caller-owned ledger/cache writes and serialized ledger head
  allocation. The registry's transitive import test excludes executable pack modules.
- Atomic final proposal/ledger/draft persistence, immutable retries, and integration
  into replay and chain proposal storage. Replay commits before Executor dispatch;
  a second connection verifies durable complete target parameters/explanation.
  Missing draft/target data fails closed instead of fabricating executable data.
- Cache/exposure savepoint rollback and shared inference/web-budget timestamps.
  Executor re-derives evidence read-only instead of trusting a licence-cache row.
- Ledger metadata and verification from one read snapshot, including corruption.
  New proposal/licence payload names match DATA_MODEL; legacy licence readers accept
  prev_level. Existing ledger bytes are not migrated or rewritten.
- Scoped runtime clock, application request clock, UTC normalization, preserved
  microseconds, rejected backwards clocks/unsupported sub-microsecond precision,
  explicit UTC collation in the repaired query paths and an application-wide
  alias-aware direct-clock scan. Transport durations use core/clock.py only.
- Stable exam/case IDs with semantic input/version/seed/attempt components,
  idempotent retries and explicit attempt ordinals; stable habit/chain/resource IDs.

## Verification checkpoints

The final isolated `python scripts/check.py` run passed Ruff lint/format (187 files),
project mypy (130 modules), strict core/engine mypy (24 modules), and **328 tests**
(two existing Typer deprecation warnings). Fixture/result hashes were unchanged in
both source and snapshot. Snapshot: `data/checks/run-k415klc4`. This supersedes the
earlier 291/310/322-test checkpoints and targeted runs; code was frozen before this run.

All runtime tests use sanitized synthetic snapshots. No secret file, private export,
live provider or new dependency was used. Historical published measurements remain
unchanged. `graphify update .` completed after the final code changes: 3,863 nodes,
8,587 edges. Its optional SQL parser is unavailable; no dependency was installed.

## Still required before WP1 closure

1. Finish role enforcement in legacy paths. API habit denial writes `habits`, and
   the API exam endpoint invokes Examiner writes through an unrestricted connection.
   Executor still writes `drift_state`, owned by Examiner. CCR-F requires a human
   ruling on admin-command ownership before those API operations can satisfy both
   CONTRACT sections 3 and 9. Broadening the role allowlist is not an approved fix.
2. Complete canonical ledger payload coverage. Replay CUSUM alarms lack `cusum` and
   `kind`; family-shift alarms retain `alarm_type`; resolver outcome ledger entries
   still include detailed data beyond the documented compact payload. Existing ledger
   bytes must remain untouched. These are engineering gaps, not approval requests.
3. Extend the clock scanner beyond import aliases to callable assignment aliases,
   dynamic imports and indirect attribute access. API request-context, strict response
   chronology and independent exam/case/habit/chain identity regressions now pass.
   Full chronology and whole-replay equivalence remain WP2 work.

The numbered audit and concrete contract change request are in
`docs/reports/wp1-checkpoint-2026-10-22.md`. There are no known failing tests in the
final run. These remaining requirements prevent a WP1 completion claim.

DOC-A resolution: the approved WP1 plan follows the existing foreign key: generate
and validate a draft in memory; ledger, proposal, then draft in one transaction;
commit before dispatch. `docs/ENGINE_SPEC.md` lower-authority prose is corrected.
CONTRACT.md is unchanged. D/FP decisions on feedback ownership, outcome migrations,
administrative commands, live credentials and external services remain unresolved
for their affected future work; no approval is inferred from this implementation.
