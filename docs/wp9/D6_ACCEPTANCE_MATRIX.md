# D6 Acceptance Matrix

Final D6 completion tree: `main` at the repository root, based on `00a1570`. The earlier
`phase-9-d6-api-frontend` worktree is the historical milestone. "Pending" means no
end-to-end evidence has been recorded; a unit test alone does not satisfy browser or live
acceptance.

Evidence key:

- **OFFLINE** — `python scripts/check.py` on the final tree: **1462 passed, 2 deselected,
  0 failed**; ruff check and format clean, project mypy and `mypy --strict` on
  `core/` + `engine/` clean, protected fixture and published-result hashes unchanged.
- **BROWSER** — `cd frontend && npx playwright test --reporter=list`: **40 passed, 0 failed**
  against the built bundle on loopback with system Chrome, one isolated synthetic workspace
  per journey.
- **LIVE** — read-only Gmail setup and observation. The approved test account produced
  **1 ASK** and **167 watching** proposals; no Gmail write was performed; the Executor is
  unprovisioned; no paid model/Tavily call was made in the D6 live session.

| Plan item | Required evidence | Status |
|---|---|---|
| A09 Derived permission parity | API, Examiner and Executor agree at one cutoff; no explicit-approval promotion | Offline tests pass (OFFLINE; `test_gmail_evidence_provenance.py`, `test_wp6_followup_evidence.py`). Cross-surface agreement at one cutoff through HTTP remains **Pending** |
| A10 Response race | Concurrent accept/edit/reject, idempotent same request, typed conflict, truthful 202 | **Offline passed** (OFFLINE; `test_wp6_response_api.py`) |
| A11 Draft/edit/forward | Immutable bindings, address/content validation, separate forward recipient | Draft/edit/bind **offline passed**; forward **Blocked** — the forward allowlist is not configured, so forward is refused fail-closed |
| A12 Archive/trash/undo | Real before-state, duplicate/conflict/expired undo behavior | Conflict/expired-undo rules **offline passed**; physical archive/trash and undo against Gmail **Blocked (LIVE)** — no write manifest |
| A13 Holds and consent | No early autonomous send, fresh restriction check, cancellation has no effect | **Offline passed** (OFFLINE; gate, restriction and hold paths, plus the webfacts fail-closed `cap 0` test) |
| A14 Crash after effect | Durable attempt and reconciliation; no duplicate uncertain send | **Offline passed** (OFFLINE; `test_d6_replay_recovery.py`, spend `ambiguous` hold reporting in `test_api_endpoints.py`) |
| A15 Correction/drift restart | Owned correction, deduped alarm/demotion before next eligible effect | **Offline passed** (OFFLINE; drift/correction suites in the gate run) |
| A16 Gmail observation | Pagination, race/resync, MIME bounds, no body URL or attachment fetch | **Offline passed** (OFFLINE; D4 tests, `test_gmail_ingest.py`, `test_gmail_runtime.py`). **Live read-only passed** — the approved label cohort was observed through the real provider; one incoming synthetic message produced one ASK; the MIME parser accepts Gmail's decimal-string `historyId`; no body URL or attachment was fetched |
| A17 Gmail auth/revoke | Account/scope/state/revoke checks and role grant isolation | **Offline passed** (OFFLINE; `test_gmail_live_wiring.py`, owner/bind and per-role allowlist tests). **Live read-only passed** — fixed loopback consent, exact `gmail.readonly`, SHADOW registration, owner-only token ACL; no write grant |
| A18 Authorized real Gmail flow | Approved incoming cohort; only owner-approved operations; sanitized outcome | **Read-only pass:** one incoming synthetic email observed and surfaced as an ASK; no body or account identifiers published. **Archive/undo/reply/forward Blocked** — no exact write manifest and no Executor write grant |
| A19 Tavily guard/accounting | Guard, budget/log failure, cache/TTL, outage baseline | **Offline passed** (OFFLINE; guard/TTL, IPC timeout, no-auto-retry). **No new Tavily call in D6**; cumulative D5 is 8 confirmed credits + 1 `ambiguous` hold = **11 usable**. The hold stays counted and is never re-sent |
| A20 Tavily restrictions/citations | Monotonic restriction behavior and source-backed uncertainty | **Offline passed** (OFFLINE; D5 `test_web_failure_fails_closed`, citation rendering in `VerificationCard`). No live Tavily card is claimed for the cold-start live item |
| A21 Extract | Show unavailable unless independently verified and accepted | **Passed as unavailable** — Extract is not claimed; unverified fields are not shown as supported |
| A22 Browser workflow | Detail/review/status/undo, invalidation, refresh/navigation/multi-tab | **Passed (BROWSER 40)** — `07-golden-path`, `02-routes`, `06-session-isolation`; durable request, conflict and undo states are covered |
| A23 Honest navigation | Discoverable destinations; truthful mode/readiness/unavailable states | **Passed (BROWSER 40)** — nine visible More destinations, active states, honest legacy deep-link fallbacks; no fake boards |
| A24 Accessibility/content safety | Keyboard, focus, responsive layout, escaped content, safe links, clean console | **Passed (BROWSER 40)** — keyboard-only review, visible focus, accessible names, announced errors, reduced motion, 360/390/768/1440, measured 44px controls, zero console errors, no off-origin request, production bundle verified |
| A25 Reports/claims | Hand counts, exact scope, zero cohorts unavailable, measured cost/provenance | **Offline passed** (OFFLINE; scope/denominator, intended vs confirmed, spend unavailable is not zero) |
| D6 owner isolation | Every private route scoped to verified owner grants | **Offline passed** (OFFLINE; 401 off-loopback, 401 wrong token, 403 authenticated without grant, 503 unconfigured) |
| D6 worker isolation | Dotenv-safe bootstrap, exact child env, role-owned loops/readiness | **Offline passed** (OFFLINE; real Windows children, synthetic canary, per-role allowlists, tick-derived readiness) |
| D6 frontend usability | Plain language, real API, loading/error/empty states, visual review | **Passed automated (BROWSER 40)** plus desktop/mobile screenshots. The Taste inspector itself did not complete successfully, so no successful inspector run is claimed |
| D6 replay durability | Versioned commands and durable receipts with restart-safe projection | **Offline passed** (OFFLINE; `test_d6_replay_controls.py`, `test_d6_replay_recovery.py`, no `clock_state` writer). The live supervisor is started with `serve-live` / `--gmail-runtime` |
| D6 budget | Cumulative Nebius / 20 Tavily credits including prior accounting | **No new paid calls in D6.** Cumulative D5: Nebius confirmed $0.005005 across per-model scopes; Tavily **11 usable** after 8 confirmed credits and 1 ambiguous hold. No fresh allowance |
| D6 Connect apps | Visible entry point, official icons, Gmail read-only consent, Calendar/Drive planned, API holds no Google credential | **Passed (BROWSER 08 + LIVE)** — the chooser shows Gmail connected, Calendar/Drive planned; the API receives status only; the setup child/token remain local |
| D6 live read-only demo | One incoming email observed, dashboard review, no write, no invented data | **Passed (LIVE)** — one incoming synthetic message produced 1 ASK; 167 watching proposals come from recorded history; no Gmail write, no paid call, no fake rows |

Do not mark an item passed without the exact command, exit status, fixture or cohort identity,
and saved evidence location in `docs/reports/phase-9-d6.md`.

**Live-acceptance note.** A read-only approval never authorizes send, forward, trash or archive.
Those require the exact operation manifest (account, cohort, action, recipient where relevant,
reviewed body hash, request identity, applicable restrictions, operation limit) and the owner's
approval of each write. An ambiguous send is not retried automatically. Implementation readiness
and live acceptance are reported separately and neither implies the other.
