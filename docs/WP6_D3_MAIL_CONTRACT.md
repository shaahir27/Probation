# D3 controlled mail and review contract

This is the owner-approved email D3 slice of WP6, on top of D2 at
`200ab938ff0986bdbb96005cd47bcc70dcfb1fb0`. It does not close whole WP6,
Gmail connectivity, production authentication or the browser acceptance gate.

## Review and authority

The server receives an explicitly injected owner and SourceGrant; absence denies.
Source identity is never authentication. A grant binds source, connection, account
and sending From. The server constructs the exact reviewed payload from the known
source, action, parameters, stored validated draft, recipient, native IDs and
restriction revision. Accept/Edit/Reject semantics also enter the hash. One initial
valid decision wins atomically. Stable retries return the existing intent; a changed
payload conflicts. An undo is a separate immutable request against an existing action.

`POST /api/queue/{id}/review` returns the version-v2 review and hash;
`POST /api/queue/{id}/respond` and `POST /api/actions/{id}/undo` return 202 for
durable intent. `GET /api/responses/{request_id}` distinguishes request consumption
from action/attempt effect state. A consumed receipt does not claim a send succeeded.
Existing clients must adopt the v2 payload/hash and injected owner context before
using these mutations. D6 owns frontend adaptation. Schema readiness failures are
503; missing owner context is 403. There is no synthetic production login fallback.

Explicit authority is for exactly the reviewed operation and can work at licence 0.
It does not promote autonomous permission. Every operation rechecks hard constraints,
account/source identity, restrictions and immutable content. Autonomous operations
add current D2-derived evidence/exam/expiry/alarm permission and actual conditional
caps; saved proposal caps do not authorize execution. Pending drift or negative
controls deny. Resume clears only its exact pause scope and never a revocation.

## Effects and rollback limits

Archive removes INBOX only if present. Trash adds TRASH only if absent. Before-state
and per-label revisions are durable before dispatch. Undo reverses only Probation's
actual changes within the configured window measured from confirmed execution.
Unrelated labels survive; an intervening remove/reapply of a touched label conflicts.
Reply uses the original sender, approved owner From, original thread/native reference
and validated stored body. Explicit approval sends immediately. Only a qualifying
autonomous reply holds for the configured ten minutes and can be cancelled before
send. Sent reply/forward has no recall promise.

The fake-provider protocol journals a stable operation ID and payload hash atomically
with its effect. A dispatched or unknown attempt is reconciliation-only; it cannot
create an alternate send attempt. Only definitive no-effect proof becomes FAILED.
Ambiguous results remain visibly `needs_reconciliation`. Provider-side support and
native reconciliation are D4 obligations; the local protocol is not a Gmail guarantee.

## Restricted forward (approved decision)

Forward is explicit-only. The owner supplies one recipient from an injected controlled
allowlist, empty by default. From is the owner grant. CC/BCC, attachments (including
singular attachment flags), arbitrary recipients and autonomous forward are denied.
The server combines the validated introduction with the exact source quotation and
requires an exact final-body approval; editing or omitting the quote fails. The final
body is at most 4,800 characters, without silent truncation. Source/native identity,
recipient and all reviewed content are rechecked at execution. Tests use controlled
synthetic addresses; no real forwarding or account provisioning was performed.

## Storage and runtime

`migrate_lifecycle` is bootstrap-only, atomic and rerunnable. It extends responses and
actions, adds immutable command intents/events plus role-owned receipts/attempts, and
upgrades proposal uniqueness for linked Brain followups. Workers must be stopped for
migration. Retain the ledger and provider journals during repair; restoring an old
database and blindly replaying dispatched operations is unsafe.

Outcome events and canonical ledger summaries commit together. Rejection is a strong
disagreement without an invented training label; corrections monitor drift and never
become agreement votes. Permission evidence has at most one genuine vote per situation.
Frozen exam history copies bounded canonical events and minimal inert cancelled-action
references, not operational approval bodies, write capabilities or execution attempts.

The bounded coordinator accepts separate permanently role-bound connections and
role callbacks. It carries no provider credentials. Real observation polling, process
supervision, auth lifecycle and connector grants remain D4/WP12 work. Missing supplied
Brain snapshots leaves followups pending rather than fabricating a model prediction.
