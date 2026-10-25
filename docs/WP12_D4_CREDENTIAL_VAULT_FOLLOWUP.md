# WP12 D4 credential-vault migration follow-up (work package)

**Status: PROPOSED — NOT AUTHORIZED, NOT STARTED.**
This document is a plan for owner approval. No code, dependency, OS capability, account,
network destination or configuration change described here has been made. Nothing in it is
evidence that a vault, an OS identity split or a rotation path exists. `docs/reports/phase-6-d4.md`
("Credential-vault migration follow-up") names this work; this file is the concrete package behind
that paragraph and nothing more.

Authority and citations: `docs/CONTRACT.md` I-2 (only the Executor performs side-effects; write
credentials stay inside its trusted deployment boundary); FP-D4 (protected OS credential store or
deployment secret manager, with refresh/rotation/revocation and provisioning; "no new dependency
is approved incidentally") and FP-D6 (write-grant callback/exchange/refresh inside the Executor
boundary, observation grants separate), both as recorded in
`docs/CONTRACT_AMENDMENT_2026-10-22.md` and `docs/FULL_PRODUCT_SPEC.md` section 5.1;
`docs/SECURITY_PRIVACY.md` section 2 (trust boundaries), section 3 T7 (credential theft or
over-privilege), section 4.1 class A (secrets), section 4.5;
`docs/WP12_D4_GMAIL_CONTRACT.md` section 5; and `docs/FULL_PRODUCT_SPEC.md` section 5.3.

---

## 1. Objective and non-goals

### 1.1 Objective

Replace per-process environment injection plus a plaintext refresh file with **per-role OS
identities and a protected credential vault**, so that the read role cannot obtain, decrypt or
exercise the write role's grant even when both run on the same Windows machine, and so that
refresh, rotation, revocation and re-consent have a specified, auditable lifecycle.

Exit condition in one sentence: an attacker holding code execution **in the reader process under
the reader identity** must fail to read or decrypt the write role's secret material, and that
failure must be demonstrated by a test, not asserted by review.

### 1.2 What exists today (facts, not aspiration)

| Mechanism | Location | Property it actually provides |
| --- | --- | --- |
| Role-bound credential providers, allowlisted child env | `backend/src/probation/connectors/credentials.py`, `credentials_state.py::build_child_env` | A child process receives exactly one grant variable; naming a sibling grant is refused (`foreign_grant_not_allowed_in_child`). Proves the app did not hand the write grant to the reader. |
| Plaintext refresh file behind an owner-only ACL | `credentials_state.py::RefreshTokenStore`, `connectors/acl.py` (`apply_owner_only`, `verify_owner_only`) | The file is readable only by the owner SID; ACL failure denies startup. It is **not** encrypted at rest and every process of that owner SID can read it. |
| Generation guard, no token column | `db/gmail.sql` `gmail_credential_state`, `generation`/`credential_ref` | A stale refresh cannot overwrite newer state; the metadata store holds scopes and times only. |
| Separate private store | `db/gmail.sql`, `db/gmail_store.py` | Connector bookkeeping is not in the engine DB and cannot widen `CONTRACT.md` section 3 role rows. |

### 1.3 Non-goals

- No change to `CONTRACT.md`, engine schema, ledger format or ledger kinds.
- No new Gmail capability, scope or endpoint; no live account access in this package's tests.
- No public/multi-tenant OAuth hosting; no Google verification or security assessment.
- Not a substitute for Google's own controls: token-level read/write separation stays
  "TOKEN-LEVEL ONLY" (`docs/WP12_D4_GMAIL_CONTRACT.md` section 1, C10).
- Does not defend against a local administrator, kernel-level malware or physical access. That
  limitation is stated in section 7, not engineered away.

---

## 2. Why same-user isolation is not isolation

`docs/WP12_D4_GMAIL_CONTRACT.md` section 5 already records the honest limit: *"Same-user process
isolation proves only that the application did not provision the write grant to the reader."*
Concretely, on today's profile:

1. Any process running as the owner can read `%PROBATION%\data\private\...\<ref>.refresh`
   (plaintext), because the ACL grants that SID.
2. Any process of the owner can enumerate environment variables of its own children, and can
   start a process with any grant it holds.
3. The only barrier between the reader and the write grant is application logic plus which
   variable the supervisor chose to pass — not an OS authorization boundary.

