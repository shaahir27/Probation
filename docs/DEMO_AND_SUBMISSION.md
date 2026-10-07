# DEMO_AND_SUBMISSION

The demo script, the video storyboard, and the submission checklist. Authority: below `CONTRACT.md`.
The requirements in section 1 were **checked against the official Devpost rules page on 4 Oct 2026**. Re-read it before submitting in case it changed (open question O-11).

---

## 1. What the hackathon requires (verified 4 Oct 2026)

- Project runs on **Nebius Token Factory or Nebius AI Cloud**, and uses **at least one NVIDIA open model** (we use Nemotron).
- A **public code repository** with an **open-source licence** that the repository's About section shows. The README must say how Nemotron was used and where Token Factory helped.
- A **demo video of at most 3 minutes** on **public YouTube**, showing the project working on the device it was built for.
- A **working demo URL**. The project must stay **available free of charge and without restriction until the judging period ends (15 Dec 2026)**; judges are not required to test it.
- Written **feedback on the tools** you used. If the project existed before, explain what changed.
- Deadline: **30 Oct 2026, 10:00 am PDT (10:30 pm IST)**. Our target: submit on **29 Oct**.
- Judging criteria: technological implementation, design (a complete product), potential impact, quality of the idea.
- **Best Use of Tavily ($3,000, one prize):** open to submissions that make a **functional runtime call to the Tavily API** as part of the solution. A project is eligible for one Overall award, or one Track award plus one Bonus award (my reading of the wording **(check)**, open question O-18).
- Evidence to prepare for the Tavily prize: the `tavily_calls` table and the `GET /web-facts` page (exact queries and credits), one live call in the video, and a README section explaining why Search and Extract are essential (`TAVILY_AND_NEW_PACKS.md`).

**Licence choice:** pick MIT or Apache-2.0 in Phase 0 (Apache-2.0 adds a patent grant; MIT is shorter). Put `LICENSE` at the repo root and name it in the README's first lines.

---

## 2. The demo, beat by beat

Persona: **Meena** (synthetic student). The demo database is pre-run to a chosen simulated date; the replay clock runs at an adjustable speed.

| Beat | What the viewer sees | Screens and data needed |
|---|---|---|
| **1. The driving test** | "Before it touches anything, here is what it would have done with your last six months." A report card: same / different / would-ask counts per family | Report card page; per-family numbers |
| **2. A day in the life** | A newsletter archived silently; a college PDF moved to the right folder (undo button visible); an early-morning invite declined after a hold; a recruiter mail answered with a polite-no draft; a professor's deadline mail producing one combined suggestion (draft reply plus block time) | Queue, Actions, Chains pages; replay playing |
| **3. Licences earned** | A ladder per task type: watch, suggest, do with undo, do silently, with the evidence ("58 clean agreements" style) beside each | Licences page with lower bounds and counts |
| **4. The exam** | A shortcut policy (or an injected mail) fails the trick questions; the proper policy passes | Exams page with flipped cases highlighted |
| **2b. Opportunity Radar (Tavily)** | A hackathon-style email: the system searches for the official page itself, compares it with the email's link, reads the page (deadline, fee, eligibility), and offers to track it. A fictional lookalike email shows "Check the sender" with sources and no automatic action | Radar board, Item detail, Privacy (Tavily usage) |
| **5. Habit change** | Meena's habit changes (early invites now accepted); the system raises a drift alarm and demotes itself, then re-earns | Metrics page drift timeline; Licences page change |

Also visible throughout: the **ledger verify badge** and the **exposure** counter (how little text left the machine).

The screen-by-screen behaviour behind these beats is in `USER_FLOW.md` (section 10 maps each beat to screens).

### Design rules for the dashboard
- Plain words, no jargon on first screen ("Allowed to: suggest").
- Every automatic action shows **why** (the evidence line and the three most similar past cases) and an **undo** button.
- Works on a phone-sized screen.
- Empty, loading and error states for every page.

---

## 3. Video storyboard (3:00)

