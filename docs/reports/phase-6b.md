# Phase 6b Handoff: Entity Facts Service (Tavily Vetting)

**Branch:** `phase-6b-entity-facts-tavily`  
**Phase:** 6b — Entity Facts Service (Tavily Vetting)  
**Lane:** Lane B (Member 2: Data & Packs)  
**Authority:** [`docs/TAVILY_AND_NEW_PACKS.md`](../TAVILY_AND_NEW_PACKS.md), [`docs/CONTRACT.md`](../CONTRACT.md) invariants I-21 to I-26, [`docs/PROMPTS.md`](../PROMPTS.md) section 15, and [`docs/MEMBER_SPLIT.md`](../MEMBER_SPLIT.md).

---

## Done

1. **Deterministic Web Query Guard (`backend/src/probation/web/query_guard.py`)**:
   - Codified strict character whitelist: letters, digits, whitespace, dot, hyphen, ampersand, and apostrophe (`^[a-zA-Z0-9\s.\-&']+$`).
   - Enforced maximum bounds: length $\le 80$ characters, tokens $\le 12$ tokens.
   - Built deterministic safety rejections:
     * Contains `@`, `<`, `>`, or `http`/`https`.
     * Runs of 6 or more digits (potential private ID / account numbers).
     * Redacted person placeholders (`<PERSON_\d+>`).
     * User name tokens from `settings.user_name_tokens` (case-insensitive).
   - Rejected queries abort outbound calls, record to `tavily_calls` audit table with `ok=0`, and return status `not_checked` (Invariant `I-23`).

2. **Deterministic EntityFacts Derivation (`backend/src/probation/web/derive.py`)**:
   - Implemented domain extraction with SLD + TLD awareness (handling multi-part suffixes like `.co.uk`, `.ac.in`, `.gov.in`).
   - Built homoglyph folding (`0->o`, `1->l`, `rn->m`, `vv->w`, strip `-` and `_`) and Levenshtein edit distance ($\le 2$) lookalike detection.
   - Built brand label containment detection (`brand-secure-login` vs `brand`).
   - Integrated local brand dictionary pre-check (`config/brands.json`) providing immediate `confirmed_official` or `lookalike` status with zero network requests.
   - Codified strict status precedence: `lookalike` > `reports_found` ($\ge 2$ scam/phishing hits) > `confirmed_official` (domain in top 3 and candidate) > `no_web_presence` > `unverified`.
   - Extracted plain-text citations (up to 3 `{title, url}` pairs) ensuring transparency without untrusted text injection.

3. **Production Tavily HTTP Client (`backend/src/probation/web/client.py`)**:
   - Communicates with Tavily Search API (`POST https://api.tavily.com/search`).
   - Implemented exponential backoff retries on HTTP 429 and 5xx.
   - Integrated credit accounting reading `usage.credits` from response.
   - Enforced hard daily and monthly budget checks against `settings.tavily_max_calls_per_day` (100) and `settings.tavily_monthly_credit_budget` (800).
   - Recorded every call in `tavily_calls` table under `Role.WEBFACTS`.

4. **WebFactsView and Process Isolation (`backend/src/probation/web/view.py`)**:
   - Built `WebFactsView` strictly exposing `RestrictionOnly` schemas.
   - Guaranteed that `RestrictionOnly` contains **zero** probability, weight, or evidence fields (Invariant `I-21`).
   - Enforced asymmetric veto: statuses `lookalike`, `reports_found`, and `no_web_presence` set `web_cap = 1` and reason `web_veto:{status}`. Statuses `confirmed_official`, `unverified`, and `not_checked` have `web_cap = 3` (no effect).
   - Verified static AST import boundary: `engine/policy.py`, `evidence.py`, `licence.py`, and `features.py` have zero imports from `probation.web` (`T-WEBISO`).

5. **Webfacts Worker (`backend/src/probation/workers/webfacts.py`)**:
   - Enforced `Role.WEBFACTS` database write boundaries via `RoleAccess`.
   - Vetting pipeline:
     1. Personal freemail bypass (`gmail.com`, `yahoo.com`, `outlook.com`, etc.).
     2. Fresh cache check in `web_facts` (TTL 30 days for `confirmed_official`, 7 days otherwise).
     3. Local verified brand pre-check (`config/brands.json`).
     4. Guarded `vet_ident` search query: `"{brand or domain} official website"`.
     5. Conditional guarded `vet_report` query if unverified: `"{domain}" scam OR fake OR phishing OR complaint`.
     6. Persist derived facts to `web_facts` table.