That is acceptable for a single-user demo where the code is trusted. It is not what I-2 and FP-D6
mean by "trusted deployment boundary" once the observation loop, the executor and the API run as
separate always-on processes.

---

## 3. Target model

### 3.1 Roles, identities and secrets

| Role | Runtime | Holds | Needed secret (class A, `SECURITY_PRIVACY.md` 4.1) |
| --- | --- | --- | --- |
| `api` | Dashboard/query process | no target-app credentials | owner API key only |
| `engine` (brain, examiner, ingestor) | Local workers | no target-app credentials | LLM key (budgeted, separate concern) |
| `gmail-read` | Observation worker + read readiness | `gmail.readonly` grant | OAuth client (read app) + refresh token for read |
| `gmail-write` | Executor | `gmail.send`, `gmail.modify` (narrow) | OAuth client (write app) + refresh token for write |

Two **separate OAuth clients** (not one client with two tokens) keep client secrets and consent
screens distinct; scopes never appear in a single bundle. I-2 is satisfied by construction only if
the write identity is the only identity that can decrypt the write blob.

### 3.2 Identities

Preferred, in order, for a single Windows machine:

1. **Virtual service accounts** (`NT SERVICE\<ServiceName>`) if the roles are installed as Windows
   services — no password to manage, logon type restricted to service, SID stable. Requires the
   roles to actually be services (new install surface, part of the always-on runtime work).
2. **Dedicated local standard users** (`probation-read`, `probation-write`) with "Log on as a
   service"/"Log on as a batch job" rights as needed — works without a domain, but needs a
   credential lifecycle of its own (password rotation, no interactive logon).
3. **gMSA** (`DOMAIN\svc-probation-write$`) — passwordless and auditable, but requires Active
   Directory; not available on a stand-alone demo host.

All options require an interactive owner session for the OAuth loopback flow
(`gmail_auth.py` binds `127.0.0.1` only). The Executor's callback listener must run **as the write
identity**, while the browser runs as the owner; the loopback redirect still reaches it. This
ordering must be verified in the deployment test, not assumed.

### 3.3 Vault options (Windows, realistic)

| Option | What it gives | Trade-offs | Blocking question |
| --- | --- | --- | --- |
| **DPAPI, user scope** (`CryptProtectData` via `ctypes`, stdlib) | Ciphertext bound to the role's logon credentials; no new dependency; offline | Any process of the same identity decrypts; profile loss or password reset can make blobs unrecoverable; per-machine, no audit trail | Is a ctypes call to an OS crypto API an "OS capability" requiring FP-D4 approval? Assumed **yes** until approved. |
| **DPAPI-NG with a SID protection descriptor** (`NCryptProtectSecret`, descriptor e.g. `SID=<write SID>`) | Decryption requires the caller to hold the descriptor SID; a *different local user* fails even on the same machine; remote/AD descriptors available later | Windows 8.1+/10+ only; still no audit; administrator can change the descriptor; `ctypes` surface is larger and needs negative tests | Same approval question, plus: is DPAPI-NG in scope for the supported OS floor? |
| **Windows Credential Manager** (`CredWrite`/`CredRead`, generic credential) | Simple per-identity store, OS-managed; no plaintext file of ours | Blob limit (`CRED_MAX_CREDENTIAL_BLOB_SIZE`, 2560 bytes), no rotation/audit API, roams with the profile, awkward for services, historically readable by same-user tooling | Does the 2560-byte limit and profile roaming fit the token sizes and support model? |
| **Approved secret manager** (Azure Key Vault, HashiCorp Vault, 1Password Connect) | Central rotation, audit log, per-identity auth, revocation | New network destination (CONTRACT.md section 3 allowlist), new dependency/SDK, bootstrap credential problem (a secret to fetch secrets), availability and cost | **Blocked**: no destination or dependency is approved. Not usable until CONTRACT.md section 3 is amended and FP-D4 closes. |
| **Encrypted file + role-only ACL** (baseline, no OS crypto) | Smallest change: keep `RefreshTokenStore`, encrypt with a key held by DPAPI | Security equals DPAPI user scope; two layers of the same boundary | Fallback only; does not achieve cross-identity protection by itself. |

Recommended target: **DPAPI-NG SID descriptor per role**, with a DPAPI user-scope blob as the
compatibility path on older hosts, behind one `CredentialSource` implementation. The remote secret
manager stays the long-term answer and stays unapproved.

### 3.4 What "genuine isolation" means here

A test must show all four, on a real machine, with real OS calls:

