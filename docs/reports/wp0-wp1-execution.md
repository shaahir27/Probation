# WP0 / WP1 execution record

Status: WP0 implemented, verified and committed (`c92131c`); WP1 implementation in progress.
Date: 22 October 2026. The approved scope is sections 4 and 5 of
`docs/CHANGES_IMPLEMENTATION_PLAN.md`; all numbered tasks remain acceptance requirements.
`docs/CONTRACT.md` is unchanged. Existing user changes are preserved.

## Ordered task list

1. WP0 baseline: record toolchain and working-tree hashes; run checks in an isolated
   synthetic copy without environment files, private data or live credentials.
2. WP0 hygiene: repair CLI contract tests and generation/export paths; implement the
   import/serve command contract and portable checks; correct typing and enforce strict
   checks for core/engine; ignore future local build logs and inventory tracked logs;
   qualify existing evaluation artifacts without replacing historical measurements.
3. WP0 handoff: verify fixture/result integrity, CLI behavior, lint, formatting, types
   and tests; write local logs and a dated handoff before the WP1 implementation slice.
4. WP1 regressions first: invalid schemas/outputs/cache payloads; action parsing and
   pack membership; atomic rollback/concurrent ledger writes; actual SQL target denial;
   proposal persistence ordering; correct ledger snapshots; monotonic clock/IDs.
5. WP1 implementation: strict Pydantic-backed output validation and job models, one
   parsed-action representation, role-bound storage/unit-of-work, descriptor/executor
   separation, canonical new ledger payloads and legacy readers, context clocks and
   deterministic semantic identifiers. Keep existing ledger bytes and schema intact
   unless a separately approved specification change permits an addition.
6. WP1 handoff: execute the relevant regression suites and complete required checks;
   verify source/test/output integrity; update Graphify and local construction logs;
   record evidence and every unresolved requirement explicitly.

## Decision handling

The user authorized the existing WP0/WP1 plan, not a contract amendment. Feedback
ownership, outcome-event migrations, level-zero explicit approval, body editing and
new connector/credential boundaries remain governed by the recorded D/FP decisions.
No such boundary is silently expanded here. For DOC-A, the existing draft foreign key
requires proposal insertion before draft insertion in the same transaction; the lower
authority prose will be corrected and the decision recorded. No new network service,
dependency, credential or personal-data access is included.

## Verification

WP0: `python scripts/check.py` passed Ruff lint/format, project mypy (119 modules),
strict core/engine mypy (21 modules), and 207 tests (two existing Typer warnings).
Source and snapshot fixture/result hashes were unchanged. Details and all nine task
dispositions are in `docs/reports/wp0-handoff-2026-10-22.md`.

WP1: substantive repairs and regressions are implemented. The final isolated checkpoint
passed 328 tests plus lint/format/types (130 project modules, 24 strict core/engine modules). This
does not close every numbered WP1 requirement. Current evidence and outstanding
audit items are in `docs/reports/wp1-progress-2026-10-22.md`; the numbered disposition
and contract change request are in `docs/reports/wp1-checkpoint-2026-10-22.md`. Existing D/FP
contract-dependent work remains gated until approved. No WP1 completion or full
product readiness is claimed.
