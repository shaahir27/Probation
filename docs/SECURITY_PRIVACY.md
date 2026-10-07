# SECURITY_PRIVACY

Threats, defences and data rules. Invariants live in `CONTRACT.md` section 2 (referenced here as I-n). Authority: below `CONTRACT.md`.

---

## 1. Assets

| Asset | Why it matters |
|---|---|
| Credentials (LLM API key, mail and calendar tokens) | Could spend money or read and change a real mailbox |
| The user's mail, calendar, files and their metadata | Private, and full of other people's data |
| The ledger and evidence | They justify every permission; tampering would fake trust |
| The licences | They decide what runs without asking |
| The demo and its budget | A public target |
| Tavily key and credits | Could be drained; queries could leak what the user is looking at |

---

## 2. Trust boundaries

```
 [ Sources: mail, calendar, files ]
            | read-only
            v
   ingestor ---> engine DB (SQLite) <--- api (read-only) <--- dashboard
                     ^      ^
        brain -------+      +------- examiner      <- may call the LLM endpoint (redacted text only)
          |                              |
          +---------- LLM endpoint ------+          (Nebius Token Factory)

   executor  <--- only process with WRITE credentials ---> target apps
```

Rules at each boundary: CONTRACT section 3 (who may read, write, hold credentials, reach the network).

---

## 3. Threat table

