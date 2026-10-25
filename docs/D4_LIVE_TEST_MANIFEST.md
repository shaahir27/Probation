# D4 live-test manifest — PREPARED, NOT AUTHORIZED, NOT RUN

Status: **dry run only.** No account has been accessed, no grant exchanged, no mail sent.
Nothing in this file authorises an action. The owner must authorise a concrete manifest
separately before any step below is performed (`OCT29_DEMO_BUILD_PLAN.md` §10.2).

Exact account and cohort identifiers are deliberately **not** in this file. They are held
privately at `data/private/d4/live_manifest.private.json` (gitignored, owner-only ACL).
This repository copy contains placeholders only.

## 1. Authorisation fields

| Field | Value |
| --- | --- |
| Account | `<OWNER-TEST-ACCOUNT>` — private only |
| Cohort | `<COHORT>` — explicit native message ids and/or one owner-provisioned label |
| Allowed action types | ARCHIVE, TRASH, REPLY, FORWARD (empty recipient allowlist by default), LEAVE |
| Undo | ARCHIVE/TRASH only, and only when `undo_history_proof` is `supported` at request time |
| Maximum operations | 8 total (2 archive, 1 archive-undo, 1 trash, 1 trash-undo, 1 reply, 1 forward, 1 negative) |
| Starting permission mode | Level 0 — explicit owner approval for every effect; no autonomy claimed |
| Distribution profile | Installed-app desktop, loopback redirect, Testing publishing mode |
| Callback | `http://127.0.0.1:<PORT>/oauth/callback` (port chosen at launch; never a public URL) |

## 2. Scopes

| Role | Scopes | Why |
| --- | --- | --- |
| Read worker | `gmail.readonly` | observation only; classified readonly by Google |
| Executor | `gmail.send` + `gmail.modify` | send; archive/trash and reconciliation. `gmail.modify` is a **restricted** scope |
| Forbidden | `https://mail.google.com/`, settings scopes, domain-wide delegation | never requested by this codebase |

## 3. Credential delivery (names only — never values)

Per-process environment injection, built from an explicit allowlist so a child can never
inherit both grants:

- Reader: `PROBATION_GMAIL_READ_CLIENT_ID`, `PROBATION_GMAIL_READ_CLIENT_SECRET`,
  `PROBATION_GMAIL_READ_REFRESH_TOKEN`, `PROBATION_GMAIL_READ_REDIRECT_PORT`
- Executor: `PROBATION_GMAIL_WRITE_CLIENT_ID`, `PROBATION_GMAIL_WRITE_CLIENT_SECRET`,
  `PROBATION_GMAIL_WRITE_REFRESH_TOKEN`, `PROBATION_GMAIL_WRITE_REDIRECT_PORT`
- Owner API credential: `PROBATION_OWNER_API_KEY` (separate from every Google credential)

Durable refresh state is written only under `data/private/` after `apply_owner_only` +
`verify_owner_only` succeed; access tokens stay in process memory. No token is stored in
the connector metadata DB, in command payloads, URLs, logs or prompts.

## 4. Estimated provider requests

| Step | Requests |
| --- | --- |
| Bootstrap anchor | 1 `users.getProfile` |
| Cohort enumeration | ⌈N / 100⌉ `users.messages.list` pages |
| Body fetch | 1 `users.messages.get?format=metadata` per selected message (N) |
| Catch-up | ⌈history / 100⌉ `users.history.list` pages, unfiltered, filtered locally |
| Snapshot per effect | 1 `messages.get` (+1 `history.list` on undo paths) |
| Verification per effect | 1 `messages.get` post-write |

With N = 25 selected messages the whole rehearsal is under 100 requests, well inside the
per-user quota for a single controlled run.

## 5. Ordered steps (each requires explicit authorisation)

1. Observe one approved inbound synthetic message; confirm the observation row's three
   timestamps differ and its provenance is recorded.
2. Produce a truthful proposal; obtain exact owner approval through the existing D3 review
   path (no shortcut, no forced promotion).
3. ARCHIVE, then verify the label delta. Undo only if `undo_history_proof` reports
   `supported`; otherwise record the capability refusal and stop that step.
4. TRASH, then restore under the same restriction.
5. Approve an edited REPLY; verify exactly one correctly threaded SENT message
   (`threadId`, `In-Reply-To`, `References`, matching subject).
6. FORWARD to an explicitly allowlisted recipient; confirm an empty allowlist refuses.
7. Pause and revoke; confirm the next affected effect is blocked and observation stops.
8. Simulate an ambiguous send (timeout); confirm `needs-reconciliation`, no automatic
   resend, and bounded SENT reconciliation.

## 6. Cleanup

- Restore any label Probation changed; leave the account as found.
- Disconnect the connection; delete `data/private/d4/*` refresh state.
- Revoke the OAuth grant at the provider for the test account.
- Retain only hashes and safe codes as evidence; delete raw native receipts.

## 7. Expected capability limitations (must be stated, not hidden)

- **C1 atomic conditional modify — unsupported.** Gmail has no precondition; the D3 CAS
  degrades to check-then-act. `conditional_write` readiness stays `unsupported`.
- **C3 history retention ≈ 7 days** collides with `undo_days = 7`, so undo late in its own
  window may be unprovable. The correct behaviour then is refusal, not a demonstration.
- **C8 send idempotency — not provided.** Unknown sends stay `needs-reconciliation`.
- **C9 attribution — impossible.** Unmatched history events stay unknown.
- **Testing-mode refresh tokens expire after about seven days**; reauthorisation is an
  operating step, not a bug.
- `gmail.modify` is restricted: Google verification/assessment obligations apply to any
  distribution beyond the test users of the Testing profile.

## 8. Separate authorisation required

Account access, grant exchange, any send, any quota spend and any recording of real
mailbox content each require their own approval. This manifest exists so that approval can
be specific; it is not approval.
