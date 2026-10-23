# CONTRACT

The rules and interfaces that **must never be broken**. If code and this file disagree, the code is wrong.

Status: v2 · Authority: highest · Change control: human approval only (section 13).

Amendment approved by the owner on 22 October 2026: D1-D9/CCR-A-G and DOC-A-C,
as recorded in [the amendment register](CONTRACT_AMENDMENT_2026-10-22.md).
This is the target contract; approval does not certify implementation or authorize
private-account access, new dependencies, provider spending or deployment.

---

## 1. Vocabulary (exact meanings)

| Term | Meaning |
|---|---|
| **Pack** | A plug-in connecting the engine to one kind of work (`mail`, `calendar`, `files`, `chains`, `radar`, `reading`) |
| **Family** | A decision type inside a pack, with a fixed action set (for example `email_action`) |
| **Situation** | One thing that arrived and may need a decision (a mail, an invite, a new file, a trigger) |
| **Clues (features)** | Numbers and labels describing a situation. Two kinds: *deterministic* (plain code) and *reader* (an LLM filling a strict form) |
| **Proposal** | The system's prediction for a situation: probabilities over actions plus a gate decision |
| **Outcome** | A time-bounded projection of immutable user-decision/footprint events; later corrections do not overwrite earlier knowledge |
| **Explicit approval** | Owner authorization for one exact reviewed operation; independent of the autonomous licence and never an increase to it |
| **Action** | A typed side-effect the Executor may perform (archive, move file, create draft, and so on) |
| **Class key** | A string naming a task type, built by the pack (for example `mail|request|known`) |
| **Licence** | Permission for one `(class_key, action)` pair at level 0-3, *derived* from evidence at the moment it is needed |
| **Ledger** | The append-only, hash-chained log of proposals, outcomes and actions |
| **Entity facts** | Public information about a domain or organisation gathered from the web (status, sources). Restriction-only (I-21) |
| **Strong / weak outcome** | Strong: directly observed (reply found, label seen, RSVP status, explicit user response). Weak: inferred (left alone, time-and-similarity links) |

Levels: **0** Watch, **1** Suggest, **2** Do with undo, **3** Do silently (reversible only).

---

## 2. Invariants

Each invariant has an ID. Tests reference these IDs (`TEST_PLAN.md`).

### Security and authority
- **I-1** LLM output is **data only**. An LLM never holds credentials, tools, file access or the ability to run commands. Every LLM output is parsed and validated against a schema before use.
- **I-2** Only the **Executor** performs side-effects on target systems. Write-grant callbacks, exchange, refresh and signing credentials stay inside its trusted deployment boundary. Observation grants remain separate; API/LLMs/external runtimes cannot hold or exercise target-app write credentials.
- **I-3** **Fail closed.** If featurization fails, the LLM is unreachable, validation fails, the clock is inconsistent or the budget is exhausted, the gate result is `ASK` or `SHADOW`. Never `EXECUTE*`.
- **I-4** The **hands-off rules** and the **level caps** (`ENGINE_SPEC.md` section 8 and `PACKS_SPEC.md`) are hard-coded in `caps.py` and `handsoff.py`. They are not configurable by the database, an LLM, or a user setting.
- **I-5** The **Examiner is not an LLM.** Exam questions may be LLM-written; verdicts are computed by code.

### Time and truth
- **I-6** **No peeking.** Any computation for a situation at time *t* may use only data with `known_at <= t`. History access goes **only** through `HistoryView(as_of=t)`.
- **I-7** A prospective proposal is committed to the ledger before its outcome event is recorded, and `proposal.proposed_at < outcome.known_at`. Preserve real microsecond ordering; never invent a later known time. Backfill can train eligible models and support separately labelled retrospective replay, but cannot qualify a live autonomous licence. Retrospective runs have separate ledger/run provenance and never impersonate real prior commitments.
- **I-8** The **ledger is append-only and hash-chained** (`DATA_MODEL.md` section 4). No UPDATE or DELETE on it, enforced by database triggers.
- **I-9** Engine code never calls the system clock directly. It uses the injectable `Clock` (`replay` or `live`).

