# Phase 6b D5 handoff — guarded Nemotron and Tavily verification

Branch: `phase-6b-d5-nemotron-tavily`. Initial base:
`347b06e5794085366d190a35985377fdb8b725cc`, verified accepted main at creation.
Rebased onto accepted D4 commit `c423160` before final integrated verification.
Implementation is in `data/d5/worktree`. Owner approved both D5 plans on
25 October 2026. Selected D5 core plus Extract implementation and acceptance are complete; ready for
local review. This is not completion of all Phase 6b/WP7/WP13.

## Done

Search and Extract reserve durable physical-attempt budgets before HTTP and retain
unknown liability across restart. Missing accounting denies dispatch. Audit records
contain safe exact sent queries, options and source proof; rejected private text and
credentials are excluded. Daily/monthly and fixed-run budgets count attempts and
held/confirmed credits separately. Guard rejections and cache reuse do not spend.

Validated mail reading precedes email entity verification. Public-suffix domains,
bounded genuine-user familiarity and exact reviewed brand provenance drive the
trigger; raw mail URLs are reduced locally to domains. Three reviewed active brand
sets replace undocumented legacy authority. Regional domains are supported; report
hits require independent sources. Future/expired facts cannot influence decisions.

Opportunity fields must be copied from source mail. Independent Search plus reviewed
catalog provenance authorizes a safe official Extract; a caller boolean cannot.
Quarantined registered Nano jobs validate page-supported fields, uncertainty and
citations. Cache identity includes options/versions and preserves historical pages
on refresh. Raw pages/snippets never reach reader/writer/policy prompts.

Worker composition rechecks features at a decision cutoff after observations, derives
permission, and persists one proposal/draft unit. Web data cannot alter probabilities,
evidence or earned permission. Executor re-reads current restrictions immediately
before autonomy; exact explicit approval remains independent. GET endpoints expose
versioned typed cards and whole-population usage without provider calls.

## Files changed

- `web/{accounting,client,catalog,derive,types,verification,view}.py` and reviewed
  `config/brands.json`.
- `db/tavily_migration.py`, bootstrap hooks in `db/connection.py`; existing
  `tavily_calls` only, no additional role grants.
- `links/{extract,extractor_jobs,quarantine,sanitise}.py`, legacy Radar wrapper.
- `workers/{d5_verification,webfacts,restrictions,mail_execution}.py`, bounded
  HistoryView helpers and accurate feature cutoff provenance.
- Read routes `api/routes/{items,webfacts}.py`; no `api/app.py` change.
- `llm/client.py` read-only account catalog and supported Nano/Super instruction-only
  settings; versioned generation/cache/feature provenance and fitted-policy identity
  guard; current price evidence metadata; opt-in `scripts/d5_live.py`.
- Focused `test_d5_*` suites, stronger existing query/source/clock/batch fixtures,
  mail-reader version/model routing tests, updated registered-job count, and the
  D4 lifecycle baseline pin updated for D5's intentional restriction-only recheck.
  D5 Executor regressions remain enabled. Also updated the accepted implementation
  plan, web specification ordering and decision record.
  Exact paths/ownership: `docs/WP7_D5_IMPLEMENTATION_PLAN.md`.

## Tests

Final integrated gate after rebasing onto D4 commit `c423160`: PASS, exit 0.
**1315 tests passed, 2 deselected**, with two existing Typer/Click deprecation
warnings in 323.09 seconds. Ruff, formatting, application typing (241 files) and
strict core/engine typing (49 files) passed. Protected fixture/result hashes were
unchanged.
Portable command: `C:/Users/shaah/miniconda3/python.exe -B scripts/check.py` from D5.
It runs Ruff, application typing, strict core/engine typing and the whole offline
suite in a secret-free snapshot with protected source/snapshot fixture/result hashes.
Final integrated output is local `data/d5/worktree/data/d5-final-integrated-check.log`.
Earlier complete gates passed 964, then 965 tests before the generation correction.
The profile-focused run passed 38 tests in 5.91 seconds. The subsequent
versioned-prompt/writer/pipeline regression run passed 50 tests in 4.74 seconds.