1. The `gmail-read` identity can read its own material.
2. The `gmail-read` identity **cannot** read or decrypt the `gmail-write` blob (distinct error, not
   an application-level refusal).
3. The `engine` and `api` identities can read neither.
4. Moving the write blob into the reader's reach requires changing an OS object (ACL, DPAPI-NG
   descriptor, identity membership) — an action the OS records and the deployment test detects.

If any of these can only be shown by application logic, the control is not isolation and the
package must say so in the handoff.

---

## 4. Credential lifecycle

### 4.1 States and generations

`gmail_credential_state` already stores `credential_ref`, `role`, `generation`,
`granted_scopes`, `access_expires_at`, `refresh_updated_at`, `rotation_origin`, with a trigger
that refuses a regressing generation. The vault adds **ciphertext**, not new authority:

- One vault entry per `(credential_ref, role)`; the entry name is derived by code, never accepted
  from a caller or a model.
- `generation` in the store is the single ordering authority; the vault entry carries the same
  generation in its metadata so a mismatch fails closed (read refusal, capability disabled).
- Reads decrypt into `SecretMaterial` (existing type), are used once, and are never cached in a
  module-level variable or written to disk.

### 4.2 Refresh rotation

Google installed-app refresh tokens generally do **not** rotate per refresh; they can change on
re-consent, scope change or account change. The lifecycle is therefore provider-driven, not
scheduled:

1. Refresh happens only in the identity that owns the role (`gmail-read` or `gmail-write`).
2. On any returned refresh token that differs from the stored one, write the new value first,
   bump `generation`, then update `refresh_updated_at`/`rotation_origin`; a failure at any step
   aborts the refresh and disables the capability (I-3).
3. A refresh observed under an older generation is rejected (`StaleRefreshRejected`), as today.
4. A provider-side rotation of unknown origin (token changed without a local refresh) is treated
   as `rotation_origin='provider'` and logged; it never raises autonomy.

### 4.3 Revocation

- Local: delete the vault entry, mark the state row generation-invalid, set readiness
  `AUTH_REQUIRED`, stop dependent work. Pause/revoke precedence stays as implemented in
  `connectors/readiness.py` and `workers/gmail_observation.py` (revocation outranks pause).
- Provider: `POST https://oauth2.googleapis.com/revoke` from the owning identity only, after the
  local delete; the call is best-effort, and its failure does not resurrect the credential.
- A revoked credential is never replaced by another account or an app password.

### 4.4 Re-consent for Google Testing-mode seven-day expiry

In Testing publishing mode Google expires Gmail-scope refresh tokens after about seven days. The
package must make that visible instead of mysterious:

1. A refresh answered with `invalid_grant` sets `AUTH_REQUIRED` and records a safe code only.
2. Readiness surfaces "re-consent required" and the reason category, never the provider body.
3. The owner re-runs the loopback flow for that role; completion is verified (account identity,
   actual granted scopes) before the vault entry is replaced and `generation` bumps.
4. A seven-day wall clock must not be hard-coded as an expiry. The system reacts to the provider
   answer, not to a guessed timer; if a timer is added it can only *warn*, never grant.

### 4.5 Access tokens

Unchanged: access tokens live in process memory only, are never written to the vault, the store,
logs, prompts, command payloads or URLs. The vault stores the refresh token and the OAuth client
secret only.

### 4.6 Audit of rotation and revocation events

- Structured log fields: `credential_ref` (opaque), `role`, `generation`, `rotation_origin`,
  `outcome`, `safe_code`. Never token text, never lengths that narrow a guess.
- Store: `gmail_credential_state` is the durable record of generation and origin.
- **Ledger: no new kind.** `ledger.kind` is a frozen CHECK list in `db/schema.sql`; adding
  `credential_event` would change the ledger contract and is a contract change request, not a
  free step. Options: (a) keep rotation audit in the connector store and structured logs only;
  (b) request a ledger kind addition in a later phase; (c) reuse an existing kind (only with an
  owner decision, and only if the payload semantics stay honest). Default in this package: **(a)**.

---

## 5. Migration plan (ordered, idempotent, fail closed)

Each step has an explicit exit check and a rollback that does not require re-running an effect.
Nothing here starts before a written owner authorization that names this package.

**Step 0 — Authorization gate.** Owner approves: OS identities, the vault option (3.3), any new
dependency, and any new network destination. No approval, no step 1.

