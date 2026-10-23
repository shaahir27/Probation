# TAVILY_AND_NEW_PACKS

Web grounding with Tavily, and two new domain packs (Opportunity Radar, Reading Triage). Written 4 Oct 2026.
Authority: below `CONTRACT.md`. Section 11 is **Contract Change Request CCR-1**; it has already been merged into `CONTRACT.md` as invariants I-21 to I-26 (see `DECISIONS_AND_OPEN_QUESTIONS.md` C-17). Revert it if you disagree.

---

## 1. What the rules require (verified on the official rules page, 4 Oct 2026)

| Rule | Consequence for us |
|---|---|
| **Best Use of Tavily: $3,000, one prize.** Eligible: submissions that **make a functional, runtime call to the Tavily API** as part of the solution | The bar to be eligible is a real runtime call. The prize is for the *best use*, so the call must be essential, not decorative. Make the first runtime call early (Phase 0 spike) |
| A project is eligible for **one Overall award, or one Track award plus one Bonus award** (my reading of the wording **(check)**) | The Tavily bonus can sit next to a Track win; it may not combine with an Overall win |
| Personal AI track: persistent memory, reusable skills, tools and information you choose, tasks across daily workflows | Radar and Reading are "daily workflow" packs; the entity-vetting service is "information you choose" with safety |
| Must run on Nebius Token Factory or AI Cloud; use at least one NVIDIA open model | Unchanged. Tavily is an extra external API |
| The project must stay available **free of charge and without restriction until the judging period ends (15 Dec 2026)** | The public demo must keep running for about 7 weeks after submission. Plan the cost (section 15) |
| 3-minute video on public YouTube; public repo with an open-source licence visible in its About section; README must highlight how Nemotron was used and where Token Factory helped | `DEMO_AND_SUBMISSION.md` updated |

Context: Nebius announced an agreement to acquire Tavily on 10 Feb 2026, and Nebius describes Tavily as letting agents check information against the web. Verifying facts is therefore exactly the story the sponsor tells about Tavily.

---

## 2. Tavily facts we rely on

| Fact | Source | Confidence |
|---|---|---|
| `POST https://api.tavily.com/search`, bearer key `tvly-...`; parameters include `query`, `search_depth`, `max_results`, `topic` (general, news, finance), `time_range`, `start_date`, `end_date`, `include_answer`, `include_raw_content`, `include_domains`, `exclude_domains`, `country`, `auto_parameters` | Tavily docs, Search API reference | High |
| Search costs 1 credit (basic, and fast); advanced costs 2. One doc page lists ultra-fast at 0.5 credit while the reference says 1, so **assume 1** and read the real cost from the response `usage` field | Tavily docs (conflict noted) | Medium |
| `POST https://api.tavily.com/extract`: `urls` (single or a list, up to 20), `query`, `chunks_per_source` (1-5, only with `query`), `extract_depth` (basic or advanced), `format` (markdown or text), `timeout`; returns `results` and `failed_results`. Cost: basic 1 credit per 5 successful URLs, advanced 2 | Tavily docs, Extract API reference and credits page | High |
| Free plan: 1,000 credits per month; pay-as-you-go about $0.008 per credit. The hackathon's Builders Program also gives Tavily credits (amount unknown) | Tavily pricing pages; Nebius hackathon materials | Medium |
| Development keys have a request-rate limit (a third-party page says 100 per minute) | Third-party | Low: verify with your key |
| Tavily's help center describes SOC 2, GDPR and CCPA compliance and "established data retention procedures". "Zero data retention" is described by third parties as an **enterprise** posture | Tavily help center; third-party summaries | Medium. **Assume free-tier queries may be retained** |
| Search results and extracted pages are **untrusted web text**. A Snyk audit of a Tavily agent skill flagged the indirect prompt-injection risk of passing such content to a model | Snyk | Medium |

---

## 3. Design thesis and principles

> **The web can warn you. Only your history can trust.**