### Evidence and licences
- **I-10** **Licences are derived, not stored as truth.** A licence is `level(class_key, action, as_of)` computed from evidence. Any cache has a time-to-live. Autonomous execution, including after a hold, re-derives it immediately before effect. Explicit owner approval is a separate one-operation authority checked under section 8; it never grants or increases a licence.
- **I-11** Level 2 and 3 licences use **strong outcomes only**. Level 1 may use strong and weak.
- **I-12** An executed action's silence is **not** evidence of agreement. Evidence comes from eligible user-handled/answered predictions, including the **audit holdout** (`ENGINE_SPEC.md` section 9). Count a decision at most once per proposal at its as-of cutoff. Explicit decision evidence is separate from execution success. Rejection is disagreement without an invented alternative training label. Undo and override feed drift/demotion, not agreement counts or policy action labels.
- **I-13** No **level 2 or 3** licence may be issued without a passed exam dated after the latest drift alarm (and after the latest family-shift alarm) for that `(class_key, action)`. Until then the level is at most 1.

### Privacy and cost
- **I-14** **Redaction before egress.** Text sent to any LLM first passes `redact()` (`PROMPTS.md` section 1). Every call is recorded in `exposure_log` with counts.
- **I-15** A **hard budget cap** is enforced in the LLM client. When estimated spend reaches the cap, the client raises `BudgetExceeded` and the system falls back per I-3.
- **I-16** LLM calls are **deterministic and cached**: temperature 0, key `(content_hash, prompt_id, prompt_version, model_id)`. Identical inputs never trigger a second call.

### Hygiene
- **I-17** **One code path** for synthetic and real data. No `if synthetic:` branches in engine code.
- **I-18** The public demo and the repo contain **synthetic data only**. Real exports live under gitignored `data/private/`.
- **I-19** Secrets are never committed, logged or sent to an LLM. `.env` is gitignored.
- **I-20** Every outward-facing action is **recallable-aware**: autonomous actions marked `recallable=False` use the hold queue (`HOLD_MINUTES`) at level 2 and cannot run silently. Exact explicit approval may execute immediately. Cancellation before effect and undo after effect are distinct; no post-send recall is promised.