**Step 1 — Inventory and baseline.** Enumerate `credential_ref`s per role from
`gmail_credential_state`; record generation and `refresh_updated_at`; record the vault/target ACLs
of `data/private/`. No secret is printed, hashed into a committed file, or copied to a ticket.
Exit: an inventory artifact under `data/private/d4/` listing refs and generations only.

**Step 2 — Provision identities.** Create the two (or four) identities from 3.2; grant only the
logon rights each role needs; deny interactive logon for service identities. Exit: `whoami`-level
proof per identity recorded, and the ACL test matrix (section 6) passes for empty vault slots.

**Step 3 — Provision the vault.** Create one entry per `(credential_ref, role)` with the
DPAPI-NG descriptor naming that role's SID. Write a **synthetic** canary first and prove the
cross-identity read denial before any real token is stored. Exit: section 6 matrix green on
canaries.

**Step 4 — Code seam.** Add `VaultCredentialSource` implementing the existing `CredentialSource`
protocol (`credentials_state.py`); it returns `SecretMaterial` and nothing else. No caller outside
the owning process may construct it; the existing `build_child_env` path stays intact for
rollback. New code is inert until the flag in step 5 selects it.

**Step 5 — Dual-read (read role only).** Mode `dual`: try the vault, fall back to the environment
file; every fallback logs `vault_miss` with `credential_ref` and generation. Exit: two weeks with
zero `vault_miss` on the reader and no readiness regression.

**Step 6 — Dual-write.** On refresh, write the vault entry **and** the existing private file, both
before acknowledging the refresh; if either write fails, the refresh fails closed and the
capability is disabled. Exit: a forced vault write failure disables read readiness and does not
advance generation.

**Step 7 — Reader cutover.** Mode `vault` for `gmail-read`: environment fallback removed. Exit:
restart, refresh and a re-consent drill all succeed with the env variables absent.

**Step 8 — Executor cutover.** Repeat steps 5-7 for `gmail-write`, with the stricter rule that the
executor's readiness must be `AUTH_REQUIRED` (not silently degraded) on any vault error. Exit:
section 6 matrix green for the write blob, including a negative test from the reader identity.

**Step 9 — Retire the old path.** Delete plaintext refresh files (secure delete is best-effort;
record that limitation), remove `PROBATION_GMAIL_*` secret injection from every launcher, revoke
the provider grants that were issued to the retired client if the client changed, and keep the
flag defaulting to `vault` with no fallback.

**Feature flag.** `PROBATION_GMAIL_VAULT_MODE` in `{off, dual, vault}`, read at startup only,
validated against an allowlist; unknown values refuse startup. It can only restrict behaviour:
`vault` never falls back to `off` implicitly, and a missing or unreadable vault in `vault` mode is
a startup denial. Flag state is logged without secrets.

**Rollback.** `vault -> dual -> off`, in that order, with the plaintext file still present until
step 9. Rollback must not restore a token that the provider has since invalidated: after any
re-consent or revocation, rollback requires a fresh owner consent, because the old ciphertext may
be stale. Rollback is drilled once before step 9 and the drill is recorded.

---

## 6. Per-deployment ACL and vault tests

Readiness gate for every deployment (dev host, demo host, any future host). These are real OS
calls under real identities, so they are **integration/live** tests excluded from `make check`
(which must stay offline and secret-free) and required in the deployment checklist:

| ID | Actor | Action | Expected |
| --- | --- | --- | --- |
| VA-1 | `gmail-read` | read own vault entry | succeeds, generation matches store |
| VA-2 | `gmail-read` | open/decrypt `gmail-write` entry | OS denial (`E_ACCESSDENIED`/`NTE_BAD_KEY` class), not an app error |
| VA-3 | `engine` | read either entry | denied |
| VA-4 | `api` | read either entry | denied |
| VA-5 | any role | read the other role's `data/private/*.refresh` while rollback path is live | denied by ACL |
| VA-6 | `gmail-write` | refresh with a stale generation | refused, capability disabled |
| VA-7 | `gmail-write` | startup with vault unreadable | startup denial, no fallback |
| VA-8 | `gmail-read` | revoked grant | `AUTH_REQUIRED`, dependent work halted, no retry storm |
| VA-9 | `gmail-write` | provider returns a rotated refresh token | new generation persisted atomically, old entry unusable |
| VA-10 | operator | remove the role from the descriptor and retry VA-2 | still denied until the ACL/descriptor changes, and the change is observable |