First full run: 961 passed / 3 failed / 2 existing Typer/Click warnings in 564.58s.
The three compatibility findings were addressed without reducing assertions:

- Preserve historical `total_calls`, add guaranteed `physical_attempts` separately;
  legacy credits remain unverified and block new spending in that accounting store.
- Batch vetting requires persisted, bounded, schema-valid reader output. The batch
  test now proves zero pre-reader work, then genuine same-adapter offline vetting.
- Quota/audit time is operational UTC, not replay time. The clock test now proves
  rejection consumes no attempt, replay jumps cannot reset quotas, and operational
  day advancement restores only the daily allowance through actual fake dispatch.

The versioned-prompt full run then passed 968 tests and failed one historical
15-job count assertion. The registry intentionally has 17 jobs after adding v2
alongside v1. Update the exact count and assert both v2 keys; retain registry/model
set equality and schema compilation for every job. No safety assertion is removed.

Focused evidence includes 42 accounting tests, 49 entity/history/legacy/actual
Executor tests, and 63 Extract/card/legacy tests. These are overlapping lane runs,
not additive full-suite totals. Regressions first exposed missing behavior. They
cover races, restart/ambiguity, fractional usage, legacy migration/ledger preservation,
privacy, no-peeking, cache versions/TTL, forged provenance, injection isolation,
unsupported dates/fees/claims, uncited cards and unchanged baseline authority.

Graphify final AST-only refresh: **6,589 nodes / 17,937 edges / 322 communities**;
exit 0, local `data/d5-graphify-final.log`. Graph remains local/ignored;
no provider API cost.

## Invariants touched

Requirements evidence (paths relative to `backend/tests`):

| Requirement | Evidence |
| --- | --- |
| D5-01 contracts/ownership | Approved plan, `unit/test_d5_verification_contract.py`, preserved baseline hashes |
| D5-02 physical accounting | `unit/test_d5_accounting.py`, `unit/test_d5_accounting_boundaries.py` |
| D5-03 reader/entity/time | `unit/test_d5_entity.py`, `unit/test_d5_entity_history.py`, `integration/test_d5_pipeline.py` |
| D5-04 official Extract/quarantine | `unit/test_d5_extract.py`, `unit/test_d5_verification_contract.py`, separate live manifest |
| D5-05 configured models/versions | `unit/test_d5_models.py`, original WP3 regressions, fixed-allowance live manifest |
| D5-06 API/Executor seams | `integration/test_d5_api.py`, `integration/test_d5_execution.py`, D4/D6 obligations below |

I-1/I-3: registered schema-validated data only, classified failure and conservative
fallback. I-2: API remains read-only and Executor retains target-effect ownership.
I-6/I-7/I-8/I-9: HistoryView cutoffs, actual receipt times, atomic prospective
proposal persistence, immutable ledger and injected clocks. I-10/I-12: derived
authority and explicit-user provenance, no web agreement votes. I-14/I-15/I-16:
existing redaction/gateway/cache and durable shared Nebius allowance. I-21-I-26:
restriction-only web composition, guarded public queries, independent official
Search/Extract, quarantine, hard accounting and supported safe citations.

## Deviations and assumptions

The owner's reader-first selection supersedes the older section 5.1 web diagram.
Keep the conservative risk boolean separate from supported payment/free/unknown
display status. Existing evaluated prompt bytes and protected fixtures/results are
unchanged. The generation profile is versioned separately. Policies fitted with
another recorded feature identity fail closed; refit/exam proof is required before
using the new reader identity for autonomy. Source hashes are in root `data/d5/preflight/baseline.json`.

The three active reviewed brand sets do not satisfy the whole Phase 6b catalog
target. Unknown/missing user attribution remains unfamiliar. A small smoke cohort
measures only its declared cases; it cannot establish general model accuracy.

Provider redirect hops are not independently observable. Submitted/returned URL
identity and safety are validated; card provenance explicitly reports this limit.
Cache-hit totals are unavailable when not durably recorded as attempts; they are
not fabricated as zero. Known source fetch/expiry and live/cache provenance remain
available per card and entity.

