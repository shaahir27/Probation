# ENGINE_SPEC

> WP1 ownership addendum (user-approved CCR-F, 22 October 2026): API enqueues typed
> administrative requests; Examiner applies them. Examiner consumes bounded immutable
> outcome ledger events into append-only drift receipts/state/alarms. Executor never
> updates drift state and waits when its pair has unreviewed events. Review occurs
> before nightly derivation and via `probation examiner-tick`; replay invokes the same
> Examiner-owned operation. See `docs/reports/wp1-closure-2026-10-22.md` and
> `docs/DECISIONS_AND_OPEN_QUESTIONS.md`. Full WP6 correction projection and remote
> reconciliation remain later work; no outcome-storage amendment is inferred here.

Exact algorithms, formulas and default numbers. Authority: below `CONTRACT.md` and above `SYSTEM_DESIGN.md`.
Every number is a named constant in `config.py` (section 12 lists the defaults). Numbers marked *(assumption)* are starting values to tune on the evaluation.

---

## 1. Time and the event-sourced replay

The engine is **event-sourced**: the same loop runs a simulated past (replay) and the live present. Only the `Clock` differs (CONTRACT I-9).

Event types on one merged timeline, processed in non-decreasing time order:

| Event | Time | Effect |
|---|---|---|
| `OUTCOME_KNOWN` | `outcome.known_at` | Outcome becomes visible to `HistoryView`; evidence updated |
| `LICENCE_REVIEW` | Every simulated day (replay) or nightly 02:00 IST (live) | Recompute class stats and licences; drift checks |
| `RETRAIN` | Every `RETRAIN_INTERVAL_DAYS` (replay) or nightly (live) | Refit policy and calibration per family |
| `SITUATION` | `situation.occurred_at` | Featurize, predict, gate, write proposal |

Tie order at the same timestamp: `OUTCOME_KNOWN`, then `LICENCE_REVIEW`, then `RETRAIN`, then `SITUATION`.
(An outcome known at time t is allowed to influence a proposal made at time t. It must never influence a proposal made earlier.)

### 1.1 Setting `known_at` for outcomes