| Time | Content |
|---|---|
| 0:00-0:20 | **Hook.** "I wouldn't give a new assistant my bank login on day one. I'd have them shadow me, do the small stuff, and earn the rest. AI agents skip that." Show the 93% approval statistic (reported by Anthropic for coding agents) **(verify wording before use)** |
| 0:20-0:50 | **Beat 1:** the driving test and report card |
| 0:50-1:20 | **Beat 2:** a day in the life across mail, calendar, files and a chain |
| 1:20-1:45 | **Beat 2b (Tavily):** a real opportunity is verified through Search and Extract and tracked; a fictional lookalike mail is held back with its sources; "mail says 30 Oct, official page says ..." |
| 1:45-2:05 | **Beat 3:** licences and the evidence behind them |
| 2:05-2:25 | **Beat 4:** the exam catches a cheat or an injection (including text hidden in a web page) |
| 2:25-2:42 | **Beat 5:** habit change, automatic demotion |
| 2:42-3:00 | **Close.** One architecture slide (Nemotron on Nebius; Tavily as web grounding; the workers; the ledger), two headline numbers from the evaluation, and the line "evidence, not guarantees" |

Rules: no real data on screen; captions on; record at 1080p; practise twice with a stopwatch; keep a 2:50 cut.

---

## 4. Pre-submit checklist

### Code and repo
- [ ] `LICENSE` at the repo root; README states it at the top.
- [ ] README: what it is, the problem, the architecture diagram, how to run (`make setup`, `make synth`, `make backtest`, `make serve`), results with seeds and models, limits (synthetic data, no guarantees), team and credits.
- [ ] Fresh-clone test: `make setup && make synth && make backtest` works on a clean machine.
- [ ] `make check` passes; coverage meets `TEST_PLAN.md` targets.
- [ ] Secrets scan clean; `.env` not in the repo; history checked for leaked keys.
- [ ] No real personal data anywhere in the repo.
- [ ] Dependency audit run; lockfiles committed.

### Demo
- [ ] Demo URL loads from a phone on mobile data and a fresh browser profile.
- [ ] Runs on **Nebius** (virtual machine plus Token Factory); note this in the README.
- [ ] README explains how Nemotron (Nano, Super, Ultra) is used and where Token Factory helped.
- [ ] README explains the Tavily integration (Search for vetting and official-page lookup, Extract for reading) and links the evidence (`tavily_calls`, `/web-facts`).
- [ ] The demo stays up until 15 Dec 2026; hosting cost checked.
- [ ] Every scam example in the demo uses an **invented** domain; no real organisation is called a scam anywhere.
- [ ] Budget kill-switch and rate limits tested.
- [ ] `GET /ledger/verify` returns `ok`; head hash recorded in the submission text.
- [ ] Backup: a recorded screen capture of the full demo, stored separately.

### Evaluation
- [ ] Aggregate results and figures committed under `docs/results/`.
- [ ] Each result lists seed, personas, model names, prompt versions and date.
- [ ] Limits section states: synthetic data; baselines; test personas held out.

### Submission page
- [ ] Project title, tagline and description (what it does, how it was built, what Nemotron and Nebius do).
- [ ] Track selected: Personal AI.
- [ ] Repo link, demo link, video link (public).
- [ ] Tools feedback written (specific, useful: what worked, what was missing, rate limits, JSON-schema behaviour, docs).
- [ ] Team members added.
- [ ] Submitted by **29 Oct**, with the deadline buffer unused.

---

## 5. Demo failure plan

| Failure | Response |
|---|---|
| LLM endpoint slow or down | The demo uses cached answers; the main flow does not need a live call |
| Demo site down | Switch DNS or link to the backup screen recording; the video is the primary evidence |
| Replay shows an unexpected result | Use the seeded persona and fixed clock so the run is identical every time; keep the known-good database snapshot |
| A judge enters odd text (if a free-text box exists) | Rate limit; redaction; no tools; fail closed |

---

## 6. How it maps to the judging criteria

| Criterion | Our evidence |
|---|---|
| **Technological implementation** | Hash-chained ledger; no-peeking property test; per-class statistics with pooling; trick-question exam; Executor separated from the models; Nemotron tiers (Nano, Super, Ultra) on Nebius Token Factory; optional OpenShell lock |
| **Design** | A dashboard a non-technical person can read; evidence and undo on every action; works on a phone |
| **Potential impact** | Targets the supervision cost of delegating to AI; covers daily workflow (mail, invites, files, follow-up chains); honest, reproducible numbers |
| **Quality of the idea** | Earned autonomy per task type, a backtest on the user's own history, and an exam that tests trick cases; not a generic assistant or a risk score |

---

## 7. Honest framing for the pitch

- Say: "one engine that safely hands over **any repeated decision that leaves a footprint**, proven on mail, calendar, files and follow-up chains."
- Do not say: "automates everything you do on a computer" or "guaranteed safe."
- Acknowledge prior art (enterprise task mining and RPA; "ask when unsure" research). Our difference: personal, footprint-based, and every permission is earned with evidence.