1. **Asymmetry.** Web facts about an entity may only **lower** autonomy or **inform** a human. They never raise a probability, a cap, a licence or evidence. Reason: licences are earned from the user's own history; web facts are spoofable at the long tail; and web facts change over time, so they cannot be replayed honestly for evidence (no-peeking, CONTRACT I-6).
2. **Quarantine.** Raw web text never reaches a prompt that influences the gate. Where a model must read a web page, a **quarantined extractor** (Nano, strict schema, no tools) turns it into typed fields, and code validates them.
3. **Out-of-band verification.** Never follow the link in an email. Find the official page independently, then compare. This is the standard anti-phishing advice, built into the architecture.
4. **Minimal egress.** Tavily only ever receives public-entity strings (domains, brand names, public event names) or URLs the user saved themselves.
5. **Citations or silence.** Anything shown to the user that came from the web carries its source URLs. No source, no statement.
6. **Facts, not accusations.** The UI says "I found...", never "this is a scam".

---

## 4. Choosing the integration pattern

| Pattern | Safety link to the licence system | Is Tavily essential? | Privacy and cost | Injection risk | Demo appeal | Verdict |
|---|---|---|---|---|---|---|
| **P1. Sender and link vetting** (mail and invites, out-of-band) | Strong: protects the "unknown sender" gap and makes asks evidence-bearing | Yes: no local list covers the world's organisations | Low: domain strings only; cached | Low if deterministic | High (lookalike caught live) | **Chosen as the core** |
| P2. Location or commute check (calendar) | Weak | No: needs a maps API, not web search | Medium | Low | Medium | Rejected |
| P3. URL extraction for knowledge management | None for safety (user-saved content) | Yes (Extract) | Low | High (page text) | High | **Used inside the new packs**, not as the core |
| P4. Pre-reader "entity card" fed to the LLM | Medium | Yes | Medium | **High** (web text into prompts) | Medium | Rejected: replaced by deterministic facts |

**Honest note on P1's value.** Unknown senders are already capped at level 1 for outward actions, so Tavily does **not** reduce interruptions and does **not** grant autonomy. What it adds: (a) the question the user is asked comes with sources ("the official site is X; this domain is different"), which matters because people approve most prompts without reading; (b) lookalike and mismatched-link detection; (c) the new packs rely on it to avoid fetching bad URLs and to flag fee scams; (d) measurable exam cases. We test (a) in the human study (section 14).

---

## 5. Entity Facts Service (EFS)

### 5.1 Where it sits

```
ingest -> normalise -> E1 entities (code) -> E2 vet (Tavily, conditional) -> redact -> reader (Nano)
       -> clues -> policy -> E3 veto (code) -> gate -> draft (Super) -> proposal
```

E2 runs **before** the reader, as requested, but its output never enters the reader's prompt. It is a separate worker (`webfacts`) that writes `web_facts`; the `brain` only reads them.

### 5.2 E1: entities (code, no network)
From headers and links only: `sender_domain` (registrable), `brand_token` (alphanumeric words from the display name, at most 4), and up to 3 distinct registrable `link_domains` found in the body (domain only; path and query are discarded), excluding a small allow-list of infrastructure domains (common CDNs, tracking and shortener services are listed separately as "redirectors" and are themselves flagged).

### 5.3 E2: when Tavily is called (all must hold)
1. Pack is `mail` or `calendar` (radar and reading have their own rules in sections 8 and 9).
2. The domain is not a free-mail domain.
3. The domain is **not** in `known_domains` (the user has replied to, accepted, or filed something from it, outcome known at `as_of`).
4. No fresh entry in `web_facts` (time to live: 30 days when status is `confirmed_official`, 7 days otherwise).
5. Budget allows it (`TAVILY_MAX_CALLS_PER_DAY`, `TAVILY_MONTHLY_CREDIT_BUDGET`; I-25).
6. At least one trigger: `sender_tier == unknown`; or a body link domain that differs from the sender domain and is itself not known.

