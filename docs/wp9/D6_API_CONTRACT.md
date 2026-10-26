# D6 API Contract

This contract freezes the API/UI boundary for D6. Existing routes retain their authority and safety semantics; additions are typed and versioned. `docs/CONTRACT.md` remains authoritative.

## Profiles and authentication

- `/health` is anonymous and reports API liveness only.
- `/api/bootstrap` is anonymous and returns only schema version, configured profile (`private` or explicitly configured `synthetic`), and whether authentication is required. It contains no account, grant, or private data.
- In private mode, the UI shows a masked owner-key field and the owner enters the already configured local API key. The value is held only in memory and sent as a same-origin bearer header; logout clears it. Do not persist it in browser storage.
- All private data routes and mutations require the configured owner credential. The UI sends it only in an Authorization header to same-origin `/api` requests; it is memory-only.
- Local owner sign-in does not depend on Gmail being connected. If the private connector store is absent, authentication returns an owner with no source grants; source-scoped views stay empty and Gmail connector routes report that setup is incomplete.
- Synthetic identity is selected by trusted server configuration, never by missing/invalid user token or a browser switch. It is bound to one synthetic workspace and cannot access Gmail/provider/admin credentials.
- Uniform errors use `{ "error": { "code": string, "message": string } }`. Validation errors never echo request values.

## Read surfaces

- `GET /api/queue`: unanswered owner decisions only; each item includes identifiers, current review binding/hash, action, plain-language gate/state, expiry where applicable, and supported operations.
- `GET /api/watching`: observations that have no actionable owner decision. Kept out of the answer/review queue.
- `GET /api/items/{id}`: bounded authorized item detail, explanation, validated draft when present, cited Webfacts card/status, and server-derived supported actions. Raw Tavily pages are never returned.
- `GET /api/actions`: authoritative action lifecycle (`pending`, `held`, `done`, `failed`, `cancelled`, `undone`, `unknown`) and truthful undo eligibility.
- `GET /api/permissions`: derived pair evidence, current restrictions/caps, and source cutoff. It does not accept permission edits.
- Reports, insights, boards, budgets, and `/api/web-facts` reflect actual bounded data, filters, confirmed/estimated/held costs, and citations. Empty/unavailable remains explicit.
- Health/readiness separates API liveness from role, model, embedding, connector, and sync readiness. Missing/stale worker status is unavailable.

## Mutations and status

- Review payloads use the existing review schemas: version `v2`, response `accept|reject|edit|leave`, optional `edited_action`, `edited_body`, and `forward_recipient`. Review returns `reviewed_payload` and `reviewed_payload_hash`. Edit invalidates the previous hash. Concurrent conflicting decisions return typed conflict; the first valid decision remains authoritative.
- Every mutation has a stable client request ID created before submission. Duplicate identical requests resolve to the same durable request; a changed payload with that ID conflicts.
- `202 Accepted` means queued, never complete. Response requests expose `/api/responses/{request_id}` as status URL. The UI looks up that durable request after refresh/reauthentication.
- An uncertain network result is retried only with the same ID and exact frozen payload after owner action. Never automatically retry a send or unknown effect.
- Undo uses the existing action-specific rules and states. Unsupported or expired undo is explicit.
- Replay intents are Examiner-owned durable commands. Supported controls: `start`, `pause`, `speed` with finite speeds `1`, `10`, or `100`. Scope/run identity is derived on the server. API submits an intent and reads state from durable terminal command receipts; while running, it projects simulated time from the saved receipt and operational clock. API does not advance replay. No new ledger kind or writer is introduced.

## Frozen replay wire contract

- `POST /api/replay/start` body `{"request_id": string}` → `202`
- `POST /api/replay/pause` body `{"request_id": string}` → `202`
- `POST /api/replay/speed` body `{"request_id": string, "speed": 1 | 10 | 100}` → `202`
- Each control responds `{"ok", "request_id", "status": "accepted", "status_url", "existing"}`. `202` means accepted for processing.
- Unknown fields, non-finite or unsupported speeds, and any client-supplied workspace, run, path or database identity are refused. `GET /api/replay/state` returns `{"running", "speed", "simulated_date", "mode", "available", "last_request_id"?, "open_decisions", "resumable", "resume_reason"?}`.
- A repeated command with the same `request_id` and payload resolves to the existing durable record and stays `202`. The same `request_id` with a different payload returns a typed `409`.
- Re-issuing a control after a clean stop starts a new run identity and advances from the durable checkpoint; it never restarts the scenario from zero. A command that lost its worker mid-run is reported `available: false` with `result not confirmed` until reconciliation, and is never auto-retried.

## Readiness surface

- `GET /api/readiness` is owner-authenticated, read-only, and never starts, migrates, or probes a provider.
- Role state comes from one supervisor status document beside the engine database (`core/runtime_status.py`). The supervisor writes it; the API only reads it.
- `{"available": bool, "reason": string|null, "clock_mode", "api_live", "generated_at", "stale", "age_seconds", "roles": [{"role","state","ready","code","last_tick_at"}], "replay": {...}}`.
- A missing, corrupt, unsupported-version or stale document reports every role unavailable. A live process with no reported successful tick is never ready.
- Ageing uses operational (wall) time through `core.clock.operational_clock()`, never simulated scenario time.

## Data, safety and compatibility

- Responses use strict typed models; unknown fields are rejected at mutation boundaries.
- Private reads and writes require owner scope. GET endpoints perform no provider calls, world construction, or action side effects.
- Web facts only inform/restrict; only source-backed validated fields reach the UI. Web facts never raise permission.
- Preserve distinct existing command-status response envelopes with explicit parsers; do not normalize them into a falsely compatible shape.
- Use the existing append-only ledger, history cutoffs, policy, gates, and derived licence logic. No licence is stored as user-editable truth.
- New persistence is allowed only for roles already authorized by the contract. Do not write legacy `clock_state`.