## Contract change requests

None. `docs/CONTRACT.md` is unchanged. No new table grant or target effect.

## Migrations and rollback

Bootstrap-only `migrate_tavily_accounting()` is additive, repeatable and atomic on
failure. Preserve legacy rows and ledger bytes; unidentified legacy liability denies
new HTTP. New identities are immutable, delete/replace blocked, transitions forward.
After paid use, stop dispatch and retain all upgraded audit/reservation rows during
application rollback. Never restore an old unreserved client or delete/reset the
accounting database. Automatic unknown-charge release and post-paid schema downgrade
are intentionally absent.

## New dependencies

None. Existing publicsuffix2/httpx/Pydantic and registered jobs are reused.
Ponytail was installed at the owner's separate explicit request; no project
dependency was introduced. No browser/frontend implementation is claimed.

## LLM cost incurred and live acceptance

Initial live run: nine reconciled Nebius attempts, USD 0.00083652; one confirmed
Tavily credit; no held/unknown liability. Nano readers exhausted the 200-token
limit under default reasoning; the draft failed validation. These were safe
failures, not acceptance. The supported instruction-only generation correction
retains the original prompt bytes/token limits and all original spending.
The next instruction-only run returned all six schema-valid Nano forms with
zero-dispatch repeats, but only 2/6 declared intent matches. Money/personal-data
risk flags were conservative, including false positives. Writer v1 failed local
commitment validation and opportunity v1 copied the whole title as organiser.
At that point cumulative spend was USD 0.00129750, 18 Nebius attempts and two
Tavily credits, no unknown/held liability. This evidence is preserved in
`data/d5/live/manifest-2026-10-25T123936885284Z.json` in the original checkout.

