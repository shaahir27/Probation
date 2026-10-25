# D5 preflight and implementation plan

Status: selected D5 backend core plus Extract complete and accepted by its checks;
ready for owner review on 25 October 2026. Combined Gmail/browser remains D4/D6.
Date: 25 October 2026. Scope: required email core plus the separately accepted
Extract verification card; configured models; reader -> web -> restriction -> gate.

## Verified starting point and ownership

- Base: `347b06e5794085366d190a35985377fdb8b725cc`. Local main, cached
  origin/main and the GitHub connector's current `branches/main` response agree.
  Local main reflog records the accepted D3 fast-forward; `docs/reports/phase-5-d3.md`
  records owner acceptance. Shell HTTPS verification failed with
  `SEC_E_NO_CREDENTIALS`; the connected GitHub read supplied current remote evidence.
- Created `phase-6b-d5-nemotron-tavily` at `data/d5/worktree` directly from that
  exact commit. Neither target existed before creation. No D4 file was copied.
- D4 owns `phase-6-d4-gmail` in `data/wp12/worktree`, based on the same commit,
  with uncommitted connector/runtime/API work. Its interface document was read
  as an unfinished interface record, not accepted code or an integration dependency.
- Root's existing dirty `build_history/index.md` and
  `build_history/phase_04_engine_core_backtest/feature_policy_novelty_lb.md` remain
  untouched. WP4/WP5/WP6/WP9 worktrees remain intact.
- Local baseline: `data/d5/preflight/baseline.json` in the root checkout records
  all 62 protected fixture/result hashes, the two root construction-record hashes,
  D4 dirty-file hashes/status, branch and base identity. D4 may continue changing
  those files; subsequent differences must not be attributed to D5 automatically.
- Graphify query ran before source exploration. The existing graph supplied file
  locations; no raw broad source search or secret-file inspection was used.

## Configuration inspection

Application `Settings` loaded the existing root configuration with the D5 source on
PYTHONPATH. Output was restricted to key-presence booleans, public model IDs,
HTTPS hosts and configured caps. No secret was displayed, copied or written.

| Role | Configured candidate |
| --- | --- |
| Reader / synthesis | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| Writer / wording | `nvidia/nemotron-3-super-120b-a12b` |
| Exam edits | `nvidia/Nemotron-3-Ultra-550b-a55b` |

Both provider keys are present. Hosts are `api.tokenfactory.nebius.com` and
`api.tavily.com`, both HTTPS. Existing limits are USD 20, 100 Tavily calls/day and
800 Tavily credits/month; these are **not** the authorized D5 allowance.
These were the preflight values, not live acceptance. Subsequent account/model,
price and paid-test evidence is recorded in `docs/reports/phase-6b-d5.md`.

## Corrections and conflicts to resolve before implementation

1. **Ordering:** `TAVILY_AND_NEW_PACKS.md` section 5.1 says web vetting precedes
   the reader; `OCT29_DEMO_BUILD_PLAN.md` section 11.2 and the owner's selected
   D5 scope require validated reader first. Apply the owner's explicit selection,
   amend the lower specification diagram/text and record the decision. This needs
   no CONTRACT edit. Reader failure must prevent the dependent verification job.
2. **Fee semantics:** `PROMPTS.md` section 12 requires a broad conservative fee
   boolean, while `CHANGES_IMPLEMENTATION_PLAN.md` section 11.3 requires supported
   payment/free/unknown distinctions. Preserve the existing conservative risk
   boolean; expose a separately validated tri-state display fact with source support.
   A conservative flag is not proof that payment is required. Any changed prompt
   must get a new version; evaluated prompt assets remain immutable.
3. **Logging:** `BUILD_LOGGING_PROTOCOL.md` says construction logs are ignored and
   must never be committed, but Git already tracks historical build-history files.
   Do not untrack/rewrite them or edit root records. Keep D5 construction updates
   local to its own worktree and explicitly exclude them from any commit.