VA-2/VA-10 are the tests that distinguish isolation from application policy; if they cannot be
made to fail closed, the package is not complete.

---

## 7. Acceptance evidence

Evidence artifacts stay under `data/private/d4/vault/<date>/` (gitignored, no secret text) or, for
aggregate results, `docs/results/` only after the existing protected-hash rules are respected.

| Evidence | Produced by | Pass criterion | Where |
| --- | --- | --- | --- |
| Identity map | `whoami /all`, ACL dump per path | each role has a distinct SID; no role is in another's group | private artifact |
| Vault crypto proof | VA-1..VA-2, VA-10 transcript | cross-identity denial is an OS error, not a Python check | private artifact |
| Lifecycle proof | VA-6..VA-9 transcripts | generation monotonic; revocation and `invalid_grant` disable exactly the affected capability | private artifact |
| Dual-read soak | structured log query `vault_miss` | zero misses for 14 days on the reader | log export |
| Dual-write failure | forced write failure test | refresh aborts, readiness disables, no generation bump | test log |
| Rollback drill | one `vault -> dual -> off -> on` cycle | no duplicated evidence, no stale token accepted, no effect replayed | drill record |
| Regression | `make check` on the final tree | existing suite green, protected hashes unchanged | check output |
| Honest limits | handoff report | same-user limit replaced by a stated admin limit, with the exact wording | `docs/reports/` |

---

## 8. Risks and open decisions

**Risks**

1. **Administrator equivalence.** A local administrator can take ownership, change the DPAPI-NG
   descriptor or read process memory. Isolation is between roles, not against the machine owner.
2. **Profile loss.** DPAPI blobs die with the service profile; a profile reset silently destroys
   the refresh token. Re-consent must be the documented recovery, not a hidden failure.
3. **Headless callback.** The loopback listener must run as the write identity while the browser
   runs as the owner; a service in session 0 may behave differently for the redirect.
4. **Testing-mode expiry.** Seven-day expiry will keep interrupting soak tests; a soak must either
   be short or accept a re-consent in the middle, recorded as such.
5. **Rollback staleness.** Rolling back to the env path after a rotation can resurrect an invalid
   token; the drill must prove the failure is detected and fails closed.
6. **Operational drift.** Two identities double the install surface: ACLs, logon rights, service
   registration, log locations. Every added surface needs an ACL test or the package adds risk.

**Open decisions (each needs an owner answer before implementation)**

- **OD-1** Approve the OS capability: DPAPI user scope, DPAPI-NG SID descriptor, or both. None is
  approved incidentally; a `ctypes` call is still a platform capability, not "no dependency".
- **OD-2** Approve identities: virtual service accounts, local users, or gMSA. The choice changes
  the install surface and the callback test.
- **OD-3** Approve or reject a remote secret manager. Until `CONTRACT.md` section 3 names the
  destination, no such client may be added.
- **OD-4** Rotation audit home: connector store + logs (default), or a contract change to add a
  ledger kind.
- **OD-5** Whether the rollback window may ever contain both a plaintext file and a vault entry
  (this package says yes, briefly, with dual-write and a deletion deadline).
- **OD-6** Supported Windows floor for DPAPI-NG.
- **OD-7** Whether the Executor may run as a service at all, given the interactive loopback flow.

---

## 9. Sequencing and estimate

| Phase | Work | Rough effort | Blocked by |
| --- | --- | --- | --- |
| V0 | Owner decisions OD-1..OD-7 | owner time | this document |
| V1 | Identities + ACL matrix on canaries (steps 1-3, 6) | 2-3 days | V0 |
| V2 | `VaultCredentialSource` + flag + dual-read/dual-write (steps 4-6) | 2-3 days | V1 |
| V3 | Reader/executor cutover + lifecycle drills (steps 7-8) | 2 days + soak | V2 |
| V4 | Retire env path, rollback drill, handoff (step 9, section 7) | 1-2 days | V3 |

No estimate here is a commitment, and no phase may begin before V0 is recorded in writing.

---

## 10. Authorization statement

This work package is **not authorized and not started**. It adds no dependency, no OS identity, no
vault, no network destination and no configuration. The current D4 profile remains: per-process
environment injection, a plaintext refresh file behind a verified owner-only ACL, generation-
guarded refresh, and the documented same-user limitation. Every claim in `docs/reports/phase-6-d4.md`
stands unchanged.