### Web grounding (Tavily; CCR-1, see `TAVILY_AND_NEW_PACKS.md`)
- **I-21** **Web facts about entities may only restrict or inform.** They never raise a probability, cap, licence or evidence. The policy, evidence and licence modules MUST NOT import `web/`. Access is only through `WebFactsView`, which returns restriction-only types. (Content of an item the user saved is the user's own data and may be used as clues after quarantine extraction; it is not a "web fact about an entity".)
- **I-22** **Raw web text is untrusted.** Search snippets and extracted pages are never placed in a prompt that influences the gate and are never given to the writer. Only a **quarantined extractor** (strict schema, no tools) may read them; code validates its output.
- **I-23** **Tavily queries are built by code** from a closed set: registrable domains, brand tokens, reader-extracted `organiser_name` and `opportunity_name` that pass `web_query_guard`, and user-saved URLs for Extract. Never mail subjects or bodies, person names, addresses, or per-recipient URL parts. Every call is logged in `tavily_calls` with the exact query text.
- **I-24** **URLs found in mail bodies are never fetched or extracted.** Extract is used only on user-saved URLs and on official URLs discovered by Search.
- **I-25** **Tavily has a hard budget** (`TAVILY_MAX_CALLS_PER_DAY`, `TAVILY_MONTHLY_CREDIT_BUDGET`). On exhaustion or failure the system behaves as if no web facts exist.
- **I-26** **Citations or silence.** Anything shown to the user that derives from web content carries the source URLs from Tavily results; validators reject uncited claims.

---

## 3. Processes and permissions

| Process | Reads | Writes (tables) | Credentials | Network |
|---|---|---|---|---|
| `ingestor` | Sources (files or read-only APIs) | `sources`, `raw_items`, `situations` | Read-only source credentials | Only the source |
| `brain` | `situations`, `features`, history via `HistoryView` | `situations` (chain follow-up variants only), `features`, `llm_cache`, `proposals`, `drafts`, `exposure_log`, `ledger` (append) | **None** | Only the LLM endpoint |
| `resolver` | `raw_items`, `proposals`, `user_responses`, bounded event history | `outcome_events` (normal decisions/footprints/overrides only, append), `outcomes` (derived projection), resolver-owned `command_receipts`, `ledger` (append) | Read-only source credentials | Only the source |
| `examiner` | `proposals`, bounded outcome history, `raw_items`, typed admin requests | `licence_cache`, `exam_runs`, `exam_cases`, `drift_state`, `family_shift`, `habits`, `chains`, `class_stats`, `llm_cache`, `exposure_log`, `admin_commands` (status/results only), `drift_receipts` (append), examiner-owned `command_receipts`, `ledger` (append) | **None** | Only the LLM endpoint (for exam edits, exam re-reading and wording) |
| `webfacts` | `situations`, `web_facts`, `extractions` | `web_facts`, `tavily_calls`, `extractions`, `quarantine_outputs`, `llm_cache`, `exposure_log`, `ledger` (append) | **None** (a Tavily API key only) | Only `api.tavily.com` and the LLM endpoint (quarantined extractor) |
| `executor` | `proposals`, `drafts`, `user_responses`, `actions`, current restrictions and bounded evidence/exams/alarms | `actions`, `outcome_events` (own undo/cancel corrections only, append), executor-owned `command_receipts`, `ledger` (append) | **Write** credentials; execution-boundary auth/signing secrets | Only approved target apps/auth endpoints |
| `api` | All non-secret tables (read-only) | `user_responses` (immutable accept/reject/edit/undo requests), `admin_commands` and `command_requests` (validated initial intents only) | None | Serves authenticated owner/admin controls; no provider calls |

Rule: a process MUST NOT write to tables outside its row. Enforced by separate DB connection helpers per role (`db/access.py`).

Administrative requests are acknowledged with HTTP 202 and a stable request/status
reference. API cannot update/delete requests, drafts or worker results. Each typed
command has one designated consumer and row-level ownership; shared receipt tables
do not permit cross-role writes. Existing `admin_commands` remain the Examiner
queue; any later general command schema requires its own reviewed migration and
exact type/owner matrix. Connector/cursor/lease/budget/signing tables in the full
specification are architectural proposals, not a blanket role-allowlist extension.

In `backtest` and `eval` runs a single operating-system process may call the role functions in sequence (the replay loop does this). The permissions above are then enforced by the per-role helper objects, not by separate processes. The network and credential columns apply to the **deployed** workers.

---

## 4. Data contracts (summary; full DDL in `DATA_MODEL.md`)

All are Pydantic v2 models in `core/types.py`. Field names below are binding.

```text
Situation   id, pack, family, raw_item_id, occurred_at, sender_key|None,
            content_hash, redacted_text|None, hands_off_reason|None
Features    situation_id, deterministic{str: num|str|bool}, reader{...}|None,
            reader_ok:bool, featurizer_version, model_id|None, prompt_version|None
Proposal    id, situation_id, family, class_key, action, probs{action: float},
            p_max, novelty, novel:bool, licence_level, cap, gate, reasons[str],
            params{}, explanation{}, web{status, cap, source_ids}, policy_version,
            features_hash, audit_holdout:bool, proposed_at
Outcome     situation_id, observed_action, strength(STRONG|WEAK), observed_at,
            known_at, details{}
Action      id, proposal_id, pack, type, params{}, level_required, recallable,
            status, hold_until|None, undo{}|None, created_at, updated_at
LicenceView class_key, action, level, lower_bound, n_strong, k_strong, n_all,
            k_all, n_recent, exam_run_id|None, valid_until, reasons[str]
```

Enums: `Gate = SHADOW | SUGGEST | ASK | EXECUTE_UNDO | HOLD_THEN_EXECUTE | EXECUTE_SILENT`.
`ActionStatus = PENDING | HELD | DONE | UNDONE | CANCELLED | FAILED`.
`Strength = STRONG | WEAK`.

Approved additive target models (implementation/migration still required):
- Outcome events bind stable event, situation, proposal/response/action references,
  kind, source, strength, observed/known time and correction linkage. They are
  append-only. `HistoryView` derives the applicable as-of decision without duplicate
  evidence; unknown chosen actions remain unknown. Undo is not a training action.
  Persist an event, its compact ledger entry and its consumption receipt in one
  caller-owned transaction; external effects remain outside that transaction.
- Actions distinguish `autonomous` from `explicit_user` authority and bind the exact
  approved response/payload, connection, account/resource and restriction revision.
  No synthetic `level_required=0` or licence promotion is used to represent consent.
- Edited-body/forward payloads live in immutable response storage, preserving the
  original generated draft. API never writes the `drafts` table.

---

## 5. Pack adapter interface (`packs/base.py`)

```python
class PackAdapter(Protocol):
    name: str                                   # "mail"
    families: tuple[str, ...]                   # ("email_action",)

    # 1. What shows up that needs a decision?
    def iter_situations(self, source: Source, since: datetime | None) -> Iterator[Situation]: ...
    # 2. What facts can we count?  (history ONLY via HistoryView)
    def deterministic_clues(self, s: Situation, hist: HistoryView) -> dict[str, float | str | bool]: ...
    def reader_spec(self) -> ReaderSpec | None: ...   # prompt id, JSON schema, redaction profile
    def class_key(self, s: Situation, f: Features) -> str: ...
    # 3. What may the AI do?
    def action_catalog(self) -> list[ActionSpec]: ...  # type, recallable, base_cap, loss
    def level_cap(self, action: str, s: Situation, f: Features) -> int: ...  # conditional caps
    def hands_off(self, s: Situation) -> str | None: ...                   # reason or None
    # 4. Do it safely, and undo it  (Executor process only)
    def execute(self, a: Action, io: ExecutorIO) -> ExecResult: ...
    def undo(self, a: Action, io: ExecutorIO) -> ExecResult: ...
    # 5/6. What did the user actually do, and when is it final?
    def window(self, s: Situation) -> timedelta: ...
    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None: ...
    # Exam
    def exam_operators(self) -> list[ExamOperator]: ...
```

Rules:
- Preserve `iter_situations(source, since)` publicly; an internal raw-observation
  mapper may implement it. Ingestor owns source I/O and cursor durability. Synthetic
  and live observations share the same mapping and decision semantics.
- `HistoryView(as_of)` exposes only outcomes and raw items with `known_at <= as_of`. It has no method that can return later data.
- `execute` and `undo` are only ever called inside the `executor` process.
- A new pack MUST pass the **pack conformance test** (`TEST_PLAN.md` section 4) before it is registered in `packs/registry.py`.

---

## 6. LLM client contract (`llm/client.py`)

```python
class LLMClient:
    def chat_json(self, *, kind: str, model: str, system: str, user: str,
                  schema: dict, cache_parts: dict) -> ParsedJSON: ...
    def chat_text(self, *, kind: str, model: str, system: str, user: str,
                  max_tokens: int, cache_parts: dict) -> str: ...
```

- OpenAI-compatible HTTP API; base URL and model names come from settings only.
- `temperature=0`. Per-call timeout and up to 3 retries with exponential backoff and jitter on 429 and 5xx; honour `Retry-After` and rate-limit headers.
- Try JSON-schema structured output first. If the endpoint rejects it, fall back to "return JSON only" plus Pydantic validation plus **one** repair retry. On final failure raise `LLMValidationError` (the caller fails closed per I-3).
- Before sending: budget check (I-15). After: write `llm_cache` and `exposure_log`.
- Never log prompt bodies at INFO level. Hashes only.

---

## 7. Gate contract (`engine/gate.py`)

Pure function, no I/O:

```python
def decide(*, action: str, p: float, novel: bool, licence_level: int, cap: int,
           hands_off: str | None, reader_required: bool, reader_ok: bool, deterministic_ok: bool,
           loss: float, attention_cost: float, recallable: bool,
           audit_draw: float, audit_fraction: float, budget_ok: bool) -> GateResult: ...
```

Decision order (first match wins), exact semantics in `ENGINE_SPEC.md` section 7:
1. any of `not budget_ok`, `reader_required and not reader_ok`, `not deterministic_ok` -> `ASK`
2. `hands_off` -> `SHADOW`
3. effective level = `min(licence_level, cap)`
4. level 0 -> `SHADOW`; level 1 -> `SUGGEST`
5. level >= 2: `novel` -> `ASK`; economic test fails -> `ASK`; audit draw selects -> `SUGGEST`
6. otherwise by level and `recallable`: `HOLD_THEN_EXECUTE`, `EXECUTE_UNDO`, or `EXECUTE_SILENT`

---

## 8. Executor contract

- The Executor **creates** `actions` rows (idempotently, by `action_id`) from: (a) proposals whose gate is `EXECUTE_UNDO`, `HOLD_THEN_EXECUTE` or `EXECUTE_SILENT`; and (b) proposals whose `user_responses` row is `accept` or `edit` (an explicit user approval, which is sent or done immediately, without the hold). It then processes rows with `status=PENDING`.
- Reply text comes from the validated generated draft or the immutable, validated owner-edited response bound to that draft; action parameters come from immutable server-validated proposal/approval bindings. Never send a mutable browser payload.
- **Idempotent**: `action.id` is the idempotency key. Re-running never double-acts.
- Before an autonomous action (including after a hold), re-derive the licence (I-10) and recheck current restrictions, catalog, parameters and caps. On lost authority, cancel and request a linked suggestion through the Brain-owned proposal path; Executor cannot insert/mutate proposals.
- Explicit approval may authorize a supported action at licence level 0. Validate authenticated owner, exact account/resource/action/content binding, current consent/revocation and all hard hands-off, catalog, filesystem and draft constraints. Caps still bound autonomy; consent cannot increase them. Revalidation failure blocks effect. Payload changes require fresh approval.
- The first valid initial Accept/Edit/Reject wins atomically. Identical retries return the same result; conflicting initial decisions fail with a typed conflict. Later corrections are new linked events, never overwritten initial decisions.
- Normal explicit-feedback outcomes are Resolver-owned. Execution success/failure is a separate result; provider failure does not erase an already expressed decision. Executor emits immutable undo/cancel correction events; Examiner consumes them for drift before further affected autonomous execution.
- Reversible actions store actual prior state sufficient for conflict-safe undo. Non-recallable actions expose pre-effect cancellation only; ambiguous remote results require reconciliation before any retry, never blind resend.
- Undo window: `UNDO_DAYS` for reversible actions; `HOLD_MINUTES` cancel window for recallable-false actions.
- Cancelling a `HELD` action uses the undo request: Executor sets `CANCELLED` without effect and appends a linked STRONG correction event (source `undo`).
- **Undo flow:** API records an immutable undo request; Executor restores prior state within the permitted window, sets `UNDONE` on confirmed success and appends its correction event. Resolver records detected manual overrides with source `override`. Preserve earlier outcomes and their historical projections; correction events feed drift, never the agreement counts.
- The Executor MUST refuse any action type not in `action_catalog()`.

---

## 9. HTTP API contract (`api/`)

Base path `/api`. JSON in and out. Read-only except where noted.

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness and replay or live mode |
| `GET /report-card?family=` | Backtest summary: same / different / would-ask counts |
| `GET /licences` | Current derived licences with evidence, plus the last 5 changes of each (from the ledger `licence_change` entries) |
| `GET /queue` | Items needing the user (`ASK`, `SUGGEST`), grouped into a digest by `class_key` and proposed action |
| `GET /items/{proposal_id}` | Everything needed to explain one item: situation summary, proposal, evidence line for its `(class_key, action)`, `explanation` (top clues, similar past cases), web status and sources (if checked) and the draft if any |
| `POST /queue/{proposal_id}/respond` | Immutable typed request `{request_id, response: accept/reject/edit, edited_action?, edited_body?, forward_recipient?, reviewed_payload_hash}`; API records intent and returns HTTP 202; Resolver records decision evidence, Executor performs approved effects |
| `GET /responses/{request_id}` | Owner-scoped status/result: pending, succeeded, failed or needs-reconciliation; expose decision processing separately from execution completion |
| `GET /actions` | Executed and held actions |
| `POST /actions/{id}/undo` | Request an undo (writes a `user_responses` row; the Executor performs it and records the outcome) |
| `GET /habits`, `POST /habits/{id}/deny` | Mined habits; deny disables a habit |
| `GET /chains` | Mined chains |
| `GET /exams`, `POST /exams/run` | Exam history with per-case verdicts (including the edited items that flipped); run an exam (admin) |
| `GET /web-facts` | Tavily usage (calls, credits, cache hits) and the **exact queries sent** (transparency page) |
| `GET /boards/{pack}` | Board view for packs with one (`radar` tracker, `reading` library): entries with status, sources and the item behind each |
| `GET /metrics/summary` | Scorecard numbers plus weekly time series (asks, suggestions, automatic actions, agreement) and the list of drift and family-shift alarms |
| `GET /settings` | Read-only view of the effective tunables, level caps, loss values and the hands-off list (no editing in v1) |
| `GET /exposure` | Text sent to LLMs per item (counts) |
| `GET /ledger/verify` | Verifies the hash chain; returns `ok` or the first broken `seq`, plus `length` and `head_hash` |
| `GET /replay/state`, `POST /replay/{start|pause|speed}` | Replay clock control (demo) |

Error shape: `{ "error": { "code": str, "message": str } }`.

Additive report filters: `family`, `class_key`, `action`, `since`, `as_of`. Return
the exact applied scope/cohort and counts/denominators for strong agreement,
abstention/coverage, weak/unresolved/censored items. Historical performance,
posterior permission bound, exam status and current licence are distinct values;
no family score may masquerade as a task score. Empty cohorts are unavailable.

Edited reply text passes the same approved recipient/content/attachment/length
validators as generated replies; unsatisfied required details cannot auto-send.
REPLY remains original-sender-only. FORWARD uses an explicitly owner-selected,
validated recipient, exact reviewed content/attachment policy and immutable target
binding; an LLM cannot choose it. Body editing does not itself relabel REPLY.
Hash binding must be server-validated against canonical reviewed data; a client
assertion alone is not approval. New response fields/routes require versioned
models and compatibility tests before enabling the workflow.

---

## 10. CLI contract

Entry point `probation` (Typer). Every command is deterministic given `--seed`.

```
probation db init
probation synth generate --persona-id N --seed S [--size tiny|full] --out data/synth/N
probation import mail|calendar|files --source PATH
probation backtest --family F [--until DATE]
probation serve
probation exam run --class-key K --action A
probation eval run --suite main|ablations|baselines
probation ledger verify
probation budget show
```

---

## 11. Settings contract

All tunables are named constants in `config.py`, overridable by environment variables with the same name. **Defaults are defined in `ENGINE_SPEC.md` section 12.** Code MUST NOT hard-code numbers that appear there.

---

## 12. Global Definition of Done

A change is done only if **all** are true:
1. It satisfies the invariants it touches (listed in the PR or report).
2. Tests added or updated; `make check` passes (lint, types, tests).
3. No new network destination, credential, or file-system write outside the allowed set.
4. Docs updated if behaviour changed (and a decision noted in `DECISIONS_AND_OPEN_QUESTIONS.md`).
5. The phase's acceptance tests in `IMPLEMENTATION_PLAN.md` pass.

---

## 13. Change control

- Only a human edits this file.
- An agent that believes a rule must change MUST stop, write a short "Contract change request" (what, why, which invariants, alternatives), and wait.
- Approved changes are recorded in `DECISIONS_AND_OPEN_QUESTIONS.md` with the date.

Scoped exception, 22 October 2026: the owner explicitly permitted an agent to edit
this file for the recommended D1-D9 amendment, then approved those decisions.
This records that amendment only; future amendments still require human approval.

---

## 14. Non-goals

Screen, click or keystroke recording; payments, permanent destructive operations,
application submissions or unsupported sharing; WhatsApp or other apps without an
official personal API; running or opening downloaded programs; multi-user accounts;
model fine-tuning; claiming statistical guarantees (say "evidence", never "guarantee").
Supported catalog REPLY, explicitly approved FORWARD and RSVP operations are
permitted non-recallable effects under section 8/I-20. No extra irreversible action
becomes permitted through this clarification.

## 15. Full-product integration boundaries (approved D9 design)

- All six packs and F01-F42 remain required; old cut lines do not close a feature.
  Completion requires implementation and the specified evidence, not design approval.
- Credentials may use a role-protected OS secret store/deployment secret manager
  or environment injection. No raw tokens, private feed URLs or signing keys enter
  commands, ordinary DB rows, logs, prompts or source control. Concrete store,
  dependencies, provider endpoints/accounts/resources/budgets and live use require
  separate scoped authorization. Unattended auth needs tested refresh/revocation.
- External runtimes/MCP submit schema-validated proposals without protected write
  credentials. All protected effects pass through Executor. A permission lookup or
  portable receipt never grants an alternate write path. Probation's LLMs stay data-only.
- Signed receipts use a reviewed standard signing design, exact operation/resource
  binding, expiry, rotation/revocation and replay protection, plus a fresh authority
  check. Wire format, implementation dependency and real key provisioning remain gated.
- The public domain checker may use only a bounded, domain-only, separately quotaed
  Webfacts-owned command. Preserve I-21-I-26 and baseline autonomy on outage. This
  design approval does not authorize a public endpoint deployment or live spending.
- A separately approved human study uses synthetic stimuli, consent, anonymous
  participant identifiers, private records and aggregate reporting. No account/export
  collection or surveillance is authorized; actual recruitment/collection remains gated.
- Learned-about-you edits may change descriptions or deny a pattern. Semantic
  corrections become prospective provenance-bearing feedback, never edits to counts,
  hard caps or historical evidence. Choose the Spruce & Brass dark frontend brief;
  readiness labels must reflect verified backend workflows.
- Entity restrictions are monotone relative to the no-web baseline: adding them
  cannot raise autonomy; removing them may restore baseline autonomy. Keep the query
  guard and supported grammar, and preserve the saved-content/entity-fact distinction.