4. **Acceptance scope:** original Phase 6b includes a 50-entry catalog cut line and
   broader fixture-generation acceptance; WP7 includes Radar/Reading effects.
   D5's accepted email slice does not close those whole-phase requirements. Only
   individually reviewed entries may be active; inactive legacy entries prove nothing.
5. **Budget:** a per-world database or in-memory override cannot enforce this run's
   ceiling across resets. Use one persistent D5 accounting namespace outside resettable
   worlds, with shared authority for every participating paid worker. Preserve old
   charges and unresolved reservations; never initialize an unverifiable balance to zero.
6. **Time:** live response knowledge must retain actual fetch time. A decision that
   consumes it needs a cutoff at or after receipt, with bounded history/state recomputed
   as necessary. Do not silently reuse features whose identity binds another cutoff,
   or backdate provider observations to mail occurrence time.

No CONTRACT change request is proposed. Stop the affected work if implementation
reveals an actual need to change that file or widen its role/credential boundary.

## Confirmed source gaps

| Source | Inspected behavior needing repair |
| --- | --- |
| `web/client.py` | Missing connection permits Search; post-call logging swallows failures; retries lack separate reservations; Extract bypasses the budget check; missing usage becomes estimated confirmed usage; error bodies may escape. |
| `web/view.py` | `as_of` is accepted but unused; fetched time and TTL do not filter facts. |
| `workers/webfacts.py` | Quoted report query contradicts guard grammar; batch lacks bounded familiarity/validated-reader rules; caller cutoff can become fetch time. |
| `web/derive.py` | Handwritten suffix list and one-domain brand mapping need consistent installed public-suffix handling and reviewed provenance. |
| `links/extract.py` | Caller booleans authorize extraction; cached results ignore expiry; cache identity omits options; returned source URL is unchecked; failed persistence is swallowed. |
| `links/extractor_jobs.py` | Existing registered quarantined job provides a reusable foundation, including hash/time checks and some source support. Reuse it. |
| `packs/radar/out_of_band.py` | Existing helper requires supplied official domains but passes a boolean into Extract and compares raw deadline strings; do not introduce Radar actions for D5. |
| `api/routes/webfacts.py` | Totals are calculated from the last 50 displayed rows. |

These are inspection findings, not test results. The previously reported 833 passing
D3 tests are historical evidence, not a newly run D5 gate.

## Task list and acceptance

- [x] D5-01: Freeze typed query, attempt, Search-reference and card contracts; add
  failing money/race/no-peeking/privacy/quarantine/monotonicity regressions first.
- [x] D5-02: Add repeatable bootstrap migration extending existing Webfacts-owned
  `tavily_calls`; integer credit units, immutable attempt identity and forward-only
  state transitions. Reserve/commit before every physical dispatch; count daily
  attempts, monthly credit liability and the persistent 20-credit run ceiling
  atomically. Retain ambiguity across restart; audit failure denies further dispatch.
- [x] D5-03: Implement the email-only validated-reader trigger, bounded user-handled
  familiarity, consistent domains, safe query construction, reviewed domain sets,
  independent report deduplication, truthful outage/empty/cache provenance and TTL.
- [x] D5-04: Implement provenance-bound independent Search -> safe official Extract
  -> registered Nano quarantine -> supported typed cited card. Validate submitted
  and returned URLs; no mail-body URL fetch. Check cache options/versions/expiry,
  dates, fee uncertainty and injection isolation. Preserve other-family regressions.
- [x] D5-05: Compose reader -> Webfacts -> current restriction -> unchanged policy
  probabilities/gate -> immutable proposal/draft. Supply current restrictions
  through D3's existing Executor seam. Add versioned read contracts for item detail
  and complete usage totals; GET must never call a provider.
- [x] D5-06: Verify exact configured IDs, account capability and current official
  prices through approved boundaries; use shared gateway/redaction/schema/cache and
  existing durable Nebius SpendStore. All roles share a USD 1 aggregate D5 ceiling,
  including retries, unknown charges and unresolved reservations. At most three
  physical attempts per logical live job, sequential dispatch. No automatic upgrade.