The correction adds explicit writer.reply.v2 and reader.opportunity.v2, retaining
the same schemas/token limits, original prompt bytes and validation rules.
The v2 run corrected the organiser but Super returned a terminal provider status
(the original safe enum was not included in that run's manifest). Its request is
closed and cannot be silently resent. Search did discover NVIDIA's reviewed-domain
page, but the title omitted generic "Program" and was conservatively rejected.
Preserved evidence: `data/d5/live/manifest-2026-10-25T130329864765Z.json`; cumulative
20 Nebius attempts, USD 0.00269472 recorded including conservative estimated charge,
four Tavily credits. This is not successful writer/Extract acceptance.

The final matcher ignores only generic program/programme words; reviewed-domain,
distinctive-token and unique-candidate checks remain. The runner can exercise the
separate frozen deadline email as a distinct writer task, without reopening the
failed agenda request. It records both outcomes and separates conservative Nebius
estimates from reported-usage spending. Final cumulative totals follow below.
Authenticated model discovery listed the exact configured Nano, Super and Ultra;
listing alone does not prove inference. Published primary-source rates and their
limitations are recorded in `config/prices.json`; computed token costs are not an invoice.

| Gate | Current status |
| --- | --- |
| Offline conformance | PASS on integrated D4/D5: 1315 passed, 2 deselected; lint, formatting and both typing gates |
| Live Nemotron reader/writer | PASS: mail reader v4 matched 6/6 on configured Super; Nano v4 comparison matched 2/6. Super v2 produced a separate deadline draft. Six-case smoke only |
| Live Tavily Search | PASS: nine cumulative physical attempts, eight confirmed credits and one retained held credit; independently discovered reviewed-domain page |
| Live Extract/quarantined Nano | PASS: genuine Extract + Nano; partial cited card, then stricter cache-only revalidation with zero dispatch |
| Combined Gmail/browser | D4 commit `c423160` is merged into `main`; browser/card acceptance remains pending D6 |

Live runner: from root, set PYTHONPATH to D5 backend/src and invoke
`python -B data/d5/worktree/scripts/d5_live.py --allow-live`. It loads existing
application settings without copying `.env`. Fixed durable namespace:
`data/d5/live/accounting.db`, USD 1 aggregate Nebius / 20 Tavily-credit ceilings,
at most three physical attempts per logical job, sequential. No reset option.
The frozen six-case cohort, genuine caches, manifests and hashes remain local under
`data/d5/live/`. Public replay retains its existing cache-only default.

## Final live evidence

Genuine provider run: original-checkout
`data/d5/live/manifest-2026-10-25T131801450847Z.json`, runner exit 0.
The ordinary-request writer remains a closed failed request (duplicate guard denies
redispatch); the separate frozen deadline mail produced a locally valid Super v2
draft. Both outcomes remain recorded. No mail was sent. The earlier Nano v4 run
matched only 2/6 intents. A same-prompt comparison on configured Super returned
**6/6** on genuine provider responses in
`data/d5/live/manifest-2026-10-25T161915486384Z.json`. The fixed D5 mapping now
selects Super only for `reader.mail.v4`; other reader and quarantine jobs remain on
Nano, with no fallback. The normal-settings runner in
`data/d5/live/manifest-2026-10-25T162836843596Z.json` revalidated all six matches
from those exact Super cache entries. This small smoke cohort does not establish
general quality, calibrated policy performance, an exam pass or autonomous readiness.
Ultra is account-listed, not inferred; no escalation implementation is claimed.

Cumulative Nebius: **37 physical attempts, USD 0.00500496 recorded**, including
**one conservative estimated charge of USD 0.00135780**; USD 0.00364716 derives from
reported token usage at frozen published rates. No Nebius hold remains. These are
budget records, not a provider invoice. Tavily: **nine physical attempts, eight
confirmed credits plus one held credit**, one uncertain Extract batching attempt.
The hold remains durable; nothing was released/reset to make acceptance pass.
Total credited-plus-held exposure is nine, within the owner's20-credit allowance;
Nebius remains within USD1 including all earlier failed attempts.

Final claim review exposed a country selector copied as organiser and an application
opening date copied as programme start. New regressions first failed, then passed:
require date-role context; require a reviewed-organiser match for the official card;
require contiguous eligibility support without dropping source negation/qualifiers.
No model output or original live manifest was overwritten. Unsupported values become
unknown. The date/title/eligibility checks are conservative heuristics, not proof of
real-world truth; citations and partial/unknown status remain visible.

The earlier `data/d5/live/acceptance-final.json` remains a historical cache-only
revalidation bound to the 23-attempt manifest; it was not overwritten. The final
normal-settings run is `data/d5/live/manifest-2026-10-25T162836843596Z.json` and
confirms the v4 Super mapping, zero additional Nebius attempts, and all six cached
intent matches. Exact cumulative budget state and the one unresolved Tavily hold are
in that manifest and the durable accounting database. The final source/artifact
hash inventory is in root `data/d5/preflight/final-source-hashes.json`.

## D4/D6 integration obligations

D4 commit `c423160` is accepted and integrated on `main`. D4 calls
`predict_verified_email` with its Brain connection, shared live clock and
actual fitted snapshot; `email_verifier` receives a separate Webfacts connection
and registered consumer. All participating paid workers share the same accounting
authority. `persist_verified_email` re-derives permission before the Brain-owned
atomic commit. No Gmail connector/auth/store/runtime file was modified or copied.
The integrated offline suite exercises the D4/D5 restriction and Executor seam.
Owner-reported D4 live Gmail auth/read tests passed before its credential-loading
cleanup; the corrected live tests were not rerun here. Combined Gmail/browser
acceptance remains pending D6 UI/card verification.

D6 reads `/api/items/{proposal_id}`: `verification_version`, `verification_card`,
`verification_as_of` describe proposal-time knowledge; `current_sender_verification`
and `current_verification_as_of` describe later current sender knowledge. Existing
fields remain compatible. `/api/web-facts` adds version, physical attempts, confirmed
and held credits, unknown/legacy counts and expiry/origin. Page limit does not limit
totals. Neither GET dispatches a provider. Actual card rendering, navigation and
accessibility remain D6; no visible workflow is inferred from backend tests.

## Suggested next step

The D5 branch is ready for push to its feature branch and then local merge after its
integrated check and live smoke. Keep the durable accounting database and unresolved
Tavily hold. Combined Gmail/browser acceptance still awaits D6 UI/card verification.
No deployment is included.
