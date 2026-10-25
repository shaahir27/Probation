# D4/D5 combined acceptance checkpoint

Date: 25 October 2026. Base: merged `main` at `6b6abd2`.
Status: corrected live Gmail authentication and cohort enumeration pass;
combined model/browser/action acceptance remains open for D6.
Owner requested that the correction be made directly on `main`.

## Scope and correction

Test the merged Gmail connector and D5 reader/web/gate seams without repeating
already accepted paid model calls or accessing unrelated mailbox bodies.

The connector used `labelId` in `users.messages.list`; Google's API requires
`labelIds`. The fake provider repeated the typo, allowing its cohort-isolation
tests to pass without checking the real HTTP contract. The new regression runs
the real connector and HTTP encoder against `httpx.MockTransport`, and checks
the native label parameter on both pages. It failed before the fix and passed
afterward. The history API's separate singular `labelId` parameter is unchanged.

Reference: [Google messages.list query parameters](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list).

Changed the connector parameter and the fake's message-list interpretation.
Clarified `.env.example` to require a native synthetic-cohort label ID. Strengthened
the live read assertion so an empty cohort cannot count as a successful read.
No dependency, credential, network destination, action capability or contract
change was introduced.

## Verification evidence

| Check | Result |
| --- | --- |
| Merged D4 connector + D5 pipeline/Executor/API/model/contract tests, before correction | 389 passed, 2 live tests deselected |
| New HTTP cohort/pagination regression before correction | Failed: missing `labelIds` |
| Read/HTTP tests after correction | 31 passed, 1 live test deselected |
| Existing frontend command tests | 3 passed |
| Frontend TypeScript and production build | Passed |
| Isolated synthetic API presentation check | Health, queue, item detail, web usage returned HTTP 200 |
| D5 card in isolated item-detail response | `d5.v1`, partial availability, one citation |
| Full repository check after correction | Passed: Ruff, format, application/strict mypy; 1316 passed, 2 live deselected; protected fixture/result hashes unchanged |
| Live Gmail authentication and identity | Passed in the initial configured run |
| Corrected live Gmail cohort enumeration | Passed after owner created the synthetic label |
| Independent live cohort-count check | Exactly 6 message references; zero body fetches and mail effects |
| Browser inspection of synthetic detail drawer | Confirmed old status display; D5 verification card and its citation absent |

The API presentation fixture uses synthetic source/proposal data and an actual
previously recorded D5 public verification card. It is not a live Gmail-to-model
run. No Executor or provider worker is launched. Its Webfacts usage remains zero.
Artifacts are local under `data/d4d5-acceptance/`.

## Live Gmail evidence

With owner authorization, an allowlisted local settings runner loads the required
Gmail configuration through Pydantic settings into process memory. It never
displays or copies `.env`, secret values or account identifiers. Pytest tracebacks
and captured output are suppressed; only outcomes and typed safe failure codes
are retained.

The corrected live authentication/identity test passed. The first corrected live
list test failed with `ProviderUnavailable` / `provider_status_400`: the configured
display name `PROBATION` did not refer to an existing native label. After the owner
created the label and populated six synthetic messages, the local runner resolved
that exact label name to its native ID in memory and the live read test passed
(1 passed, 18 non-live tests deselected). An independent enumeration confirmed
exactly six references. No message body was fetched and no mail effect occurred.

Name resolution exists in the ignored local acceptance runner only. Production
connector/runtime selection and the ordinary live tests expect native label IDs;
their configuration must use the native ID. No automatic production name resolver
is claimed. The accepted read check proves profile/identity and labelled reference
enumeration, not MIME ingestion, intent accuracy on these new messages or effects.

The owner screenshot shows all six under `in:sent` as well as INBOX/PROBATION.
The MIME adapter marks messages carrying `SENT` as `is_sent`, and the projection
excludes sent observations from decision situations. These self-sent messages
therefore establish labelled enumeration only. The next incoming-decision test
needs synthetic messages delivered by a separate authorized test sender, without
`SENT` on the receiving account's message.

The original two live passes reported before the cohort-filter correction do not
establish real Gmail cohort isolation. There have been no live sends, forwards,
archive/trash operations or undo operations in this checkpoint.

## Frontend acceptance gap

The backend returns `verification_card`, `verification_as_of` and current sender
verification from `/api/items/{proposal_id}`. The frontend queue inspection drawer
uses its queue row directly, never calls `getItemDetail`, and renders only the old
web status/source fields. The new card is therefore not integrated into that flow.
The isolated fixture was opened in Chrome with preview mode off, followed by Queue
and Inspect. The drawer displayed the old verification status and omitted the card
fields and citation returned by the item-detail API. This is D6 implementation
work. Actual card rendering and the complete live Gmail-to-model-to-browser
walkthrough are not accepted by this report. The temporary browser window and
local fixture servers are closed after inspection; no approval control was used.

## Safety, accounting and handoff

No new Nebius/Tavily calls were made; the D5 durable allowance and its unresolved
Tavily hold were retained. No ledger UPDATE/DELETE, fixture rewrite, mail-body URL
fetch, authority promotion or raw web exposure to the writer was introduced.
The unrelated root build-history changes and every other worktree were preserved.
The unused acceptance worktree was created before the owner's instruction to use
`main`; its clean state and base identity were verified, then that worktree and
branch were removed. All correction work is directly on `main`.

Implement and review the bounded D6 detail/card flow, then run the separately
scoped synthetic ingestion/model/browser and exact-action walkthrough before
claiming combined acceptance. No additional Nebius/Tavily allowance is inferred.
No deployment is included.