- [x] D5-07: Run focused offline regressions, then
  `C:/Users/shaah/miniconda3/python.exe -B scripts/check.py` from the D5 worktree.
  Include application typing and strict core/engine typing; protect fixtures/results
  and keep default checks secret-free/offline. Do not weaken tests.
- [x] D5-08: Only after offline gates and price/account/budget readiness, run the
  frozen synthetic six-case cohort, actual Nano reads, Super draft, real Search and
  independent official Extract/Nano extraction. Repeat identical inputs to prove
  zero-dispatch cache hits. Stop before either run ceiling can be exceeded.
- [x] D5-09: Freeze actual model/prompt/schema/price/feature identities, attempts,
  cost/unknowns and artifact hashes; update local construction records and decisions;
  run AST-only `graphify update .`; write `docs/reports/phase-6b-d5.md` using the
  playbook template. Report offline, Nemotron, Search, Extract and combined
  Gmail/browser acceptance separately. Do not commit unless the required check passes.

Official transport references inspected during preflight:
[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract),
[Nebius quickstart](https://docs.tokenfactory.nebius.com/quickstart).
Both Tavily endpoint references document bearer authentication and `include_usage`.
Extract's batching/zero-usage semantics require conservative outstanding liability;
missing usage is distinct from reported zero. Current model price evidence and its limitations were verified before paid
inference and are frozen with the acceptance artifacts.

## Proposed exact write ownership

Existing paths below are relative to this worktree. New helpers/tests are bounded
to these names. Revisit this list before expanding it; never touch D4-owned files.

```text
backend/src/probation/web/client.py
backend/src/probation/web/query_guard.py
backend/src/probation/web/derive.py
backend/src/probation/web/view.py
backend/src/probation/web/accounting.py
backend/src/probation/web/types.py
backend/src/probation/web/catalog.py
backend/src/probation/web/verification.py
backend/src/probation/links/extract.py
backend/src/probation/links/sanitise.py
backend/src/probation/links/quarantine.py
backend/src/probation/links/extractor_jobs.py
backend/src/probation/workers/webfacts.py
backend/src/probation/workers/d5_verification.py
backend/src/probation/workers/brain.py
backend/src/probation/workers/prediction.py
backend/src/probation/workers/restrictions.py
backend/src/probation/engine/replay.py
backend/src/probation/core/history.py
backend/src/probation/core/history_queries.py
backend/src/probation/db/migrations.py
backend/src/probation/db/connection.py
backend/src/probation/db/tavily_migration.py
backend/src/probation/db/tavily.sql
backend/src/probation/api/routes/items.py
backend/src/probation/api/routes/webfacts.py
backend/src/probation/api/verification_models.py
backend/src/probation/llm/client.py
backend/src/probation/llm/catalog.py
backend/src/probation/llm/jobs.py
backend/src/probation/llm/consumers.py
backend/src/probation/llm/writer.py
backend/src/probation/llm/prompts/writer.reply.v2.md
backend/src/probation/llm/prompts/reader.opportunity.v2.md
backend/src/probation/llm/prompts/catalog_manifest.json
backend/src/probation/llm/generation.py
backend/src/probation/llm/gateway.py
backend/src/probation/llm/feature_identity.py
backend/src/probation/llm/feature_pipeline.py
backend/src/probation/engine/prediction.py
backend/src/probation/workers/mail_execution.py
backend/src/probation/config.py
backend/src/probation/packs/radar/out_of_band.py
backend/tests/unit/test_d5_accounting.py
backend/tests/unit/test_d5_accounting_boundaries.py
backend/tests/unit/test_d5_entity.py
backend/tests/unit/test_d5_entity_history.py
backend/tests/unit/test_d5_extract.py
backend/tests/unit/test_d5_verification_contract.py
backend/tests/unit/test_d5_models.py
backend/tests/unit/test_tavily_webfacts.py
backend/tests/unit/test_registry_and_workers.py
backend/tests/unit/test_wp1_context.py
backend/tests/unit/test_wp1_validation.py
backend/tests/unit/test_links_radar_reading.py
backend/tests/integration/test_d5_pipeline.py
backend/tests/integration/test_d5_api.py
backend/tests/integration/test_d5_execution.py
config/brands.json
config/prices.json
scripts/d5_live.py
docs/WP7_D5_IMPLEMENTATION_PLAN.md
docs/TAVILY_AND_NEW_PACKS.md
docs/DECISIONS_AND_OPEN_QUESTIONS.md
docs/reports/phase-6b-d5.md
build_history/index.md
build_history/phase_01_core_ledger_llm/feature_redaction_llm_client.md
build_history/phase_05_evidence_licences_gate_drift/feature_executor_worker_and_simworld.md
build_history/phase_06b_entity_facts_tavily/feature_entity_facts_and_tavily_vetting.md
build_history/phase_06b_entity_facts_tavily/phase_06b_summary.md
build_history/phase_08b_radar_reading_triage/feature_links_quarantine.md
build_history/phase_09_api_dashboard/feature_api_and_dashboard.md
```

Historical evaluated prompt files and protected fixture/result paths are read-only.
If a prompt change is necessary, name its new version and update this ownership list
before editing. Shared migration/composition/API paths have one integration owner;
bounded subagent work, if used after interface freeze, cannot overlap them.

Never edit `api/app.py`, Gmail auth/connectors/stores/runtime/provisioning, D4's
documents or any other worktree. D4 commit `c423160` is now accepted on `main`; the
integrated D5 worktree is rebased on it. Browser/card rendering remains D6. The owner
subsequently authorized pushing this D5 branch to GitHub before locally merging it.
No deployment, public paid endpoint or mail sending is authorized.

## Bounded live correction

The instruction-only run returned schema-valid mail forms (2/6 declared intent
matches, with conservative money/personal-data flags), but writer v1 promised
action without marking review and opportunity v1 copied the full programme name
as organiser. Add writer.reply.v2 and reader.opportunity.v2 with explicit field/
commitment rules; keep all original prompt files byte-identical, token limits and
validators unchanged. D5 explicitly selects the new versions. Existing callers
can still request v1; no fallback to another prompt is implicit.

Final cohort review traced four of six intent mismatches to ambiguous reader
definitions: three concrete imperative requests became `question`, and a periodic
newsletter became `fyi`. Preserve v3 and add reader.mail.v4 with explicit
action-vs-answer and recurring-digest distinctions. Select v4 in the mail pack and
the live runner; retain the same schema, validators, redaction and output limit.
Re-run the frozen cohort under the existing durable allowance before claiming an
accuracy improvement. V4 still scored 2/6 on configured Nano; the same v4 cohort
scored 6/6 on configured Super. Route only `reader.mail.v4` to configured
`MODEL_WRITER`; other reader/quarantine jobs remain on Nano. This is a fixed mapping,
not an automatic fallback. Revalidate the product mapping and retain the six-case
score as smoke evidence only.


Live source-title correction: Search returned the reviewed official NVIDIA page
with title "NVIDIA Graduate Fellowship | Research", omitting generic "Program".
Ignore only program/programme suffix words, retaining distinctive-token matching,
reviewed-domain proof and unique-candidate requirement. Negative controls reject
a different distinctive word and duplicate candidates. Keep old Search audit proof.
The runner records safe writer failure codes and can exercise two distinct eligible
mails from the unchanged frozen cohort (ordinary request and deadline). These are
separate tasks, not relabelled resends of a closed request; all liability remains
in the original allowance. Failed first-task acceptance remains visible.


Final claim-support correction: genuine Nano output copied a country as organiser
and application opening as programme start. Keep the actual raw response in
quarantine, reject unsupported roles, require contiguous eligibility quotation and
preserve source negations/qualifiers. The stronger final card is revalidated from
genuine caches with transport disabled and zero additional provider attempts.
No evaluated prompt or protected fixture/result was changed. The full final gate
and exact costs are authoritative in `docs/reports/phase-6b-d5.md`.