6. **Offline Deterministic Fixtures (`backend/tests/fixtures/web_facts_fixtures.json`, `backend/src/probation/web/fixtures.py`)**:
   - Shipped catalog of recorded entity fixtures (legitimate brands, homoglyph lookalikes, scam reports, zero-presence entities, and mock searches).
   - Built `load_web_facts_fixtures` helper populating `web_facts` with `origin='fixture'` and `present_knowledge=1` for offline test suites and reproducible backtests.

7. **Replay & CLI Integration (`backend/src/probation/engine/replay.py`, `backend/src/probation/cli.py`)**:
   - Replay timeline queries `WebFactsView(conn).get_entity_facts(sender_domain)`.
   - Caps proposal autonomy: `cap = min(cap, web_cap)` and records `web_veto` reasons.
   - Emits structured `web_json` (`status`, `cap`, `source_ids`) in `proposals` table.
   - Appended `probation webfacts vet <domain>`, `probation webfacts audit`, and `probation webfacts load-fixtures` subcommands.

---

## Files Changed / Created

- `backend/src/probation/web/__init__.py` (updated: exported client, view, derivation, fixtures)
- `backend/src/probation/web/query_guard.py` (updated: strict whitelist, 80-char/12-token caps, regex safety)
- `backend/src/probation/web/derive.py` (updated: domain parsing, homoglyphs, Levenshtein, local brands, status precedence)
- `backend/src/probation/web/client.py` (updated: production client, retries, budget guard, audit logging)
- `backend/src/probation/web/view.py` (updated: RestrictionOnly schema, web_cap derivation, TTL)
- `backend/src/probation/web/fixtures.py` (created: recorded fixture loader)
- `backend/src/probation/workers/__init__.py` (updated: exported vet_entity, vet_situations_batch)
- `backend/src/probation/workers/webfacts.py` (updated: full vetting pipeline under Role.WEBFACTS)
- `backend/src/probation/engine/replay.py` (updated: wired WebFactsView, web veto, proposals.web_json)
- `backend/src/probation/cli.py` (updated: appended webfacts CLI subcommands)
- `backend/tests/fixtures/web_facts_fixtures.json` (created: recorded offline fixtures)
- `backend/tests/unit/test_tavily_webfacts.py` (created: 16 comprehensive unit tests for T-WEBQ, T-WEBISO, T-VET)
- `docs/reports/phase-6b.md` (created: this report)

---

## Tests

1. **Automated Verification Gate (`.\make.cmd check`)**:
   - `ruff check backend`: Passed (0 errors).
   - `ruff format --check backend`: Passed (105 files checked, clean).
   - `mypy`: Passed (0 issues found across 102 source files in strict mode).
   - `pytest backend/tests/unit/test_tavily_webfacts.py`: 16 passed in 1.13s.
   - `pytest backend/tests/unit`: 120 passed in 6m 46s.
   - `pytest backend/tests/api`: 11 passed.
   - `pytest backend/tests/integration/test_backtest_e2e.py`: 3 passed.
   - `pytest backend/tests/property/test_no_peeking.py`: 1 passed (50 random cuts).

2. **Acceptance Tests Passing**:
   - `T-WEBQ`: Character whitelisting, 80-char / 12-token limits, blocked characters (`@`, `<`, `>`, `http`), 6+ digit runs, `<PERSON_n>`, user name tokens, audit recording without network on rejection.
   - `T-WEBISO`: Static AST graph check verifying zero `web` imports in `policy.py`, `evidence.py`, `licence.py`, and `features.py`. `RestrictionOnly` contains no probability/evidence fields. Exhaustive gate verification proves autonomy rank never increases with web veto.
   - `T-VET`: Homoglyph and hyphen lookalike detection (`g00gle.com`, `m1crosoft.com`, `paypal-security.example`), local brand list immediate resolution, scam report hit thresholds ($\ge 2$), and status precedence order.

3. **CLI Operations Verified**:
   - `python -m probation.cli webfacts vet github.com` -> `confirmed_official` via `local_brand_list`.
   - `python -m probation.cli webfacts vet g00gle.com --brand google` -> `lookalike` (lookalike of `google.com`).
   - `python -m probation.cli webfacts load-fixtures` -> loaded 9 recorded fixtures into `web_facts`.
   - `python -m probation.cli webfacts audit` -> renders call audit table.