| Footprint | `known_at` |
|---|---|
| Exact-timestamp footprint (a reply sent, an RSVP change with a time, a user response) | the footprint time (strictly after `occurred_at`) |
| Snapshot final-state label without a time (archived, trashed, file's final folder) | `occurred_at + window` |
| Weak "left alone" | `occurred_at + window` |
| Undo or override | the time it happened |

**Censoring:** if the data export date is earlier than `occurred_at + window`, the situation gets **no outcome** (it is not a label). It may still be proposed on.

### 1.2 Replay loop (pseudocode)

```python
timeline = merge_sorted(situations, outcomes_by_known_at, review_ticks, retrain_ticks)
for ev in timeline:
    clock.set(ev.time)
    if ev.kind == OUTCOME_KNOWN:   history.add(ev.outcome); evidence.update(ev.outcome); drift.update(ev.outcome)
    elif ev.kind == LICENCE_REVIEW: licences.recompute(as_of=ev.time); shift.check(as_of=ev.time)
    elif ev.kind == RETRAIN:        policy.fit_all(as_of=ev.time)          # uses only history.known_at <= ev.time
    elif ev.kind == SITUATION:      brain.process(ev.situation, as_of=ev.time)   # features -> predict -> gate -> ledger
```

`brain.process` MUST obtain history only via `HistoryView(as_of=ev.time)` (I-6).

---

## 2. Families, class keys and the pooling hierarchy

- A **family** has a fixed action set (see `PACKS_SPEC.md`).
- A **class key** is `pack|part1|part2`. Examples: `mail|request|known`, `file|portal.college.example|doc`.
- **Parent of a class key**: drop the last part (`mail|request|known` -> `mail|request`). **Root**: the family name.
- Evidence is keyed by `(class_key, action)`; pooling uses `(parent_key, action)` summed over children.

---

## 3. Features

`Features = deterministic clues + reader fields`.

- Deterministic clues come from the pack's `deterministic_clues()`, which can only read history through `HistoryView(as_of=occurred_at)`.
- Reader fields come from the LLM form (`PROMPTS.md`) after schema validation. If the reader fails: `reader_ok=False`.
- Encoding for the policy: categoricals one-hot (unknown values ignored), numerics standardised (scaler fit on the training rows only).
- `features_hash = sha256(canonical_json(deterministic + reader + featurizer_version))`.

---

## 4. Policy model (the "scoring sheet")

Per family:

```python
LogisticRegression(solver="lbfgs", C=1.0, max_iter=1000)   # multinomial by default
sample_weight = 0.5 ** (age_days / TRAIN_HALF_LIFE_DAYS)
```

- **Training rows:** situations with a STRONG outcome whose `known_at <= as_of`, `reader_ok=True`, `hands_off_reason is None`.
- **Cold start:** fewer than `COLD_START_MIN_SITUATIONS` training rows, or fewer than 2 distinct observed actions -> no model. Proposals get `action="ABSTAIN"`, `gate=SHADOW`, reason `cold_start`.
- **Files family:** classes are the top `FILES_TOPK_FOLDERS` folders by training count, plus `OTHER`, plus `LEAVE`. A folder with fewer than 5 training rows folds into `OTHER`. If the most likely class is `OTHER`, the proposal action is `ABSTAIN` (reason `other_folder`): the system never moves a file to a folder it cannot name.
- **Calibration (temperature scaling):** with at least 100 training rows, build out-of-fold probabilities via time-ordered 5-fold splits; fit one temperature `T` in `[0.5, 5.0]` minimising negative log-likelihood (`scipy.optimize.minimize_scalar`). Calibrated probabilities are `softmax(log(p_raw) / T)`. With fewer than 100 rows, `T = 1`.
- `action = argmax`, `p_max = max`.
- `policy_version = sha256(model coefficients, scaler, T)[:12]`.
- **Failed featurization:** proposal with `action="ABSTAIN"`, `gate=ASK`, reason `featurization_failed`. `ABSTAIN` is never counted as evidence.

---

## 5. Novelty

- Embedding model runs locally (`all-MiniLM-L6-v2` by default). Input text is the situation's `redacted_text` (files: name tokens + origin + extension).
- `d(s)` = mean cosine distance to the `NOVELTY_K` nearest **training** situations of the same family.
- Threshold `theta` = the `NOVELTY_PCTL`-th percentile of leave-one-out `d` over the training set (refit at each retrain).
- `novel = d(s) > theta`. With fewer than `NOVELTY_K + 1` training rows: `novel = True`.

---

## 6. Evidence and the licence predicate

### 6.1 What counts as evidence

For a pair `(c, a)` at time `as_of`:

- **Evidence set** = proposals with `class_key = c`, `action = a`, **not auto-executed** (`gate` in `SHADOW, SUGGEST, ASK`), `proposed_at >= as_of - EVIDENCE_WINDOW_DAYS`, and an outcome with `known_at <= as_of`.
- `agree = (outcome.observed_action == a)`.
- **Strong counts** `(n_strong, k_strong)`: outcomes with `strength = STRONG`.
- **All counts** `(n_all, k_all)`: STRONG plus WEAK.
- `n_recent`: strong evidence items in the last 30 days.

Auto-executed items **do not** enter the counts (CONTRACT I-12). They matter only through undo and override events (section 11).

*Known limitation:* the evidence set contains items the user handled plus audit draws, so it leans slightly harder than the executed population. This is conservative. Measure "licence stability" in the evaluation.

### 6.2 Lower bound with pooling

```python
def lower_bound(k, n, parent_mean=None, kappa=POOLING_KAPPA, q=LB_QUANTILE):
    if parent_mean is None:
        a0 = b0 = 1.0
    else:
        p = min(max(parent_mean, 0.01), 0.99)
        a0 = max(1.0, kappa * p)
        b0 = max(1.0, kappa * (1 - p))      # never below 1: pooling cannot assert near-perfection
    return scipy.stats.beta.ppf(q, a0 + k, b0 + (n - k))
```

- `parent_mean = (k_parent + 1) / (n_parent + 2)` using the parent's pooled strong counts. If `n_parent < 20`, use `parent_mean=None`.
- With no parent and no failures: `LB = 0.05 ** (1 / (n + 1))`. This gives **58 clean agreements for LB >= 0.95** and **148 for LB >= 0.98**. These are golden numbers (section 15).

### 6.3 Level derivation

```python
def level(c, a, as_of) -> LicenceView:
    cap = cap_for(a, context)                       # section 8, hard-coded
    L = 0
    if n_all >= L1_MIN_N and lb_all >= L1_MIN_LB:                      L = 1
    strong_ok = n_strong >= STRONG_MIN_RAW_N and recent_ok
    if strong_ok and lb_strong >= L2_MIN_LB and exam_ok(c, a, as_of, level=2):  L = 2
    if strong_ok and lb_strong >= L3_MIN_LB and exam_ok(c, a, as_of, level=3) and a.recallable: L = 3
    return min(L, cap)
```

- `recent_ok = n_recent >= LICENCE_MIN_RECENT_N` (default 20).
- `exam_ok(c, a, as_of, level)`: a **passed** exam run exists for `(c, a)` with `level_tested >= level`, `finished_at >= as_of - EXAM_VALID_DAYS`, and `finished_at` later than **both** the latest drift alarm for `(c, a)` and the latest family-shift alarm for the family (if any).
- **Demotion is a consequence of this rule, not a separate subtraction.** After a drift alarm or a family-shift alarm, level 2 and 3 are unavailable until a new exam passes, so the effective level falls to at most 1 (if the level 1 evidence still holds). The licence is not set to 0 by an alarm.
- `valid_until = as_of + LICENCE_TTL_DAYS`. After it, the licence is re-derived anyway. Re-derivation is cheap.
- Level 3 additionally requires the action to be `recallable` (CONTRACT I-20).

---

## 7. Gate

Pure function (`engine/gate.py`). Decision order, first match wins:

```python
def decide(...):
    if not budget_ok or not deterministic_ok or (reader_required and not reader_ok):
        return ASK("fail_closed")
    if hands_off:
        return SHADOW("hands_off")
    eff = min(licence_level, cap)
    if eff == 0:   return SHADOW
    if eff == 1:   return SUGGEST
    # eff >= 2
    if novel:                                   return ASK("novel")
    if (1 - p) * loss >= attention_cost:        return ASK("economic_test")
    if audit_draw < audit_fraction:             return SUGGEST("audit_holdout")   # sets proposals.audit_holdout = 1
    if eff == 3:                                return EXECUTE_SILENT
    return HOLD_THEN_EXECUTE if not recallable else EXECUTE_UNDO
```

- `audit_draw = int(sha256(situation_id + "|" + AUDIT_SEED)[:8], 16) / 2**32` (reproducible).
- Predicted `LEAVE` and `NO_RESPONSE` are no-op actions with cap 0, so the gate returns `SHADOW`.
- `SUGGEST` puts a prepared item in the queue (one tap). `ASK` puts a question in the digest.
- On a user's `accept` of a suggestion (or `edit`), the Executor performs the action **immediately**, with no hold, because the user approved it explicitly (CONTRACT section 8).

### 7.1 Order of work inside `brain.process` (the proposal is written once, after all of this)

1. Compute features, the policy output and the novelty flag.
2. Compute the gate with `gate.decide` (a preview).
3. If `action == REPLY` and the preview gate is `SUGGEST`, `HOLD_THEN_EXECUTE` or an `EXECUTE_*`: call the writer, then run the draft validator (`PROMPTS.md` section 5.1).
   - Draft invalid after one regeneration: final gate `ASK` with reason `draft_invalid`.
   - Draft has `needs_user_input = true`: final gate `SUGGEST` with reason `needs_user_input`.
4. Persist one transaction: append the proposal ledger entry, insert the immutable
   `proposals` row, then insert any validated `drafts` row referencing it. Commit before
   Executor consumption (CONTRACT I-7). Draft generation/validation happens in memory
   before the transaction. This order satisfies the existing draft foreign key.

---

## 8. Actions: caps, losses, recall, and conditional caps

`recallable = True` means the action can be undone after it is performed.
Attention cost = `ATTENTION_COST` (1). **Economic bar** `p* = 1 - ATTENTION_COST / loss`. The test is strict: the system may act alone only if `(1 - p) * loss < ATTENTION_COST`, so `p` must be **greater than** `p*` (at exactly `p*` it asks).

| Action | Family | recallable | Base cap | Loss | Bar `p*` |
|---|---|---|---|---|---|
| `ARCHIVE` | email_action | yes | 3 | 5 | 0.800 |
| `TRASH` | email_action | yes | 2 | 20 | 0.950 |
| `REPLY` | email_action | no | 2 | 40 | 0.975 |
| `FORWARD` | email_action | no | 1 | 40 | 0.975 |
| `LEAVE` | email_action | n/a | 0 | n/a | n/a |
| `ACCEPT` | invite_rsvp | no | 2 | 10 | 0.900 |
| `DECLINE` | invite_rsvp | no | 2 | 20 | 0.950 |
| `TENTATIVE` | invite_rsvp | no | 2 | 5 | 0.800 |
| `NO_RESPONSE` | invite_rsvp | n/a | 0 | n/a | n/a |
| `MOVE_TO_FOLDER` | file_destination | yes | 3 | 5 | 0.800 |
| `LEAVE` | file_destination | n/a | 0 | n/a | n/a |
| `BLOCK_TIME` | chain_followup | yes | 3 | 3 | 0.667 |
| `CREATE_FOLDER` | chain_followup | yes | 3 | 2 | 0.500 |
| `CREATE_TASK` | chain_followup | yes | 3 | 2 | 0.500 |
| `RENAME` (stretch) | file_destination | yes | 3 | 3 | 0.667 |
| `HOLD_DELETE` (stretch) | file_destination | yes | 2 | 10 | 0.900 |
| `GH_MARK_READ` (dropped from the plan) | gh_notification | no | 2 | 5 | 0.800 |
| `TRACK` | opportunity_triage | yes | 3 | 3 | 0.667 |
| `DISMISS` | opportunity_triage | yes | 2 | 8 | 0.875 |
| `LEAVE` | opportunity_triage | n/a | 0 | n/a | n/a |
| `FILE_TO_COLLECTION:{collection}` | link_triage | yes | 3 | 3 | 0.667 |
| `ARCHIVE_LINK` | link_triage | yes | 2 | 6 | 0.833 |
| `LEAVE` | link_triage | n/a | 0 | n/a | n/a |

Chain follow-up `REPLY` reuses the mail `REPLY` row (it creates a draft; sending follows mail rules).

### 8.1 Conditional caps (combine with `min`)

| Condition | Effect |
|---|---|
| mail: `sender_tier == unknown` | `REPLY`, `FORWARD`, `TRASH` -> cap 1; `ARCHIVE` -> cap 2 |
| mail: reader says `money_involved` or `asks_for_personal_info` | `REPLY`, `FORWARD`, `TRASH` -> cap 1; `ARCHIVE` -> cap 2 |
| invite: `organizer_tier == unknown` or `money_involved` | `ACCEPT`, `DECLINE`, `TENTATIVE` -> cap 1 |
| radar: reader says `fee_mentioned` or `requires_personal_docs` | `TRACK`, `DISMISS` -> cap 1 |
| any situation whose entity status is `lookalike`, `reports_found` or `no_web_presence` (**web veto**, `web_cap = 1`) | every action -> cap 1 |
| reading: entity status `lookalike` or `reports_found` | `FILE_TO_COLLECTION`, `ARCHIVE_LINK` -> cap 1, and no Extract |
| any situation with `hands_off_reason` | no action at all |

The `cap` passed to `gate.decide` is already `min(base cap, conditional caps, web_cap)`. The web veto can only lower it (CONTRACT I-21). Web facts reach the engine only through `WebFactsView`.

### 8.2 Hands-off (hard-coded)

- Files: executable and script extensions (`exe, msi, bat, cmd, com, scr, js, jse, vbs, vbe, wsf, ps1, jar, apk, dmg, pkg, app, lnk, iso, img, dll, sys`), any double extension whose last part is in that list (`report.pdf.exe`), and any name containing the right-to-left override character U+202E.
- Never act on: passwords, payments, permanent deletes, sharing documents outward.

---

## 9. Audit holdout

Why: after a licence is granted, auto-executed items produce no honest ground truth. Without audits, evidence stalls and licences cannot be renewed.

- At level >= 2, a random `AUDIT_FRACTION` (default 0.10) of would-be-executed items are downgraded to `SUGGEST` and flagged `audit_holdout=1`.
- The user's response or natural behaviour then gives a STRONG, unbiased outcome.
- Each draw is written to the ledger as `audit_draw`.
- Cost: that fraction of autonomy. Report it as "audit overhead" in the evaluation.

---

## 10. Outcomes for executed actions

- Executed and **undone or overridden** by the user -> STRONG outcome with `observed_action = "UNDO"` (source `undo` or `override`). It counts toward drift and demotion (section 11) but not toward the Beta evidence.
- Executed and **not objected to** -> WEAK outcome at `occurred_at + window`, for reporting only. Excluded from licence evidence.

---

## 11. Drift, demotion and family shift

### 11.1 CUSUM per `(c, a)`

```python
x_t = 1 if disagreement else 0                  # evidence items AND undo/override events
S_t = max(0, S_{t-1} + x_t - (baseline_err + CUSUM_ALLOWANCE))
if S_t >= CUSUM_ALARM:  alarm()                 # record last_alarm_at = now, S = 0, ledger drift_alarm; level 2 and 3 now need a new exam (section 6.3)
```

- `baseline_err` = `1 - posterior_mean` at the last licence change, default `CUSUM_BASE_ERR_DEFAULT`.
- **Hard rule:** two or more undo or override events for the same `(c, a)` within 30 days -> alarm immediately.
- After an alarm a new passed exam, finished after the alarm, is required before level 2 or 3 can return (I-13). Meanwhile the effective level is at most 1.

### 11.2 Family shift (PSI)

- Weekly, per family. Reference window: the 90 days before the last 30 days. Current window: the last 30 days.
- Features checked: the 5 features with the largest absolute coefficients in the current policy (numerics in 10 quantile bins from the reference window; categoricals by category).
- `PSI = sum_i (a_i - e_i) * ln(a_i / e_i)` with each share floored at `1e-4`.
- If `max PSI > PSI_ALARM` (0.25): `family_shift.alarm = 1`. Every licence in the family needs a new exam finished after that week's start before level 2 or 3 can return; meanwhile the effective level is at most 1.

---

## 12. Tunables (defaults)

| Name | Default | Meaning |
|---|---|---|
| `OUTCOME_WINDOW_MAIL_DAYS` | 7 | Mail outcome window |
| `OUTCOME_WINDOW_INVITE_MAX_DAYS` | 7 | Invite window (shorter if the event starts earlier) |
| `OUTCOME_WINDOW_FILE_DAYS` | 14 | File outcome window |
| `CHAIN_WINDOW_HOURS` | 24 | Follow-up window for chains |
| `COLD_START_MIN_SITUATIONS` | 200 | Training rows before predicting |
| `EVIDENCE_WINDOW_DAYS` | 180 | Evidence lookback |
| `L1_MIN_N`, `L1_MIN_LB` | 20, 0.70 | Level 1 (assumption) |
| `L2_MIN_LB`, `L3_MIN_LB` | 0.95, 0.98 | Level 2 and 3 bars |
| `STRONG_MIN_RAW_N` | 40 | Minimum raw strong decisions for level 2 or 3 |
| `LICENCE_MIN_RECENT_N` | 20 | Strong decisions in the last 30 days |
| `LICENCE_TTL_DAYS` | 30 | Cache lifetime |
| `EXAM_VALID_DAYS` | 90 | Age limit for a passing exam (assumption) |
| `EXAM_MAX_PER_DAY` | 3 | Cap on exam runs started per review tick, to control cost (assumption) |
| `POOLING_KAPPA` | 10 | Pseudo-observations borrowed from the parent |
| `LB_QUANTILE` | 0.05 | Lower-bound quantile |
| `ATTENTION_COST` | 1 | Cost of one interruption |
| `HOLD_MINUTES` | 10 | Hold before sending irreversible actions |
| `UNDO_DAYS` | 7 | Undo availability |
| `AUDIT_FRACTION` | 0.10 | Audit holdout share (assumption) |
| `AUDIT_SEED` | `"probation-audit-v1"` | Reproducible audit draws |
| `TRAIN_HALF_LIFE_DAYS` | 90 | Policy training recency weight |
| `RETRAIN_INTERVAL_DAYS` | 7 | Replay retrain interval |
| `FILES_TOPK_FOLDERS` | 15 | Folder classes for files |
| `NOVELTY_K`, `NOVELTY_PCTL` | 10, 95 | Novelty check |
| `CUSUM_ALLOWANCE`, `CUSUM_ALARM`, `CUSUM_BASE_ERR_DEFAULT` | 0.02, 5, 0.03 | Drift (assumption) |
| `PSI_ALARM` | 0.25 | Family shift |
| `EXAM_N` | 30 | Base cases per exam |
| `EXAM_MIN_VALID_CASES` | 20 | Fewer valid cases means exam cannot pass |
| `EXAM_INVARIANCE_MAX_FLIP` | 0.03 | Invariance pass mark |
| `EXAM_CRITICAL_MAX_VIOLATIONS` | 0 | Critical directional violations allowed |
| `EXAM_OTHER_MAX_VIOLATION_RATE` | 0.05 | Other directional violations allowed |
| `HABIT_MIN_SUPPORT`, `HABIT_MIN_LIFT`, `HABIT_Q` | 20, 1.5, 0.01 | Habit mining |
| `CHAIN_MIN_SUPPORT`, `CHAIN_MIN_P`, `CHAIN_MIN_LIFT` | 20, 0.60, 1.5 | Chain mining |
| `CHAIN_LINK_MIN_SIM` | 0.45 | Text similarity for weak links (assumption) |
| `READER_MAX_INPUT_CHARS` | 4800 | About 1,200 tokens |
| `TAVILY_MAX_CALLS_PER_DAY` | 100 | Daily cap on Tavily calls (assumption) |
| `TAVILY_MONTHLY_CREDIT_BUDGET` | 800 | Stay under the 1,000 free credits unless more are granted (assumption) |
| `TAVILY_TIMEOUT_S`, `TAVILY_MAX_CONCURRENCY` | 15, 4 | Client limits (assumption) |
| `WEB_FACTS_TTL_POSITIVE_DAYS`, `WEB_FACTS_TTL_NEGATIVE_DAYS` | 30, 7 | Cache lifetime for `confirmed_official` versus other statuses |
| `REPORT_HITS_MIN` | 2 | Results needed for `reports_found` |
| `LOOKALIKE_MAX_EDIT_DISTANCE` | 2 | Edit distance for the lookalike rule |
| `EXTRACT_MAX_CHARS`, `EXTRACT_TTL_DAYS` | 20000, 30 | Stored page text limit and cache lifetime |
| `QUARANTINE_MAX_INPUT_CHARS` | 6000 | Page text given to the quarantined extractor |
| `RADAR_WINDOW_DAYS`, `RADAR_MIN_WINDOW_DAYS` | 14, 2 | Radar outcome window |
| `READING_WINDOW_DAYS` | 14 | Reading outcome window |

---

## 13. Habit mining

1. For each family, build a table of rows `(clue_name, clue_value, action)` from strong-outcome situations. Numeric clues are binned into quartiles.
2. For each `(clue_value, action)`: `k` = rows with that clue value and action, `n` = rows with that clue value. Lift = `(k/n) / P(action)`.
3. Test with Fisher's exact test (one-vs-rest). Apply Benjamini-Hochberg correction across all tests in the family.
4. Keep if `n >= HABIT_MIN_SUPPORT`, `lift >= HABIT_MIN_LIFT`, `q < HABIT_Q`.
5. Build a **template statement** in code (for example `declines invites with start_hour_bucket=early`). The LLM may only reword it; a validator rejects any reworded text whose numbers differ from the template (`PROMPTS.md` section 7).
6. Store up to 5 example situation ids. A `denied` habit is excluded from explanations (it never enters the policy; the policy is learned from data, not from habits).

---

## 14. Chain mining

1. **Triggers:** situations with a class key (mail, invite, file).
2. **Follow-ups:** user-initiated events within `(t, t + CHAIN_WINDOW_HOURS]`: sent replies, user-created calendar events, user-created folders, user-created tasks.
3. **Linking:** explicit link (a reply in the same thread) -> STRONG. Otherwise link when cosine similarity of the trigger text and the follow-up title or name `>= CHAIN_LINK_MIN_SIM` -> WEAK.
4. For each `(trigger_class, follow_action)`: `n` = triggers in that class, `k` = triggers with a linked follow-up of that type, `base_rate` = share of days containing at least one user-initiated event of that type, `lift = (k/n) / base_rate`.
5. Keep if `n >= CHAIN_MIN_SUPPORT`, `k/n >= CHAIN_MIN_P`, `lift >= CHAIN_MIN_LIFT`.
6. Each follow-up step is its own **situation** (`pack=chains`, `family=chain_followup`, `variant={follow_action}`, created by the `brain` when the trigger is processed) and is gated independently with class key `chain|{trigger_class_key}|{follow_action}`. One trigger can therefore have several chain situations, each with its own immutable proposal.
7. Evidence for chain steps: WEAK links may support **level 1 only**. Level 2 or 3 needs STRONG evidence, which comes from explicit user responses to suggestions (accept gives `observed_action = follow_action`; reject gives `REJECT`) and from strong links.
8. At the end of the window, a chain situation with no explicit response and no link gets the WEAK outcome `NONE`.

---

## 15. Exam board algorithm

Inputs: `(c, a)` and the candidate level `L_test` in `{2, 3}`. The result is stored with `level_tested = L_test`; a pass at 3 also qualifies for 2.

### 15.0 When exams run

At each `LICENCE_REVIEW`, for every `(c, a)` whose evidence meets the **numeric** bar for level 2 (or 3) but has no valid passing exam (section 6.3), queue an exam for the highest level it qualifies for. Start at most `EXAM_MAX_PER_DAY` per review tick, oldest candidate first. Exams also run on demand (`probation exam run`, `POST /exams/run`). There is no periodic "weekly exam": a passing exam is reused until it is older than `EXAM_VALID_DAYS` or an alarm makes it stale.

### 15.1 Procedure


1. **Sample** up to `EXAM_N` base situations from `c` where the proposal action is `a` and an outcome exists. Stratify by month. Deterministic with a seed.
2. Keep only bases whose gate at `licence_level = L_test` is **action-taking** (autonomy rank >= 2, see 15.2). If fewer than `EXAM_MIN_VALID_CASES` valid cases result, the exam fails with `insufficient_cases`.
3. For each base, apply operators from the pack (`PACKS_SPEC.md`): code operators run in code, LLM operators call the exam-edit prompt. Each operator has a **validator** (code) confirming the edit really happened. Invalid edits are discarded and counted.
4. Run the **whole pipeline** on each valid edit: redact, reader (LLM), deterministic clues, policy, gate (with `licence_level = L_test`).
5. Verdicts (code only):
   - **Invariance** operators: flip if `(action, gate)` differs from the base. Invariance operators marked **critical** (page injection) must have **zero** flips.
   - **Directional** operators: violation if `autonomy_rank(after) > autonomy_rank(base)`.
6. Pass if all hold: `invariance_flip_rate <= EXAM_INVARIANCE_MAX_FLIP`; critical violations `<= EXAM_CRITICAL_MAX_VIOLATIONS`; other violation rate `<= EXAM_OTHER_MAX_VIOLATION_RATE`; valid cases `>= EXAM_MIN_VALID_CASES`.
7. Write `exam_runs`, `exam_cases`, and a ledger `exam_run` entry.

### 15.2 Autonomy rank

`SHADOW=0, ASK=1, SUGGEST=1, HOLD_THEN_EXECUTE=2, EXECUTE_UNDO=2, EXECUTE_SILENT=3`.

`ASK` and `SUGGEST` share a rank on purpose: neither acts without the user. (An earlier draft ranked `SUGGEST` above `ASK`, which wrongly counted a licence demotion from level 2 to level 1, or a web veto, as "more autonomous" in 144 of 1,536 exhaustively tested gate inputs.)

---

## 16. Golden numbers (tests assert these)

| Case | Expected |
|---|---|
| No parent, `k=n=58` | `LB >= 0.95` |
| No parent, `k=n=57` | `LB < 0.95` |
| No parent, `k=n=148` | `LB >= 0.98` |
| No parent, `k=n=147` | `LB < 0.98` |
| No parent, `k=n=60` | `LB = 0.952` (tolerance 0.001) |
| No parent, `k=41, n=42` | `LB = 0.894` (tolerance 0.003) |
| Parent mean 0.99, `kappa=10`, `k=n=48` | `LB < 0.95` |
| Parent mean 0.99, `kappa=10`, `k=n=49` | `LB >= 0.95` |
| Parent mean 0.99, `kappa=10`, `k=n=40` | `LB = 0.9417` (tolerance 0.002) |
| Economic bar for `REPLY` (loss 40, cost 1) | `p* = 0.975` |

---

## 17. Report card definition

For a family over a period (strong outcomes only):
- **same** = proposals where `action == observed_action`
- **different** = strong outcome and `action != observed_action`
- **would_ask** = proposals with `gate == ASK` or `action == ABSTAIN`
- Items with no outcome (censored) are listed separately and excluded from "same" and "different".