| ID | Threat | Defences (invariants and mechanisms) | Tests |
|---|---|---|---|
| **T1** | **Prompt injection** in a mail, invite or file name tries to steer the reader or writer | LLM output is data only and schema-validated (I-1); the reader only fills a form and has no tools; risk flags default to `true` when unsure; reader output is cross-checked against header facts (`reader_conflict` fails closed); drafts go through the draft validator; the exam includes injection operators (critical); outward actions on unknown senders are capped at level 1 | T-EXAM, T-GATE, T-CAPS |
| **T2** | **Malicious files** (executables, double extensions, right-to-left override names) | Hard-coded hands-off list (I-4); the system never opens or runs files; moves only inside `FILES_ALLOWED_ROOTS`; never overwrites | T-HANDSOFF, T-EXEC |
| **T3** | **Leaking personal text** to the LLM provider | Redaction before every call (I-14); minimal context (trimmed body, no history); `exposure_log` of every call; local embeddings; optional sandbox allowing only the LLM host | T-REDACT, T-SEC |
| **T4** | **Provider retention or training** on prompts | Read Nebius's data-retention and privacy terms before using any real data **(check, open question O-3)**; until then the demo and repo use synthetic data only (I-18) | Manual check |
| **T5** | **Licence poisoning**: an attacker sends many harmless items to earn trust, then exploits it | Classes are keyed by sender tier; `unknown` senders are capped at level 1 for outward actions; only strong outcomes count for level 2 and 3 (I-11); the exam's directional operators; audit holdout gives unbiased evidence (I-12); CUSUM and the two-undos rule | T-EVIDENCE, T-CUSUM, T-EXAM |
| **T6** | **Ledger tampering** | Append-only triggers and hash chain (I-8); `GET /ledger/verify`. **Limitation:** someone with full write access to the database file can recompute the chain. Mitigation: publish the head hash (for example in the submission text) so later tampering is detectable | T-LEDGER |
| **T7** | **Credential theft or over-privilege** | Only the Executor holds write credentials (I-2); per-container environment variables; least-privilege scopes; no secrets in logs or prompts (I-19) | T-SEC |
| **T8** | **Cost runaway or demo abuse** | Budget guard (I-15); per-IP rate limits; replay mode with saved answers; kill-switch; no free-text input to the LLM in the public demo | T-LLM |
| **T9** | **Supply chain** (packages, model files) | Lockfiles; few dependencies; run the ecosystem audit tools (`pip-audit`, `npm audit`) before release **(check availability)**; fetch the embedding model from its official source and record its hash | Release checklist |
| **T10** | **Wrong action** from model error | Licences, hold queue, undo, audit holdout, fail closed (I-3, I-12, I-20) | T-GATE, T-EXEC |
| **T11** | **Peeking** (using future information) | Injectable clock (I-9); `HistoryView` (I-6); property test | T-NOPEEK |
| **T12** | **Third-party privacy** (other people appear in a user's mail) | Redaction; real exports stay local under `data/private/`; never committed (I-18); human study uses synthetic stimuli only | Review |
| **T13** | **Over-claiming** safety | Say "evidence", never "guarantee"; document limits (section 7) | Review |
| **T14** | **Indirect prompt injection** through web content (snippets, extracted pages) | Raw web text is untrusted (I-22): only a quarantined extractor with a strict schema reads it, code validates the output, the writer never sees it; vetting is deterministic code; injection operators in the exam | T-QUAR, T-EXAM |
| **T15** | **Query leakage** to Tavily (free-tier retention unknown) | Queries are built by code from public-entity strings only and pass the query guard (I-23); every query is logged and shown to the user (`GET /web-facts`); only user-saved URLs reach Extract | T-WEBQ |
| **T16** | **Tracking or side-effects** from fetching a link (a per-recipient link confirms the mailbox is live) | Mail-body URLs are never fetched (I-24); Extract only on user-saved or Search-discovered official URLs; token-bearing and sensitive-path URLs are hands-off | T-LINK |
| **T17** | **Poisoned or spoofed "official" results** (SEO or a fake brand site) | Web facts can only restrict (I-21); `confirmed_official` never raises anything; a local brand list covers the head; the tail is a documented limit | T-WEBISO, T-VET |
| **T18** | **False accusations** against real organisations | UI says "I found...", never "this is a scam"; every statement is cited (I-26); demo scam examples use **invented** domains; real organisations appear only as live-confirmed examples | Review |

---

## 4. Data handling rules

### 4.1 Classes

| Class | Examples | Rules |
|---|---|---|
| **A: secrets** | API keys, OAuth tokens, passwords | Environment variables only; never committed, logged, sent to an LLM, or pasted into an agent prompt |
| **B: personal data** | Real mail, calendar, files, filenames, the `drafts` table (restored names in reply text), saved links and `extractions` (they reveal what the user saved) | Local only under `data/private/`; gitignored; never in the repo, demo, issue tracker or screenshots |
| **C: synthetic data** | Generated personas and items | May be committed in small fixtures; may be sent to an LLM |
| **D: aggregates** | Metrics, figures | May be published |

### 4.2 Redaction
`redact()` runs before every LLM call (PROMPTS section 1). It is best-effort: it reduces exposure, it does not prove the absence of personal data. Never describe it as anonymisation.

### 4.3 Logging
- Never log message bodies, prompts, secrets or file contents. Log ids, hashes, counts and decisions.
- Prompt bodies are not logged at INFO level (CONTRACT section 6).

### 4.4 Retention
- `probation db purge` can remove `raw_items` and `situations` text. The ledger holds only ids and decisions (DATA_MODEL section 5).

### 4.5 Secrets
- `.env` is gitignored; `.env.example` has no values.
- Run a secrets scan (for example `gitleaks` or `trufflehog`) before every push and before submission **(check tool choice)**.
- If a secret is ever committed, rotate it immediately; deleting the commit is not enough.

---

## 5. Public demo hardening (Phase 11)

- [ ] Synthetic data only; the repo and the deployed volume contain no class A or B data.
- [ ] LLM answers for the demo persona are **pre-computed and cached**; the live LLM is not needed for the main flow.
- [ ] No free-text input reaches an LLM. If a "try your own" box is added: rate-limit per IP, cap length, run `redact()`, show the budget remaining.
- [ ] Budget kill-switch tested (set a tiny limit; confirm graceful fallback to cached answers).
- [ ] HTTPS in front; the API has no write endpoints beyond the demo-safe ones (`respond`, `undo`, `replay`), each on a **copy** of the demo database that resets.
- [ ] CORS limited to the demo origin; sensible security headers.
- [ ] `GET /ledger/verify` returns `ok` on the demo database; the head hash is recorded.
- [ ] No debug endpoints; no stack traces in responses.
- [ ] Dependency audit run; lockfiles committed.
- [ ] Executor in the demo acts only on the simulated world.
- [ ] Tavily calls in the public demo come from recorded fixtures; the live key is not exposed to the browser; the daily cap and monthly credit budget are enforced.
- [ ] The demo stays up until the end of the judging period (15 Dec 2026) at a cost you have checked.

---

## 6. Rules for coding agents (Antigravity or any other)

Agents MUST:
- Read `AGENTS.md` and the invariants before changing code.
- Use synthetic data only.
- Fail closed in any new error path.

Agents MUST NOT:
- Read, print, log or commit `.env` contents or any secret.
- Paste real mail, calendar or file data into prompts, tests or fixtures.
- Add a network call outside `llm/client.py`, pack connectors or `workers/executor.py`.
- Add a dependency without noting it (name, purpose, licence) in the handoff report.
- Weaken, skip or delete a test to make a build pass.
- Edit `CONTRACT.md` (propose a change instead).
- Use a browser or terminal tool to log into personal accounts, download unknown binaries, or run scripts fetched from the internet.

Human setup: in Antigravity, require review for terminal commands that use the network or delete files (check the option names in your version).

---

## 7. What we do not claim

- Not a guarantee: the statistics assume the future resembles the past, and drift breaks that. Use the word **evidence**.
- Not formal verification.
- Redaction is best-effort, not anonymisation.
- Not a replacement for reviewing sent mail: level 2 sends only after a hold, and the user can cancel.
- Synthetic results do not prove real-world performance.

---

## 8. If something goes wrong

1. **Stop** the workers and take the API offline.
2. **Contain:** revoke the affected key or token; set `BUDGET_HARD_LIMIT_USD=0`.
3. **Check:** `probation ledger verify`; review `exposure_log` and `actions`.
4. **Fix** with a test that reproduces the problem.
5. **Record** what happened in `DECISIONS_AND_OPEN_QUESTIONS.md`.
