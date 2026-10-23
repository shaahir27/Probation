# W3-D03 — Spend accounting schema and role-ownership review request

Status: **request for review. Nothing here is approved, migrated or implemented.** No table named in this
file exists in `backend/src/probation/db/schema.sql`, no migration adds one, and no process writes one.
This document exists because `backend/src/probation/llm/budget.py` says so in its module docstring, and
because the alternative — creating the tables and the write grants quietly inside a WP3 package — is
forbidden.

Authority chain: `docs/CONTRACT.md` §3 (process/table matrix, "a process MUST NOT write to tables outside
its row"; "Connector/cursor/lease/budget/signing tables in the full specification are architectural
proposals, not a blanket role-allowlist extension"), invariant I-15 (hard cap enforced in the LLM client),
I-14 (every call in `exposure_log` with genuine counts), I-16 (cache key), I-8 (append-only ledger);
`docs/CONTRACT_AMENDMENT_2026-10-22.md` FP-D3 ("Exact DDL/index/role matrix for each proposed
connector/cursor/lease/budget table; no blanket table grants") and §3 ("existing worker code must not read a
new schema until its compatibility/readiness gate passes"); `docs/wp3/WORK_PACKAGES.md` P04; the W3-D03 and
W3-D04 rows of `docs/wp3/WP3_IMPLEMENTATION_PLAN.md` §9.

## 1. What is already in place, and what it cannot promise

Implemented in P04 (`backend/src/probation/llm/budget.py`, `backend/src/probation/llm/client.py`):

| Behaviour | Source |
|---|---|
| Money is an exact integer unit, `UNITS_PER_USD = 100_000_000`; limits and costs both round up | `usd_to_units`, `cost_units` |
| A model with no verified price is denied before dispatch; there is no cheap fallback tier | `rates_for`, `load_price_table` |
| A missing or malformed price file is a denial, not a default | `load_price_table` |
| Every physical attempt — first send, 429/5xx retry, format fallback, repair — reserves its own bound before the socket | `BudgetGuard.reserve_units`, `LLMClient._post_with_retries` |
| An attempt that left the process stays charged at its bound on timeout, non-2xx and invalid output | `charge_bound`, `_account` |
| Only an attempt known never to have been dispatched gives its hold back | `release_hold` on `httpx.ConnectError` |
| Reported provider usage is charged exactly and a charge above its authorization warns and consumes the cap | `_account`, `code=charge_over_estimate` |
| Stored spend is re-adopted on start-up, and untrustworthy stored cost metadata denies | `sync_from_db`, `units_from_persisted` |

What it cannot promise, in one sentence each:

1. **Cross-process serialization.** Two workers each hold a `BudgetGuard`; neither sees the other's hold, so
   both can be authorized for the last unit of the cap. `spent_units` resets on process restart except by an
   explicit `sync_from_db` read of `exposure_log`.
2. **Crash-durable attempt truth.** If the process dies between dispatch and reconciliation, the attempt
   exists nowhere except — if it got that far — one `exposure_log` row. P04.2's "reserved but not billed"
   state has no home.
3. **Attempt-level exposure rows.** `exposure_log` is written once per successful *request*, not per physical
   attempt, so a three-attempt ladder that ultimately fails records zero rows while charging three bounds.
   That is the correct billing posture and the wrong audit story; §4 fixes the audit story without changing
   the billing posture.
4. **Single-flight.** Nothing prevents two processes from paying for the same semantic request.

Those four are the reason P04.1, P04.2, P04.4 (durability), P04.6 (lease policy) and P04.8 remain open, and
why requirement **7.3.6 in `docs/reports/wp3-requirements-coverage-2026-10-23.csv` is recorded as partially
implemented, not complete**.

## 2. Design rules this schema must satisfy

* **Derived counters, not trusted counters.** `spent` and `held` are `SUM`s over attempt rows, so a crash
  cannot lose or invent money and no row can claim a total that its attempts do not support.
* **Integer money.** Every monetary column is `INTEGER NOT NULL CHECK (col >= 0)` in units of 1e-8 USD.
  `REAL` money is what produced the six-decimal leak that P04 closed. `exposure_log.cost_usd` stays `REAL`
  for now (it is a published schema and existing rows exist); a companion integer column is proposed in §5.
* **No payload, no secret.** Accounting rows hold digests, ids, counts and units. Never message text,
  recipient, prompt body, API key or provider response.
* **Two clocks, never one.** Operational timestamps come from a separately injected `core.clock.Clock` in
  operational mode. The semantic replay Clock (W3-D07) must never age a lease or move a charge between
  budget periods, and no operational timestamp may enter `features`, `exam_cases` or ledger evidence.
* **Role rows, not role tables.** Per FP-D3, each grant below is row-scoped by an owner-role column that
  the typed repository and a SQLite `BEFORE UPDATE`/`INSERT` trigger both check.

## 3. Proposed DDL (additive; nothing here is applied)

```sql
-- One row per provider/account/budget scope. Independent of persona, run, replay or situation.
CREATE TABLE budget_scopes (
  scope_id       TEXT PRIMARY KEY,          -- det_id(provider, account_label, period_rule)
  provider       TEXT NOT NULL,             -- 'nebius_token_factory'
  account_label  TEXT NOT NULL,             -- non-secret label, e.g. 'primary'; never a key
  model_id       TEXT NOT NULL,             -- the exact priced id this scope quotes
  period_rule    TEXT NOT NULL CHECK (period_rule IN ('total','calendar_day','calendar_month')),
  period_key     TEXT NOT NULL,             -- operational period, e.g. '2026-10-23'
  cap_units      INTEGER NOT NULL CHECK (cap_units >= 0),
  price_version  TEXT NOT NULL,             -- hash of the price-table entry actually used
  created_at_op  TEXT NOT NULL,             -- operational clock only (W3-D07)
  UNIQUE (provider, account_label, model_id, period_rule, period_key)
);
CREATE TRIGGER budget_scopes_immutable BEFORE UPDATE ON budget_scopes
BEGIN SELECT RAISE(ABORT, 'budget_scopes rows are immutable except counters'); END;
```

`cap_units` is written once. Nothing mutable lives in this table, so no counter needs protecting.

```sql
-- Immutable logical request identity: one intent, possibly several paid attempts (W3-D04).
CREATE TABLE llm_requests (
  request_id       TEXT PRIMARY KEY,        -- det_id(scope_id, semantic_digest, ordinal_root)
  scope_id         TEXT NOT NULL REFERENCES budget_scopes(scope_id),
  owner_role       TEXT NOT NULL CHECK (owner_role IN ('brain','examiner','webfacts')),
  semantic_digest  TEXT NOT NULL,           -- content_hash of the full semantic envelope (P05.2)
  prompt_id        TEXT NOT NULL,
  prompt_version   TEXT NOT NULL,
  model_id         TEXT NOT NULL,
  cache_key        TEXT NOT NULL,           -- the I-16 outer key, unchanged in shape
  situation_id     TEXT,                    -- nullable: diagnostic calls have no situation
  result_state     TEXT NOT NULL CHECK (result_state IN
                     ('open','succeeded','failed_closed','unavailable')),
  created_at_op    TEXT NOT NULL,
  settled_at_op    TEXT,
  UNIQUE (scope_id, semantic_digest, prompt_id, prompt_version, model_id, situation_id)
);

-- One row per physical send. This is the object the cap is actually enforced against.
CREATE TABLE llm_attempts (
  attempt_id        TEXT PRIMARY KEY,       -- det_id(request_id, ordinal)
  request_id        TEXT NOT NULL REFERENCES llm_requests(request_id),
  scope_id          TEXT NOT NULL REFERENCES budget_scopes(scope_id),
  owner_role        TEXT NOT NULL CHECK (owner_role IN ('brain','examiner','webfacts')),
  ordinal           INTEGER NOT NULL CHECK (ordinal >= 1),
  stage             TEXT NOT NULL CHECK (stage IN
                      ('structured','retry','format_fallback','repair')),
  state             TEXT NOT NULL CHECK (state IN
                      ('reserved','dispatched','reconciled','ambiguous','never_dispatched')),
  estimate_units    INTEGER NOT NULL CHECK (estimate_units >= 0),
  charged_units     INTEGER NOT NULL CHECK (charged_units >= 0),
  tokens_in_bound   INTEGER NOT NULL CHECK (tokens_in_bound >= 0),
  tokens_out_bound  INTEGER NOT NULL CHECK (tokens_out_bound >= 0),
  tokens_in         INTEGER,                -- only with provenance 'reported'
  tokens_out        INTEGER,
  usage_provenance  TEXT NOT NULL CHECK (usage_provenance IN
                      ('none','reported','estimated')),
  denial_code       TEXT CHECK (denial_code IN
                      ('price_missing','price_invalid','price_table_missing','price_table_invalid',
                       'usage_invalid','amount_invalid','cost_metadata_invalid','cap_exceeded',
                       'transport','status','validation')),
  lease_owner       TEXT,                   -- process token, e.g. 'brain-4172-a3f'
  lease_token       INTEGER NOT NULL DEFAULT 0,   -- fencing counter, monotonic per attempt
  reserved_at_op    TEXT NOT NULL,
  dispatched_at_op  TEXT,
  reconciled_at_op  TEXT,
  UNIQUE (request_id, ordinal)
);

-- Held money is what the cap must add to spent; it is exactly the not-yet-reconciled rows.
CREATE INDEX llm_attempts_open_by_scope ON llm_attempts (scope_id)
  WHERE state IN ('reserved','dispatched','ambiguous');
CREATE INDEX llm_attempts_charged_by_scope ON llm_attempts (scope_id, state)
  WHERE state = 'reconciled';

CREATE TRIGGER llm_attempts_no_history_update BEFORE UPDATE ON llm_attempts
BEGIN SELECT RAISE(ABORT, 'llm_attempts rows transition forward only'); END;
```

`llm_attempts` is forward-transition only: the repository may set `state` from
`reserved → dispatched → reconciled|ambiguous`, or `reserved → never_dispatched`, and may fill `denied`
rows' terminal fields, but never rewrite an ordinal, a bound, a charge or a timestamp. Because SQLite cannot
express that in one `CHECK`, the enforceable parts are: the two triggers above plus a repository that
accepts only a declared transition, and a validation query in the readiness gate that re-derives every
`charged_units` from the provider-reported usage recorded in the paired `exposure_log` row.

`exposure_log` keeps its current meaning — one row per successful request — and gains nothing here. The
attempt rows are the audit of the *cost*, not of the *exposure*; P03's genuine counts stay the egress truth.

## 4. Exact per-role matrix for the new tables

| Table | Reads | Writes | Row restriction the repository enforces |
|---|---|---|---|
| `budget_scopes` | all roles, api | **nobody at runtime** | inserted only by an operator-initiated, ledger-recorded administration step; a worker that finds no row for its scope **denies the call** |
| `llm_requests` | owner role, api | `brain`, `examiner`, `webfacts` | only rows whose `owner_role` equals the connection's bound role |
| `llm_attempts` | owner role, api | `brain`, `examiner`, `webfacts` | same; plus only the row's `lease_owner` may advance its state |
| ledger | unchanged | unchanged | a reservation is not an effect, so reservations do not append to the ledger; only an executed action does (I-8 unaffected) |

This is the smallest grant that can serialize the cap, and it is still an extension of CONTRACT §3: the
contract names `llm_cache` and `exposure_log` for those three processes and names no budget, request or
attempt table at all. §3's own sentence — "Connector/cursor/lease/budget/signing tables in the full
specification are architectural proposals, not a blanket role-allowlist extension" — is exactly the rule that
stops this document from being self-authorizing.

## 5. Money, pricing and the unbounded-cost rule

* Cap check per attempt: `SUM(charged_units over reconciled) + SUM(estimate_units over open) + new_estimate
  <= cap_units`, evaluated inside one `BEGIN IMMEDIATE` transaction that commits **before** HTTP (P04.4).
  No write lock may span a network call, so the transaction's whole life is the reservation.
* `tokens_in_bound` is `TOKENS_PER_CHAR_BOUND` (2) × the exact egress character count. That constant is an
  **assumption submitted for review**, not a measured tokenizer ratio; a BPE encoder can split a non-Latin
  character and the request envelope adds framing this process cannot see. It is deliberately an upper bound.
* An attempt whose cost cannot be bounded **denies the call** rather than reserving a guess (W3-D04 gate:
  "unknown unbounded cost denies calls").
* `settings.price_table_path` is cwd-relative (`config/prices.json`), like every other path in
  `probation/config.py`. With the hard-coded fallback gone, that means a process started outside the
  repository root now denies its first call with `price_table_missing` instead of silently pricing itself.
  The direction is the safe one, so it is left alone here; resolving it is a configuration question for the
  same review, not something to change under a code-safety heading.
* `exposure_log.cost_usd` is `REAL` in the published schema. Proposed additive column
  `cost_units INTEGER CHECK (cost_units >= 0)`, backfilled as `CAST(ROUND(cost_usd * 1e8) AS INTEGER)` and
  verified equal to its attempt's `charged_units`; `REAL` remains for compatibility and is never the
  arithmetic input again. This is a schema change to a table CONTRACT §3 already assigns, so it needs the
  same review as the tables above.

## 6. Lease, crash and ambiguity policy (P04.6)

* `lease_owner`/`lease_token` exist so a reclaiming process can fence a dead one, but **lease expiry never
  releases money**. An expired `dispatched` or `ambiguous` row keeps its `estimate_units` held against the
  cap until reconciliation, because the provider may have billed it. Only `reserved` (never dispatched) rows
  may be returned to the cap, and only by a validated `never_dispatched` transition.
* A `reserved` row whose process died before dispatch is indistinguishable from a slow one, so the reclaim
  is conservative by default: it stays held. An operator resolution — the only path that may lower a hold —
  must be typed, logged and, if it changes what any process may spend, ledger-adjacent by policy decision.
  **Which of those two defaults is correct is a question for review, not a decision this package made.**
* Reconciliation at start-up: sum open rows into `held_units`, sum reconciled rows into `spent_units`, then
  cross-check `spent_units` against `exposure_log` for the same scope and deny on disagreement
  (`cost_metadata_invalid`).

## 7. Readiness gate before any worker reads this schema

Per the amendment's §3, no existing worker may read a new schema until its gate passes. The gate is:

1. migration is additive and re-runnable (`ensure_schema`-safe), and `DROP`s restore the pre-P04 state with
   no data loss elsewhere;
2. the two-process "last unit" test, killed-dispatch test, duplicate-attempt test and
   accounting-store-unavailable test all exist and pass (W3-T14–T18, T31);
3. an unavailable or unwritable accounting store **denies dispatch** — fail closed, never "assume in-process";
4. no operational timestamp appears in `features`, `exam_cases`, `outcomes` or `ledger`;
5. `graphify update .`, `python scripts/check.py` and the protected fixture/result hashes are unchanged
   except for the new tests.

## 8. Contract change request

AGENTS.md requires a change request rather than an edit when a rule must move. This is that request.

> **Request.** Add to `docs/CONTRACT.md` §3 a row-level grant for three new tables — `budget_scopes`
> (read: all roles; write: administration step only), `llm_requests` and `llm_attempts` (write: `brain`,
> `examiner`, `webfacts`, each restricted to rows whose `owner_role` is its own bound role and, for attempts,
> to its own `lease_owner`) — plus the exact DDL, indexes and transition triggers of §3 above, and an
> additive integer `cost_units` column on `exposure_log`. State that monetary accounting uses integer units
> of 1e-8 USD and that derived sums, not stored counters, are authoritative.
>
> **Why.** I-15 requires a hard cap enforced in the LLM client, and W3-D04 requires a durable separation of
> logical request, physical attempt and application result. Neither is reachable with the tables §3 names,
> because `llm_cache` stores results and `exposure_log` records only successful requests. A process-local
> float is explicitly rejected by P04.4.
>
> **What this does not ask for.** No new network destination, credential, dependency or process. No change to
> I-1, I-3, I-6, I-7, I-8, I-14, I-16. No spending authority: approving the schema does not authorize a live
> call, and W3-D08 (exact model ids, prices and request options) still needs its separately authorized
> account-specific spike.
>
> **Until approved,** the durable half of P04 stays unimplemented and 7.3.6 stays partially implemented.

## 9. What is deliberately *not* blocked on this review

P05's parsing, classified errors, semantic cache key and repair-bound work; P06's reader service; P07's
shared prediction; P08's writer and draft validation; P09's consumer migration; P10's atomic
proposal/draft persistence — none needs a new table. Plan §9: "Resolve unaffected pure work while a scoped
operational gate is pending; never mark a blocked F row complete." Concurrency stays sequential, and paid
dispatch stays under the in-process guard, until W3-D03 and W3-D04 clear.
