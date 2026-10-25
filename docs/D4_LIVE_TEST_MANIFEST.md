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

- Runtime connection identifier: `PROBATION_RUNTIME_GRANT="<connection_id>|<account_id>|<credential_ref>"`
- Role-scoped grants: `PROBATION_GMAIL_GRANT_<ROLE>_<REF>_<DIGEST>=json({"client_id": "...", "client_secret": "...", "refresh_token": "..."})`
  where `<ROLE>` is `READ` or `WRITE`, `<REF>` is the sanitized credential reference, and `<DIGEST>` is the 16-character SHA-256 digest of `<account_id>|<credential_ref>`.
- Operator consent token: `PROBATION_GMAIL_LIVE_CONSENT="scoped-authorization-granted"` (required for `--live` startup or running live tests).
- Explicit forward allowlist: `PROBATION_FORWARD_ALLOWLIST="recipient@domain.tld"`
- Owner API credential: `PROBATION_OWNER_API_KEY` (separate from every Google credential).
- Legacy/fallback individual env vars: `PROBATION_GMAIL_READ_CLIENT_ID`, `PROBATION_GMAIL_READ_CLIENT_SECRET`,
  `PROBATION_GMAIL_READ_REFRESH_TOKEN`, `PROBATION_GMAIL_READ_REDIRECT_PORT` (and executor equivalents).

Durable refresh state is written only under `data/private/` after `apply_owner_only` +
`verify_owner_only` succeed; access tokens stay in process memory. No token is stored in
the connector metadata DB, in command payloads, URLs, logs or prompts.

The helper script `python scripts/gmail_live_env.py` formats these environment variables
from private token files (`--format ps1`, `--format sh`, or `--format cmd`).

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

## 9. Operator runbook for Phase 7 (gated acceptance)

This runbook defines the exact sequence for live acceptance when owner consent is explicitly granted:

1. **Prerequisites**:
   - Google Cloud Console Desktop App OAuth client ID and client secret configured with scopes:
     `https://www.googleapis.com/auth/gmail.readonly`,
     `https://www.googleapis.com/auth/gmail.send`,
     `https://www.googleapis.com/auth/gmail.modify`.
   - Dedicated test Gmail account added to the OAuth Consent Screen test users list.
   - Operator consent explicitly declared:
     `export PROBATION_GMAIL_LIVE_CONSENT=scoped-authorization-granted` (Unix) or
     `$env:PROBATION_GMAIL_LIVE_CONSENT="scoped-authorization-granted"` (PowerShell).

2. **Step A: Initial OAuth authorization flow**:
   - Start the Probation API with `PROBATION_OWNER_API_KEY` and loopback authorization endpoint enabled.
   - Execute OAuth flow via `POST /api/connectors/gmail/auth/start` with PKCE and state binding.
   - Complete authorization in browser on loopback callback (`http://127.0.0.1:<PORT>/oauth/callback`).
   - Confirm returned account matches test account and granted scopes match requested scopes.
   - Durable tokens are saved under `data/private/` with verified owner-only ACL (`apply_owner_only`).

3. **Step B: Runtime environment configuration**:
   - Export runtime environment block using the helper:
     `python scripts/gmail_live_env.py --env-file data/private/d4/live_tokens.json --format ps1 | Invoke-Expression`
   - Verify environment variables:
     - `PROBATION_RUNTIME_GRANT`
     - `PROBATION_GMAIL_GRANT_READ_*`
     - `PROBATION_GMAIL_GRANT_WRITE_*`
     - `PROBATION_FORWARD_ALLOWLIST` (one authorized recipient only)

4. **Step C: Run live connector pytest suite**:
   - Execute gated live tests:
     `pytest -m live backend/tests/connectors/test_gmail_auth.py backend/tests/connectors/test_gmail_read.py`
   - Confirm token refresh, profile gateway lookup, and bounded message retrieval succeed.

5. **Step D: Live observation and controlled executor walkthrough**:
   - Launch runtime under `--live`:
     `python -m probation.workers.gmail_runtime --live`
   - Observe synthetic cohort message arrival; verify observation timestamps and payload storage under owner-only ACL.
   - Walk through the 8 manifest operations (Archive -> Undo, Trash -> Untrash, Reply, Forward to allowlisted recipient).
   - Verify reconciliation on simulated ambiguity.

6. **Step E: Teardown and credential cleanup**:
   - Pause and revoke connection via `POST /api/connectors/gmail/{connection_id}/revoke`.
   - Remove tokens from `data/private/` and unset environment variables.
   - Revoke application access in Google Account permissions.

