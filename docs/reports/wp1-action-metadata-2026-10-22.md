# WP1 action-metadata handoff (original Phase 5 ownership)

Branch: `phase-1-wp1-trusted-foundation`. Date: 22 October 2026.
This separates the original Phase 5 action-metadata portion of the user-approved
WP1 slice from its Phase 1 storage/validation work. It does not start or accept
the later full licence/execution work packages.

## Done

`core/actions.py` provides one parsed action: canonical type and optional unchanged
parameter. Caps, loss and recallability use the type; policy/evidence keep the full
label. File/folder parameter case is preserved. Malformed/unknown/empty parameters,
foreign-pack actions and no-op execution/evidence pairs are rejected.

Decision-only descriptors expose each pack's catalog without transitively importing
executable modules. Executor validates the catalog before storing an action, keeps
immutable local intent and refuses effects with uncommitted intent or pending review.
Missing target/draft data remains ASK rather than creating invented parameters.

## Verification and invariants

`test_wp1_actions.py`, `test_wp1_action_storage.py`,
`test_wp1_execution_authority.py`, `test_wp1_replay_persistence.py` and
`test_wp1_drift_roles.py` cover T-CAPS/T-GATE/T-SEC/T-EXEC boundaries.
The final full checker passed 362 tests, lint/format, project types and strict
core/engine types; source/snapshot fixtures and historical results were unchanged.
I-1/I-3/I-4/I-8/I-10 are the relevant scoped invariants.

## Limits and handoff

Full policy/calibration, licence/exam quality, correction projection, holds/undo
windows and remote crash reconciliation remain WP4-WP6 acceptance. No live action
was performed. See `wp1-closure-2026-10-22.md` for the complete numbered WP1 audit,
approved authority extension, migration instructions and phase handoff.