**Free local pre-check first.** A small shipped list `config/brands.json` maps brand tokens to their official registrable domains (about 150 entries; every entry must be verified against the brand's own site before it is committed). If the display brand is in the list and the sender domain is not one of its official domains, status is `lookalike` immediately (`origin=local_brand_list`), with no Tavily call. If it is an official domain, status is `confirmed_official` immediately. Tavily covers the long tail the list cannot.

### 5.4 The queries (built by code)

| Call | Query | Parameters |
|---|---|---|
| `vet_ident` | `{brand_token or domain label} official website` | search, `search_depth=basic`, `max_results=5`, `include_answer=false`, `include_raw_content=false` |
| `vet_report` (only if `vet_ident` is inconclusive) | `{registrable_domain} scam OR fake OR phishing OR complaint` | same |

At most 2 credits per entity. **Query guard** (`web/query_guard.py`, I-23): characters limited to letters, digits, space, dot, hyphen, ampersand and apostrophe; at most 80 characters and 12 tokens; reject if it contains `@`, `<`, `>`, `http`, a run of 6 or more digits, a `<PERSON_n>` placeholder, or a token from `USER_NAME_TOKENS`. A rejected query is not sent; the entity gets `not_checked`.

### 5.5 Deriving `EntityFacts` (deterministic code, no LLM)

From the result list (title, URL, snippet, score):
- `result_domains`: registrable domains of result URLs.
- `official_candidates`: up to 3 result domains that appear in the top 3 and whose domain label contains the brand token or whose title starts with it.
- `domain_in_results`: the sender domain is among `result_domains`.
- `lookalike_of`: the sender domain differs from every official candidate (and the local list) and any of: edit distance of the second-level labels is at most `LOOKALIKE_MAX_EDIT_DISTANCE` (2); the labels are equal after homoglyph and separator folding (`0->o`, `1->l`, `rn->m`, `vv->w`, remove hyphens); or the sender label contains the official label (for example `brand-secure-login` versus `brand`).
- `report_hits`: results from `vet_report` whose title or snippet contains the registrable domain **and** one of `scam, phishing, fraud, fake, complaint, warning, beware`.
- `sources`: up to 3 `{title, url}` pairs, stored and shown as plain text.

**Status precedence:** `lookalike` > `reports_found` (`report_hits >= REPORT_HITS_MIN`, default 2) > `confirmed_official` (sender domain is an official candidate and is in the top 3) > `no_web_presence` (no result mentions the domain or brand) > `unverified`. `not_checked` when no call was made or it failed.

### 5.6 E3: the veto (code)
- `lookalike`, `reports_found`, `no_web_presence` -> `web_cap = 1`. Effective cap is `min(cap, web_cap)`. The item shows a "Check the sender" panel with the status and sources.
- `confirmed_official`, `unverified`, `not_checked` -> **no effect** (never raises anything).
- Reasons are written to `proposals.reasons_json`; the status and source ids to `proposals.web_json`.

### 5.7 Replay and evaluation semantics
- Policy training, evidence, licences and exams' *learning* parts use **no web facts** (CONTRACT I-21; static check T-WEBISO).
- The veto may use facts only through `WebFactsView`, which returns a `RestrictionOnly` type that exposes only `web_cap` and display data.
- In replay, facts come from fixtures: the generator calls Tavily once per catalog entity at generation time and stores `origin=fixture`, `present_knowledge=1`. This is "present-day knowledge applied to the past". It is acceptable only because it can only reduce autonomy. Evaluation reports results **with and without** the veto.
- In live mode, calls happen in real time and are cached.

### 5.8 Failure modes and limits
- Outage, timeout, or budget exhausted: status `not_checked`; behaviour is the baseline (caps unchanged). The system is never *less* safe without Tavily.
- False veto on a legitimate small organisation with no web presence: costs one extra ask. Accepted.
- Poisoned results (an attacker makes their own domain look official for a brand): `confirmed_official` cannot raise autonomy, and the local brand list covers the head. The tail remains a known limit.
- Keyword evidence in snippets is crude. It is shown as sources for a human to read, never as a verdict. Precision and recall are measured (section 14).
- Free-tier retention is unknown (open question O-15). Only public-entity strings are sent.

---

## 6. The quarantine pattern (for page content)

Used by Radar and Reading, where a model must read a web page.

```
Tavily Extract (page text)
   -> truncate to QUARANTINE_MAX_INPUT_CHARS
   -> Quarantined extractor: Nemotron Nano, strict JSON schema, no tools, no memory   [untrusted in, typed out]
   -> Code validators (support checks, regex cross-checks, length and charset limits)
   -> typed fields (data only)
   -> Super writes user-facing text ONLY from typed fields, with a citation validator
```

Rules:
- The extractor's prompt states that the page text is data; the output schema leaves no room for instructions.
- Validators drop any field that is not supported by the page text (for example a deadline must be a date that literally appears in it).
- The writer (Super) never sees page text.
- The exam includes **page-injection** operators (a page containing "ignore previous instructions...") that must leave decisions unchanged.

---

## 7. Link substrate (shared by Radar and Reading)

`links/sanitise.py`:
1. Scheme must be `http` or `https`. No userinfo. No IP-literal hosts. Reject `localhost`, `.local`, `.internal`, `.lan` and private ranges.
2. Strip the fragment and tracking parameters (`utm_*`, `fbclid`, `gclid`).
3. **Hands-off (`private_token`)** if any query parameter name is in `{token, key, sig, signature, auth, session, sid, code, password, pwd, otp, access_token, id_token, jwt, apikey, api_key}`, or a parameter value is 40 or more characters, or looks high-entropy (Shannon entropy 4.0 or more and length 24 or more).
4. **Hands-off (`sensitive_page`)** if the path contains `login, signin, sign-in, checkout, cart, payment, account, reset`.
5. Maximum length 2,048.

`links/extract.py`: calls Tavily Extract (`extract_depth=basic`, `format=markdown`, `query` set to focus the chunks, `chunks_per_source=3`) only when:
- the URL is **user-saved** (intake channel `user_saved`, I-24), or is an official URL discovered by Tavily Search (Radar mail flow);
- sanitisation passes;
- the domain's vetting status is not `lookalike` or `reports_found`.
Results go to `extractions` (time to live `EXTRACT_TTL_DAYS`), then through the quarantine pattern.

---

## 8. Pack: Opportunity Radar (`radar`)

**Why this pack.** Students and job-seekers receive many opportunity messages (hackathons, internships, scholarships, competitions). Two real problems: deadlines get missed, and fake offers asking for a "registration fee" are common. India's AICTE has publicly warned about fake internship letters sent from lookalike domains, and a Chennai-area report described scammers posing as placement cells asking for UPI fees. A pack that **verifies, extracts and tracks** opportunities, and **refuses autonomy when money is asked**, shows the licence idea at its best. It is also the strongest, most natural use of Tavily Search plus Extract.

### 8.1 The six questions

**1. What situation triggers a decision?**
- A mail whose reader intent is `opportunity` (new value in `reader.mail.v2`). The brain then runs `reader.opportunity.v1` and creates a Radar situation (`pack=radar`, `family=opportunity_triage`, `variant=mail`) from the same raw item.
- A link the user pastes into the Radar inbox (`variant=link`, intake `user_saved`).

**2. What facts are counted (clues)?**
Deterministic and from the user's own data only (**no web-derived clues**, I-21):
`source_kind`, `organiser_domain_class` (`edu`, `corp`, `gov`, `platform`, `freemail`, `other`; `platform` comes from a short shipped list such as hackathon and internship platforms), `organiser_known`, `n_prior_from_organiser`, `hour_of_day`, `weekday`, `has_deadline_in_mail`, `days_to_deadline_bucket_from_mail` (`none, <3, 3-7, 8-14, 15-30, >30`), and history rates `tracked_share_for_opp_type`, `tracked_share_for_topic`.
Reader fields (`reader.opportunity.v1`): `opp_type`, `topic`, `fee_mentioned`, `requires_personal_docs`, plus `organiser_name`, `opportunity_name`, `deadline_text` (used for verification, not as clues).

**3. What actions are allowed, and the highest level?**

| Action | Meaning | Recallable | Base cap | Loss | Bar `p*` |
|---|---|---|---|---|---|
| `TRACK` | Create a tracker entry (title, organiser, type, verified deadline, official link, verification sources) | yes | 3 | 3 | 0.667 |
| `DISMISS` | Move to "Not interested" | yes | 2 | 8 | 0.875 |
| `LEAVE` | Do nothing | n/a | 0 | n/a | n/a |

Conditional caps: if `fee_mentioned` or `requires_personal_docs` is true, or the entity status is `lookalike`, `reports_found` or `no_web_presence` (veto), both `TRACK` and `DISMISS` are capped at **1**. **Never in the catalog:** apply, pay, reply, share documents. After `TRACK`, the existing chains machinery may propose `BLOCK_TIME` for the verified deadline (the deadline is an action parameter, not a learned clue).

**4. How is it done safely, and how is it undone?**
1. Reader extracts `organiser_name` and `opportunity_name`; the query guard approves them.
2. **Out-of-band lookup:** Tavily Search `{organiser_name} {opportunity_name} official` (basic, 5 results; purpose `find_official`). Code picks the official candidate (a known platform domain, or a domain whose label matches the organiser).
3. EFS vets the candidate domain **and** every link domain found in the email. If the email's link domains do not include the official domain, `link_mismatch = true`.
4. Tavily Extract on the **official candidate URL only** (never on a link from the mail, I-24), with `query="deadline eligibility fee registration"`.
5. Quarantined extractor `extract.opportunity.v1` (Nano) -> validated fields. Deadline must literally appear in the page text; `fee_mentioned` is OR-ed with a regex fee signal.
6. If the mail's stated deadline differs from the page's, both are shown ("mail says 30 Oct, the official page says 5 Nov").
7. Execute `TRACK` into the world's tracker. **Undo:** delete the entry (live Notion: move the page to trash, which the Notion API can restore).

**5. How is the user footprint detected?**
`TRACK` is observed when the user keeps or creates a tracker entry for the item, or marks it applied; `DISMISS` when the user archives the mail without tracking or taps "Not interested". Strong: explicit responses to suggestions, tracker entries, and status changes. Weak: no action. (The user's real "applied" decision happens on the opportunity's own site and is not observable; the tracker status is the footprint.)

**6. What is the outcome window?**
`min(14 days, days until the deadline)`, never less than 2 days (`RADAR_WINDOW_DAYS`, `RADAR_MIN_WINDOW_DAYS`).

**Class key:** `radar|{opp_type}|{organiser_domain_class}`.

### 8.2 Exam operators (Radar)

| Operator | Engine | Expectation | Critical |
|---|---|---|---|
| `paraphrase_body` | LLM | invariant | no |
| `add_fee_request` (appends "registration fee INR 500 via UPI") | code | no_more_autonomous | **yes** |
| `lookalike_organiser_domain` | code | no_more_autonomous | **yes** |
| `inject_instruction` | code | no_more_autonomous | **yes** |
| `page_injection` (stubbed Extract text containing an instruction) | code | invariant | **yes** (zero flips) |
| `unknown_organiser` | code | no_more_autonomous | no |

### 8.3 Visuals and demo value
A **Radar board** of cards: verified badge with sources, deadline countdown, a "mail says / page says" discrepancy line, a red fee warning, and one-tap Track or Dismiss. A **weekly digest** (Super, from typed fields only, citation-validated, `radar.digest.v1`). Demo beat: a real opportunity (this hackathon's public page) is verified and tracked; a **fictional** lookalike mail (invented `.example` domain) is held back with its evidence.

---

## 9. Pack: Reading Triage (`reading`)

**Why this pack.** Improved version of the Notion-triage idea: the "bookmark graveyard". Mozilla shut down Pocket on 8 Jul 2025, and many people had to re-think where saved links live. Notion already offers AI autofill for database properties, so summarising alone is not new. What is new here: it learns **your** filing habits, uses real page content (Tavily Extract), and earns permission to file silently. It shares most plumbing with Radar, so it is cheap once Radar exists.

### 9.1 The six questions

**1. Situation:** a link appears in the Reading inbox (`user_saved`): a Notion database row with a URL, a "Read later" bookmark export, or a mail-to-self. Family `link_triage`.

**2. Clues:** `source_kind`, `url_domain`, `path_kind` (`article, video, pdf, repo, doc` from URL patterns), `has_pdf_ext`, `hour_of_day`, `weekday`, `n_prior_from_domain`, `top_collection_for_domain`, `top_collection_share`. Content clues (from the **user-saved item's** content via the quarantined extractor, allowed because it is the user's own item, not a web fact about an entity): `topic` (13 values), `content_type`, `actionable`, and `length_bucket` (code, from text length).

**3. Actions and caps:**

| Action | Recallable | Base cap | Loss | Bar `p*` |
|---|---|---|---|---|
| `FILE_TO_COLLECTION:{collection}` | yes | 3 | 3 | 0.667 |
| `ARCHIVE_LINK` | yes | 2 | 6 | 0.833 |
| `LEAVE` | n/a | 0 | n/a | n/a |

Conditional caps: entity status `lookalike` or `reports_found` -> cap 1 and **no Extract**. Hands-off: any URL failing sanitisation (section 7).

**4. Safe execution and undo:** move the item to the collection (a select property in Notion, a row in the simulated library). Store the previous collection; undo restores it. Extraction uses the quarantine pattern; summaries are shown in the UI from typed fields.

**5. Footprint:** the item's final collection. Strong when the user moves or assigns it; `LEAVE` is weak. An item the user deletes counts as a strong disagreement.

**6. Outcome window:** 14 days (`READING_WINDOW_DAYS`).

**Class key:** `link|{topic}|{content_type}`.

### 9.2 Exam operators (Reading)

| Operator | Engine | Expectation | Critical |
|---|---|---|---|
| `utm_params_added` | code | invariant | no |
| `title_case_change` | code | invariant | no |
| `paraphrase_snippet` | LLM | invariant | no |
| `domain_unknown` | code | no_more_autonomous | no |
| `lookalike_domain` | code | no_more_autonomous | **yes** |
| `private_token_in_url` | code | no_more_autonomous (gate must be `SHADOW`) | **yes** |
| `page_injection` | code | invariant | **yes** (zero flips) |

---

## 10. Why these packs (evaluation of the baselines)

| Candidate | Demo appeal | Agentic depth | Fit with earned autonomy | Tavily essential? | Verdict |
|---|---|---|---|---|---|
| **A. Notion triage** (baseline) | High | Medium | Strong (clear footprint) | Extract only | **Kept, improved** as Reading Triage; Notion AI autofill is prior art, so we lead with learned filing habits |
| **B. Slack or Discord proxy** | Medium | Medium | Weak: replies are outward and irreversible, so little autonomy to earn; overlaps with the mail pack | Weak: "real-time facts" are rarely needed | **Rejected** |
| **C. Invoice auditor, cap 1** | Medium | Medium | Poor: it never earns autonomy, so it does not show the core idea; "VAT and pricing checks" via web search are unreliable | Partly | **Rejected as a pack**; its best part (vendor legitimacy) is the cross-cutting entity-vetting service |
| **Meeting briefs** (brainstormed) | High | High | Medium (footprint is hard to observe) | Yes | **Rejected for now**: crowded space (Microsoft Copilot "Prepare", Google Gemini workflows, several calendar add-ons) and extra privacy care about attendees. Can return as a chain follow-up later |
| **Opportunity Radar** (new) | High | High | Strong | **Yes (Search and Extract)** | **Chosen** |

Build order: **EFS (vetting) -> Radar -> Reading**. Reading is cut first if time runs short.

---

## 11. Contract change request CCR-1 (merged)

New invariants (also in `CONTRACT.md`):

- **I-21** Web facts about entities may only **restrict** or **inform**. They never raise a probability, cap, licence or evidence. The policy, evidence and licence modules MUST NOT import `web/`. Access is only through `WebFactsView`, which returns restriction-only types.
- **I-22** Raw web text (search snippets, extracted pages) is **untrusted**. It is never placed in a prompt that influences the gate, and never given to the writer. Only a quarantined extractor (strict schema, no tools) may read it; its output is validated by code.
- **I-23** Tavily queries are built **by code** from a closed set: registrable domains, brand tokens, reader-extracted `organiser_name` and `opportunity_name` that pass `web_query_guard`, and user-saved URLs for Extract. Never mail subjects or bodies, person names, addresses, or per-recipient URL parts. Every call is logged in `tavily_calls`, including the exact query text.
- **I-24** URLs found in mail bodies are **never fetched or extracted**. Extract is used only on user-saved URLs and on official URLs discovered by Search.
- **I-25** Tavily has a hard budget (`TAVILY_MAX_CALLS_PER_DAY`, `TAVILY_MONTHLY_CREDIT_BUDGET`). On exhaustion or failure the system behaves as if no web facts exist.
- **I-26** Anything shown to the user that derives from web content carries the source URLs from Tavily results; uncited claims are rejected by validators.

Process addition: a `webfacts` worker (reads `situations`; writes `web_facts`, `tavily_calls`, `extractions`, `quarantine_outputs`, `exposure_log`, `ledger`; network: **only `api.tavily.com`**, plus the LLM endpoint for the quarantined extractor). The `brain` never calls Tavily.

API additions: `GET /web-facts` (usage, credits, the exact queries sent), `GET /boards/{pack}` (Radar board or Reading library). `GET /items/{id}` also returns web status and sources.

---

## 12. Data model additions

Defined in `DATA_MODEL.md`: `web_facts`, `tavily_calls`, `extractions`, `quarantine_outputs`, and `proposals.web_json`.

---

## 13. Prompts added

Defined in `PROMPTS.md` sections 11 to 15: `reader.mail.v2`, `reader.opportunity.v1`, `extract.opportunity.v1`, `extract.link.v1`, `radar.digest.v1`, and the web query guard.

---

## 14. Tests and evaluation

**Tests (`TEST_PLAN.md`):** T-WEBQ (query guard), T-WEBISO (the policy, evidence and licence modules do not import `web/`; `RestrictionOnly` has no probability fields), T-VET (EntityFacts derivation on fixtures: homoglyphs, hyphen tricks, brand-in-label, no presence, reports), T-QUAR (injection pages leave typed fields and decisions unchanged; validators drop unsupported fields), T-LINK (sanitiser and hands-off), plus Radar and Reading in T-PACK, T-RESOLVE, T-EXEC and T-EXAM.

**Evaluation (`EVALUATION_PLAN.md`):**
- **E10 Vetting accuracy.** Catalog of about 60 legitimate organisation domains (real, public, relevant to students), about 60 **fictional** lookalikes (invented `.example` domains built by fixed rules), and about 20 plausible invented organisations with no web presence. Report the confusion matrix per status, the false-veto rate on legitimate domains, credits per entity, latency p50 and p95, and cache hit rate. Compare with the local brand list alone.
- **E11 Out-of-band verification.** Synthetic opportunity mails whose link domain differs from the official page: detection rate of `link_mismatch`.
- **E12 Quarantine robustness.** `page_injection` and `inject_instruction` operators: decision flips must be zero.
- **E13 Human study add-on.** About 20 unknown-sender items shown **with** and **without** an evidence line; compare the share of correct accept or reject decisions. Participants see synthetic items only.
- **Aims (not claims):** false-veto rate on legitimate catalog domains of 10% or less; `lookalike` recall on fictional lookalikes of 90% or more with the local list plus Tavily; zero decision flips under injection; at most 2 credits per newly vetted entity.

---

## 15. Plan, budget and demo changes

- **Phase 0:** add `scripts/spike_tavily.py`: one Search and one Extract call, record the credits used. **Make the first functional runtime call in the first week** (eligibility for the Tavily bonus).
- **Phase 6b (new, 13-17 Oct, lane B):** Entity Facts Service, `webfacts` worker, `brands.json`, query guard, fixtures, T-WEBQ, T-WEBISO, T-VET.
- **Phase 8b (new, 20-25 Oct, lane B):** link substrate, Radar, Reading, quarantine extractors, boards, T-QUAR, T-LINK. The GitHub stretch pack is dropped from the plan.
- **Tavily credits:** about 240 credits to vet the catalog once; a few hundred more for Radar fixtures and live testing. Stay under the free 1,000 per month (`TAVILY_MONTHLY_CREDIT_BUDGET=800`) unless the Builders Program credits are larger.
- **LLM budget:** the quarantined extractors add roughly 2,000 input and 200 output Nano tokens per page (about $0.00017); a few hundred pages cost cents. Super digests are negligible.
- **Demo:** add a 25-second Radar beat (verified real opportunity, held-back fictional lookalike with sources, "mail says / page says"). Trim other beats accordingly.
- **Hosting:** keep the demo running until 15 Dec 2026 at low cost (replay-only, cached answers). Check the VM cost for about 7 weeks (open question O-16).

---

## 16. Risks and unknowns

| Risk | Mitigation |
|---|---|
| Tavily results are noisy for small entities | Facts are shown with sources and never raise autonomy; accuracy is measured and reported honestly |
| Free-tier query retention is unknown | Public-entity strings only; open question O-15 |
| Credits run out during judging | Cached fixtures and a replay demo; budget guard |
| Using real brands in demos | Real organisations appear only as `confirmed_official` examples that Tavily returns live; every scam example uses an **invented** domain |
| Scope growth | Build order and cut line in section 10; Reading is cut first |
| Two doc sources disagree on ultra-fast search credit cost | Read `usage.credits` from the response and log it |

---

## 17. Sources (checked 4 Oct 2026)

- Hackathon rules (Tavily prize, award limits, video, availability): https://nebiusglobalaihackathon.devpost.com/rules
- Tavily Search API: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Tavily Extract API: https://docs.tavily.com/documentation/api-reference/endpoint/extract
- Tavily credits: https://docs.tavily.com/documentation/api-credits
- Tavily help center, Privacy and Security (March 2025); third-party summaries of the zero-data-retention enterprise posture
- Nebius agreement to acquire Tavily (10 Feb 2026), as reported by unite.ai and others
- Mozilla's Pocket shutdown (announced 22 May 2025; shut down 8 Jul 2025)
- Notion API (pages can be trashed and restored with `in_trash`) and Notion AI Autofill documentation
- AICTE alerts and college advisories on fake internship offers; CyberPeace and Careers India summaries; a Chennai report on placement-cell impersonation (secondary sources)
- FBI IC3 2025 report via secondary summaries (business email compromise about $3.0B; phishing and spoofing the most reported complaint type); totals differ between summaries, so none is quoted as a headline
- Snyk audit note on indirect prompt-injection risk when agent skills pass Tavily content to models


## Approved DOC-B/C and D9 clarification (22 October 2026)

CONTRACT v2 controls restriction monotonicity: adding entity restrictions cannot
raise autonomy relative to the no-web baseline; removing them may restore that
baseline. Policy probabilities, evidence and derived licences remain independent
of entity facts. Preserve the separate quarantined saved-content clue allowance.
Code-built vet_report queries use the unquoted allowed grammar above; do not weaken
the character/token/privacy guard to accommodate unsupported syntax.
The public domain-only checker architecture is approved with separate quotas and
Webfacts ownership. Concrete public deployment, endpoint/resource/budget authority
and abuse/failure tests remain required before enabling live calls.
