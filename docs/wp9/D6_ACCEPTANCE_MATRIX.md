# D6 Acceptance Matrix

Track D6 acceptance using evidence from the D6 worktree. “Pending” means no end-to-end evidence has yet been recorded; a passing unit test alone does not satisfy browser or live acceptance.

| Plan item | Required evidence | Status |
|---|---|---|
| A09 Derived permission parity | API, Examiner, Executor agree at same cutoff; no explicit-approval promotion | Pending |
| A10 Response race | Concurrent accept/edit/reject, idempotent same request, typed conflict, truthful 202 | Pending |
| A11 Draft/edit/forward | Immutable bindings, address/content validation, separate forward recipient | Pending |
| A12 Archive/trash/undo | Real before-state, duplicate/conflict/expired undo behavior | Pending |
| A13 Holds and consent | No early autonomous send, fresh restriction check, cancellation has no effect | Pending |
| A14 Crash after effect | Durable attempt and reconciliation; no duplicate uncertain send | Pending |
| A15 Correction/drift restart | Owned correction, deduped alarm/demotion before next eligible effect | Pending |
| A16 Gmail observation | Pagination, race/resync, MIME bounds, no body URL or attachment fetch | Pending |
| A17 Gmail auth/revoke | Account/scope/state/revoke checks and role grant isolation | Pending |
| A18 Authorized real Gmail flow | Approved incoming synthetic cohort; only owner-approved operations; sanitized outcome | Pending; requires approved manifest |
| A19 Tavily guard/accounting | Guard, budget/log failure, cache/TTL, outage baseline | Pending |
| A20 Tavily restrictions/citations | Monotonic restriction behavior and source-backed uncertainty | Pending |
| A21 Extract | Show unavailable unless independently verified and accepted | Pending |
| A22 Browser workflow | Detail/review/status/undo, invalidation, refresh/navigation/multi-tab | Pending |
| A23 Honest navigation | Discoverable destinations; truthful mode/readiness/unavailable states | Pending |
| A24 Accessibility/content safety | Keyboard, focus, responsive layout, escaped content, safe links, clean console | Pending |
| A25 Reports/claims | Hand-counted scope, correct denominators, empty cohorts, measured cost/provenance | Pending |
| D6 owner isolation | Every private route is scoped to verified owner grants | In progress |
| D6 worker isolation | Dotenv-safe bootstrap, exact child env, role-owned loops/readiness | In progress |
| D6 frontend usability | Plain language, real API, loading/error/empty states, Taste/UI UX Pro Max review | In progress |
| D6 replay durability | Versioned commands and durable receipts with restart-safe state projection | In progress |
| D6 budget | Cumulative $1 Nebius / 20 Tavily credits including prior accounting | Pending final reconciliation |

Do not mark an item passed without the exact command, exit status, fixture or cohort identity, and saved evidence location in `docs/reports/phase-9-d6.md`.
