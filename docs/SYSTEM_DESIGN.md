# Probation: System Design in Plain Words (v2)

Version 2 · written 2 Oct 2026, audited 3 Oct 2026 · NVIDIA Global AI Hackathon, Personal AI track
Submission deadline: 30 Oct 2026, 10:00 am PDT (10:30 pm IST).

> **Note:** this document explains the idea in plain words. Where the specs differ (`CONTRACT.md`, `ENGINE_SPEC.md`, `DATA_MODEL.md`, `PACKS_SPEC.md`, `PROMPTS.md`), **the specs win**. The differences are listed in `DECISIONS_AND_OPEN_QUESTIONS.md` section 2.

**What changed from v1**
1. It is no longer "email only". It is **one engine with plug-in "domain packs"**: mail, calendar, files and downloads, "chains" across tools, and (stretch) developer notifications.
2. **No OpenRouter and no free-tier models.** The AI models are NVIDIA's **Nemotron** models. Every call to them, including during prototyping, goes through **Nebius Token Factory**, the cloud service that hosts them (see "Who is who" in section 13).
3. A new section explains the four "windows" through which a system can see your work, with real sources, and which ones we refuse to use.

Words in *italics* are explained in the glossary. Anything I could not verify is marked **(check)** or **(assumption)**.

---

## 1. The problem in plain words

**Part A: delegation is broken.** Everyone wants an AI that does things for them. Today there are two ways to get it:

1. **It asks permission for everything.** You stop reading and click "yes". In a large study of coding agents, reported by Anthropic, users approved about 93% of permission prompts.
2. **You trust it blindly.** It works until one expensive mistake, and then you never trust it again.

You would never hand a new employee your bank login on day one. They watch you work, handle small things, and earn more over time. AI agents skip that stage. Probation builds it.

**Part B: the daily workload is real.** Studies of office work keep finding that a large share of the week goes to handling things that arrive, not to the actual job:
- A McKinsey Global Institute study (2012) found about 28% of a knowledge worker's week goes to email and roughly 19-20% to searching for information, leaving only about 39% for role-specific work. These figures are old and I only saw them through secondary articles, so treat them as indicative.
- Asana's Anatomy of Work Index (a survey of more than 10,000 knowledge workers, first released in 2019, with a 2021 edition) reports that about 60% of time goes to "work about work": searching for information, switching between apps, status updates and meetings. A Verdict article on the survey names six countries (UK, US, Japan, Australia, New Zealand, Germany) and says "more than 60%". These are vendor survey figures (Asana sells work-management software), so treat them as indicative.

Mail is only one of those streams. Files pile up in Downloads, invites arrive, notifications stack up, and every one of them needs a small decision. That is the target.

---

## 2. The idea in plain words

Think of a **learner driver**.

- Day one: the learner sits beside the instructor and only watches.
- Then the learner drives with the instructor's foot hovering over a second brake.
- Then the learner passes a test and gets a restricted licence.
- If the learner drives badly later, the licence is suspended.

Probation does this for an AI assistant, **separately for every kind of small task**:

| Level | Name | What the AI may do |
|---|---|---|
| 0 | Watch | Predict silently, and check later if it was right |
| 1 | Suggest | Prepare a draft or suggestion; you press the button |
| 2 | Do with undo | Do it, tell you, and keep an undo button |
| 3 | Do silently | Only for small things that are easy to undo |

It moves up only when the evidence says it has earned it, and it drops down on its own when it starts making mistakes.

**What is new in v2:** the same learner-driver system now handles many *kinds* of work (mail, invites, files, chains of follow-up steps), not just email.

---

## 3. The big picture on one page

```
 YOUR WORK TRACES                THE ENGINE (same for every pack)                  OUTPUT
 ----------------                ---------------------------------                 ------
 Mail            \
 Calendar         \   +--------+   +---------+   +-----------+   +--------+
 Files/Downloads   >--| DOMAIN |-->| REASON  |-->| EXAMINER  |-->| GATE   |--> do / draft / ask
 Developer notifs /   | PACKS  |   | (clues, |   | (counts,  |   | (checks|
 Chains (cross-pack)/ +--------+   |  score) |   |  licences,|   |  licence|
                         ^         +---------+   |  exam)    |   |  & caps)|
                         |                       +-----------+   +--------+
                         +------ what you actually did (the "footprint") ------+
```

- A **domain pack** is a small plug-in that connects the engine to one kind of work.
- The **engine** is identical for all packs: it predicts, records, scores, and decides who may act.
- To add a new kind of work you write a new pack. You do not rebuild the engine.

---

## 4. How can an AI "see" my work? The four windows

The AI cannot see your work by magic. It can only learn from what it has a **window** into. Think of a new assistant: if they sit in the mail room they learn mail; if you work behind a locked door they learn nothing.

| Window | What it shows | Used by Probation? |
|---|---|---|
| **A. App records** (official connections) | What arrived, and what you did with it: mail, calendar, developer notifications | **Yes**, the main window |
| **B. Traces on your own computer** | Where files came from and where you put them | **Yes**, for files |
| **C. Activity log** | Which app or window was in front, and when, stored locally | **Optional**, only as background context |
| **D. Screen and keystroke recording** | Screenshots, clicks and keystrokes | **No. We refuse it.** |

### Window A: app records
Mail and calendar apps already record your actions. A reply sits in your Sent folder, an archived mail loses its Inbox label, and an accepted invite has your response saved on it. GitHub's REST API can list your notifications and mark them read.

### Window B: traces on your computer
When you download a file, the system usually records where it came from:
- Windows saves the source address and referring page in a hidden `Zone.Identifier` stream.
- macOS stores the download address in `kMDItemWhereFroms` plus quarantine information.
- Linux can store it in extended attributes (`user.xdg.origin.url`).
- Browsers such as Chrome and Firefox keep a download history with the address, referrer and time.

Limits (from the sources): Firefox writes nothing for downloads from private windows, and on Windows the origin tag can be lost when a file is *copied* instead of moved. So the system must cope with files that have no origin information.

### Window C: activity log (optional)
ActivityWatch is a free, open-source tracker (MPL-2.0 licence). It keeps data locally, runs a local server at `localhost:5600` with a REST API, and has small "watchers" for the active window title, away-from-keyboard status and browser tabs. It shows *which app and when*, not *what you decided*. We would use it only as context, for example "were you in a meeting window?" to choose when to interrupt you. This is optional.

### Window D: screen and keystroke recording (what we refuse)
This is how enterprise software "sees" employees' work. *Task mining* tools (for example UiPath Task Mining, Celonis Task Mining and Microsoft's Power Automate Process Advisor) run an agent on the desktop and use what it records to find repetitive tasks that can be automated. UiPath's documentation says its tool collects screenshots and logs data on each mouse click and keystroke. Mimica quotes Gartner as defining task mining as inferring information from low-level user-interface event data. (I confirmed the screenshot, click and keystroke detail only for UiPath; check the other vendors before repeating it.)

Why we refuse it:
- Recording screens and keystrokes can capture anything shown or typed, including passwords and private messages. A review of these tools notes that they can capture personal or sensitive data.
- A well-known consumer example shows the risk. Microsoft Recall saves screenshots of your activity every few seconds. After security and privacy criticism, including a public proof-of-concept tool reported to be able to extract Recall's stored data, Microsoft made it opt-in and added Windows Hello and encryption, and delayed the rollout (as reported by Engadget and HotHardware). This is a cautionary example, not a claim about its current state, which may have changed.
- It is much harder to test and to explain.

**Honest note on prior art:** automation that learns repetitive work is not new. Enterprise task mining plus RPA does a version of it for companies. Probation differs in three ways: it is personal, it uses footprints and not screen recording, and it must earn each permission with statistical proof.

---

## 5. The domain packs

### 5.1 The six questions every pack must answer

| # | Question (plain) | Why it matters |
|---|---|---|
| 1 | What shows up that needs a decision? | Defines the "situation" |
| 2 | What facts can we count about it? | The clues |
| 3 | What is the AI allowed to do? | The action list |
| 4 | How is it done safely, and can it be undone? | Sets the level cap |
| 5 | How do we see what you actually did? | The footprint, which becomes the answer key |
| 6 | When is the outcome final? | The outcome window |

If a kind of work cannot answer all six, it does not get a pack.

### 5.2 Packs we build

| Pack | Situation | Allowed actions (highest level allowed) | Footprint | Outcome window |
|---|---|---|---|---|
| **Mail** | A mail from a person arrives | Archive (3), reply (2), trash (2), forward (1), leave | Sent mail in thread, labels | 7 days |
| **Calendar** | An invite arrives | Accept, decline, tentative (2); block own time (3, used by chains) | Your response status | Until the event, or 7 days |
| **Files and downloads** | A new file appears in Downloads or Desktop | Move to a folder (3), leave (rename and hold-instead-of-delete are stretch) | Where the file ends up | 14 days |
| **Chains** | A trigger above happens | The follow-up steps you usually take next, across packs | Whether you did those steps | 24 hours (a setting) |

### 5.3 Dropped stretch pack (replaced by Radar and Reading, see section 22)
**Developer notifications (GitHub).** A new notification arrives. Actions: mark read or done, comment (level 1 only). GitHub's API has no "mark unread", so these actions cannot be undone through the API, so they are capped at level 2 **(check)**. One more catch: the notifications endpoints are documented as classic-token only in several doc versions, while the current page also lists fine-grained tokens with Notifications-read permission, so test which token works **(check)**.

### 5.4 Chains: the "something more"
Real work is rarely one action. A professor's email with a deadline might make you: reply "noted", block time on your calendar, and create a folder for the submission. Chains learn those patterns.

How it works:
1. For each trigger type (for example "mail from a known professor with a deadline"), look at what you did **within 24 hours** in *any* pack.
2. For each follow-up action, compute how often it follows the trigger, how many cases there are, and how much more often than normal.
3. Keep a chain only if there are at least 20 cases, it happens at least 60% of the time, and it is at least 1.5 times more common than chance. (Starting values to tune.)
4. Next time the trigger appears, the system proposes the follow-up steps. **Each step earns its own licence.** So it might block the time by itself (easy to undo), only draft the reply, and just watch the folder step.

**Honest limit:** linking a follow-up to its trigger is hard. We use time proximity plus text similarity (for example the mail subject and the new event title), so the links are noisy. Such outcomes are treated as weak evidence.

### 5.5 Things we deliberately do NOT build
- Screen, click or keystroke recording (section 4).
- WhatsApp or other chat apps without an official personal API.
- Payments and anything irreversible.
- Opening or running downloaded programs. Files with executable extensions (such as .exe, .msi, .bat, .js, .scr) are on a hands-off list: the system never touches them automatically.
- Passwords, sharing documents outward, permanent deletes.

---

## 6. How the data gets in

### 6.1 Two ways in

| Way | What it is | Used for |
|---|---|---|
| **Imported files** | Google Takeout gives mail as `.mbox` and calendar as `.ics`; a folder snapshot gives files and their origin data | The "driving test on your past" and the public demo |
| **Live connection (optional)** | Gmail and Calendar APIs, a folder watcher for files | Our own accounts and the demo video |

### 6.2 Why the public demo does not use live Gmail
- Google apps in "Testing" mode have login tokens that expire after 7 days, and Testing mode allows only 100 test users.
- Gmail permissions are classed as sensitive, and Google's verification process for such scopes can take a long time **(check)**.
- A judge opening the link in November would see a broken connection.

So the **public demo runs on a synthetic (made-up) person**, through the same code path as real data.

### 6.3 The synthetic person
1. Take a persona from NVIDIA's open **Nemotron-Personas-India** dataset (check the licence on the dataset card).
2. Give the persona **hidden habits across all packs**, for example:
   - Mail: replies to professors within 3 hours; archives newsletters; never answers unknown recruiters.
   - Calendar: declines invites before 9 am.
   - Files: anything from the college portal goes to `College/Sem3/<course>`; receipts go to `Money/Receipts`.
   - Chains: a professor's deadline mail is followed by a calendar block and a reply.
3. Have a Nemotron model write about six months of mail and invites, and generate file-arrival events (name, type, origin site), all from short specs.
4. Decide what the persona "did" using the hidden habits, plus 5-10% random noise.
5. Change one habit in month 4 to test change detection.

Because we know the hidden habits, we can check whether the system rediscovered them. **Honest limit:** synthetic data is a stand-in, so we also run a small study with 6-10 classmates who label real situations.

---

## 7. Three walk-throughs (the process, step by step)

### 7.1 A mail
Meena (a synthetic student) gets: *"Submit the lab record by Friday 5 pm."*

1. **Arrives.** The *ingestor* reads it.
2. **Needs a decision?** Yes: a human-written mail that might need a reply.
3. **Clean and hide.** Old quoted mails and the signature are stripped, addresses become placeholders like `<PERSON_1>`, phone and ID-like numbers are masked, and the text is trimmed to about 1,200 tokens.
4. **Count things (plain code).** She has exchanged 15 mails with this sender and replied to 14, usually within 2 hours; the domain is her college; no unsubscribe link; it came on a Tuesday at 10:05 am.
5. **Reader AI fills a small form** (Nemotron Nano):
   ```json
   { "intent": "request", "asks_me_to_do_something": true,
     "has_deadline": true, "deadline_text": "Friday 5 pm",
     "money_involved": false, "urgency": 2, "formality": "formal",
     "asks_for_personal_info": false, "looks_automated": false }
   ```
   It only fills a form. It decides nothing.
6. **Scoring sheet** (section 8): REPLY 91%, LEAVE 5%, ARCHIVE 3%, others 1%.
7. **Sanity checks.** Not unusual compared with the past; the AI's "written by a person" matches the headers.
8. **Gate.** The task type "mail / request / known sender" holds level 1, so: prepare a draft and ask for a tap. (Even at a higher level, 91% is below the 97.5% bar for sending a reply alone.)
9. **Draft.** A bigger Nemotron model (Super) sees three of Meena's earlier replies to professors and writes in her style.
10. **Write it in the notebook before the outcome is known** (so it can't be accused of peeking).
11. **Watch.** She replies 3 hours later; the reply is found in her Sent mail.
12. **Score and learn.** One more agreement: 41 of 42. Safe estimate about 0.89, below the 0.95 needed for level 2. No promotion yet.

### 7.2 A file
`Lab7_Manual.pdf` appears in Downloads, downloaded from the college portal.

1. **Situation detected** by the folder watcher (or by the snapshot in backtest).
2. **Hands-off check.** Not an executable type, so it continues.
3. **Clues (plain code).** Extension `.pdf`; origin site (from the origin tag or download history) is the college portal; the name contains "Lab" and "7"; size and time.
4. **Optional reader step.** Only if needed, Nano gets the file name and a short redacted text snippet and returns the course and document type. File contents are not sent otherwise.
5. **Scoring sheet** over her top 15 folders plus "other": `College/Sem3/Lab` at 97%.
6. **History.** Earlier files from this portal ended in that folder 60 times out of 60. That gives a safe estimate of about 0.952, which clears the 0.95 bar for level 2 on the numbers alone (the exam and the other checks must also pass), but is nowhere near the 148 clean cases needed for level 3.
7. **Gate: level 2.** It moves the file at once, writes the old location in the notebook, and shows an undo button for 7 days.
8. **Outcome.** In the next two weeks the file stays there (agreement) or she moves it elsewhere (a mistake, and the licence is re-checked).

### 7.3 A chain
Prof. Rao's mail (with a deadline) arrives. From six months of history the chain engine knows what usually follows within 24 hours:

| Follow-up | How often | Safe estimate (about) | Result |
|---|---|---|---|
| Reply "noted" | 38 of 40 | 0.85 | Level 1: draft it |
| Block time on calendar | 34 of 40 | 0.73 | Level 1: suggest it |
| Add a to-do item | 31 of 40 | 0.65 | Level 0: only watch |

The system offers one combined suggestion: "Reply (draft ready) and block Thursday 6-8 pm?" One tap approves the pieces it was allowed to suggest. Each time you tap accept or reject on a suggestion, that counts as strong evidence. As it grows, the calendar block may be promoted to level 2 while the reply stays at level 1.

---

## 8. How it learns your habits

### 8.1 Why not just ask the AI "what would Meena do?"
A language model has never met Meena. Asked cold, it would guess from general human behaviour: slow, costly, untestable and unexplainable. Instead, **two kinds of AI each do what they are good at**:
- **Language AI (Nemotron):** reads messy text and fills a tidy form.
- **A tiny statistical model:** learns "which clues lead to which action" from your own history. It trains in under a second and every number can be inspected.

### 8.2 The clues (per pack)
By plain code (counting):
- **Mail:** sender history, reply rate, usual reply time, sender type, unsubscribe header, hour, weekday, thread state.
- **Calendar:** organiser history, duration, start hour, clash with existing events, how often you accept similar invites.
- **Files:** extension, size, origin site, name words, time.
- **Chains:** the trigger type and the clock.

By the reader AI (the small form): type of message or document, whether it asks you to do something, deadline, money, urgency, formality.

### 8.3 The scoring sheet
Imagine a sheet with one column per action and one row per clue. Each clue adds or subtracts points for each action; the action with the most points wins, and points become a percentage chance. The point values are **learned from your history**, and recent behaviour counts more (older examples lose half their weight every 90 days, a starting value to tune). The technical name is *multinomial logistic regression*.

### 8.4 Learning your style
For a draft, the system finds up to three earlier mails of yours in a similar situation, takes the replies you actually wrote, and gives them to the writing AI as examples, plus facts computed by code (your usual greeting, sign-off and length). The similarity search uses a small embedding model that runs on the machine itself, so raw text does not leave for that step.

### 8.5 Discovering habits you can read
Code scans the table of clue versus action for strong patterns, such as "declines invites before 9 am". A pattern is kept only with at least 20 cases, at least 1.5 times more common than chance, and a corrected p-value below 0.01. Super then only words it. Each habit keeps its counts ("declined 31 of 33") and example cases. If you say it is wrong, the system stops showing it (the scoring sheet itself is learned from your history, not from these habits). **Habits are hypotheses with counts, never the AI's opinion.**

### 8.6 Cold start and change
The first 200 situations are watch-only, and we report that. If your life changes, the change detector (section 10.6) lowers permissions.

---

## 9. How it tracks what happened

### 9.1 The notebook
Every prediction and every real outcome goes into an **append-only notebook**: rows are added, never edited. Each row stores a fingerprint (hash) of the row before it, so editing an old row breaks the chain. A prediction row stores model versions, clues, chances, task type, licence level and decision.

### 9.2 The "no peeking" rule
When replaying the past, at time *t* the system may use only what existed at *t*. An outcome counts as known only from the moment it could really have been observed (a reply: when it was sent; a final label such as archived: when the window closed). Anything newer than its window at export time is not used as a label, because "still there" might only mean "not handled yet".

### 9.3 Strong and weak outcomes
- **Strong:** a reply found in the thread, an archive or trash label, an invite status, a file seen in a different folder.
- **Weak:** "left alone", and chain links made by time and similarity. Weak outcomes can support a suggestion (level 1) but never an automatic action (levels 2 and 3).

Limit: a Takeout export shows the *final* state of labels, not when you archived a mail. Reply times and file times are better.

---

## 10. How it earns trust

### 10.1 The driving test on your own past
Before touching anything, the system replays your history in order, one situation at a time, predicting from only what it could have known then and comparing with what you really did. The result is a **report card**:

> Out of 500 situations: same as you 412 times, different 38 times, would have asked 50 times.

You click nothing. Your behaviour is the answer key.

### 10.2 What a licence is
A licence belongs to a pair: **(task type, action)**. Example: (files from the college portal, MOVE to `College/Sem3/Lab`). The question is: *when the system proposes this action for this task type, how often would you have done it yourself?*

### 10.3 How many right answers are needed
After 58 right out of 58, we can be 95% sure the true success rate is at least 95%. For at least 98% it needs about 148 in a row. Each mistake raises the number needed. (This is a standard Beta statistical model with a flat starting assumption.)

Small task types may borrow a little evidence from their bigger parent group, but they need at least 40 recent decisions of their own, so borrowing alone can never grant a licence.

In practice, only frequent task types (newsletters, receipts, recurring downloads, recurring invites) have enough examples to earn licences within six months of history. That is fine, because those are the boring tasks worth handing over. How quickly this happens is an aim to be measured, not a result.

### 10.4 The levels and caps
Caps come from what can be undone, **not** from how good the record is.

| Level | Meaning |
|---|---|
| 0 | Watch |
| 1 | Suggest (needs at least 20 decisions and a safe estimate of at least 0.70; starting values) |
| 2 | Do with undo (safe estimate at least **0.95**) |
| 3 | Do silently (safe estimate at least **0.98**, reversible actions only) |

For things that cannot be called back once sent (replies, RSVPs), level 2 means the action waits **10 minutes** first. For things that can be reversed (moving a file), it acts at once and keeps an undo button.

### 10.5 When it asks you anyway
The system acts alone only if **all** are true:
1. The task type holds the needed licence.
2. The chance for this particular item is high enough.
3. The item is not unusual compared with the past.
4. The action is within its cap and not on the hands-off list.
5. The reader AI worked properly this time (otherwise it asks).

The "high enough" bar uses a simple rule: act only if *(chance of being wrong) x (cost of a mistake) < (cost of interrupting you)*. Starting values (kept in the settings file, not hard-coded in the logic): interrupting = 1; archive = 5, move file = 5, block time = 3, trash = 20, accept = 10, decline = 20, reply = 40. That gives bars of roughly 80% (archive, move), 67% (block time), 90% (accept), 95% (trash, decline) and 97.5% (reply).

Questions are grouped into a short digest ("7 recruiter mails: polite no for 5, need you for 2") instead of one pop-up at a time.

### 10.6 Losing a licence
A licence is a **check on current evidence run every time**, not a switch someone flips. It disappears when:
- The safe estimate drops below the bar.
- A running tally of recent mistakes crosses an alarm line (called CUSUM; starting values allowance 0.02, alarm at 5). Every undo or override by you counts as a mistake here, and two of them within 30 days trigger the alarm at once.
- The kinds of items you receive change sharply (rule of thumb: a population-shift score above 0.25).
- 30 days pass without at least 20 fresh decisions.

The task type is then held at suggest-only (level 1) until it passes the exam again.

### 10.7 Keeping the evidence honest (the audit sample)
Once the system acts on its own for a task type, you stop doing that task yourself, so nobody is checking it any more. To keep honest evidence coming, a random 10% of the things it would have done alone are turned into suggestions instead. Your answer (or what you do) then tells us, without bias, whether it is still right. This costs a little autonomy, and we report that cost. Silence after an automatic action is **not** counted as agreement; only undos and overrides are counted, and only as mistakes.

---

## 11. The trick-question exam

Doing well on easy, typical items proves little. The exam checks that the system notices what *should* change its answer.

For each task type wanting a licence, take up to 30 real examples. A strong model writes edited versions. Plain code checks that each edit really happened, and invalid edits are discarded. The **whole pipeline** then runs on each edited version.

**Edits that should change nothing** (rephrase, greeting, typo, harmless footer): the decision must stay the same, with at most 3% flips.

**Edits that should make it more careful** (the system must never become *more* willing to act alone):

| Pack | Example edits |
|---|---|
| Mail | Unknown sender, money request, tight deadline, link added, "ignore previous instructions" |
| Calendar | Unknown organiser, clash with an existing event, unusual hour |
| Files | Unknown origin site, double extension (for example `report.pdf.exe`), a misleading name |

Pass marks: **zero** violations for money and unknown-source edits, at most 5% for the others. The AI writes the questions. Plain code gives the verdict. An AI never marks its own exam.

---

## 12. The workers and how they talk

| Worker | Job | Holds your keys? | Internet access |
|---|---|---|---|
| **Pack adapters** (postmen) | The ingestor reads new items; the resolver watches for what you actually did | Read-only | Only to that source |
| **Brain** | Clean text, run the reader AI, predict, write drafts | **No** | Only to the AI service |
| **Examiner** | Count agreements, compute licences, spot change, run exams | No | Only to the AI service |
| **Executor** (cashier with the keys) | Does the actions, keeps the hold-and-undo queue | **Yes** (the only one) | Only to the target apps |
| **Web facts** (`webfacts`) | Looks up public facts about unfamiliar organisations and reads pages the user saved, through Tavily; can only make the system more careful (section 22) | No | Only Tavily and the language service |
| **Dashboard** | Report card, questions, undo buttons | No | No |

**Key safety rule:** the AI models only produce data (a form, a draft, a list of edits). They never hold keys and never run commands. Only the Executor acts, and only from a fixed list of allowed action types, after checking the licence.

**How they talk:** through one shared notebook (a SQLite database file on the same machine), like a kitchen order board. No message broker is needed at our scale. If sharing the file between containers causes trouble, the fallback is one Postgres container.

**The locked room:** NVIDIA's *OpenShell* can run a program in a sandbox with a policy listing the internet addresses it may use. The Brain and Examiner would run there with permission to reach only the AI service. The exact policy syntax, and whether it runs well on a Nebius virtual machine, must be tested on day 1 **(check)**.

**If something fails:** each step can be repeated safely. If the AI service is down or returns bad output, the system **asks you**. It never acts when unsure.

**Always on:** continuous reading of new items; outcome checks every 15 minutes; a nightly job at 02:00 IST (retrain, find habits and chains, check for change, review licences). An exam runs when a task type first meets the numbers for level 2 or 3, after an alarm makes the old one stale, and when a passing exam is older than 90 days.

---

## 13. Models, where they run, and what it costs

### 13.0 Who is who (read this first)

| Name | What it is | Our use |
|---|---|---|
| **Nemotron** | A family of AI language models made by **NVIDIA** (open weights). Sizes: Nano, Super, Ultra. | **These are the models we use.** The hackathon requires at least one NVIDIA open model. |
| **Nebius** | A **cloud company** that rents out computing. It is not a model. | Where everything runs. |
| **Nebius Token Factory** | Nebius's service that **hosts AI models and lets you call them over the internet** (an API), paying per token. It hosts models from many makers, not only NVIDIA. | We send our Nemotron calls here. We do not run the models ourselves. |
| **Nebius AI Cloud** | Nebius's service for renting virtual machines and GPUs. | One small virtual machine runs **our own code** (the workers, the database, the scoring sheet). |

In one line: **our code runs on a Nebius virtual machine, and it asks Nemotron models (hosted by Nebius Token Factory) to read text and write drafts.**

```
 Our code (Nebius AI Cloud VM)  --->  Nebius Token Factory  --->  Nemotron Nano / Super / Ultra
 (workers, database, scoring)         (hosts the models)          (NVIDIA's models)
```

### 13.1 Decision
All model calls, **including prototyping**, go to the Nemotron models hosted on **Nebius Token Factory**. No OpenRouter and no free-tier endpoints. Reasons: the hackathon requires the project to run on Nebius, free endpoints may log prompts, and request caps would make the evaluation impractical. Token Factory's API is OpenAI-compatible with the base URL `https://api.tokenfactory.nebius.com/v1` (confirm in the docs), so keep the address and model name in a settings file.

### 13.2 Jobs, models and prices (what Nebius charges to run each Nemotron model, per 1 million tokens, input / output; seen 2 Oct 2026)

| Job | Model (all Nemotron unless stated) | Nebius price | Notes |
|---|---|---|---|
| Fill the small form for every item (high volume) | Nemotron 3 Nano 30B-A3B | $0.06 / $0.24 | 262K context |
| Drafts, habit and chain wording | Nemotron 3 Super 120B-A12B | $0.30 / $0.90 | Price from Artificial Analysis for Nebius; confirm a per-token endpoint **(check)** |
| Exam edits for the final demo runs, offline analysis | Nemotron 3 Ultra 550B-A55B | $1.00 / $3.00 | 1,024K context; other exam edits use Nano or Super to save cost |
| Find similar items | Small embedding model **on the machine** | $0 | Raw text stays local |
| Scoring sheet, statistics, licences | Plain Python on the machine | $0 | |

Nebius also suggests Nemotron 3.5 Lightning as a current default; test it as a swap for Nano or Super **(check; price and limits not verified)**.

### 13.3 Speed limits
Nebius says rate limits are dynamic and per account, with limits reported in response headers. Its Starter plan baseline is listed as 400K tokens per minute and 600 requests per minute **(check your account)**. At about 780 tokens per call that is roughly 500 calls per minute, so a 60,000-call evaluation takes about 2 hours **(assumption)**. Build retries that honour the headers.

### 13.4 Prototyping cheaply on real credits
- Iterate prompts on a **dev set of about 300 situations**, with answers saved by content fingerprint, so re-running the scoring or gate costs nothing.
- Use Nano or Super (not Ultra) to write exam edits while developing and in the main evaluation; Ultra only for the final demo-persona runs.
- Run the full 60,000-situation evaluation only twice (later runs reuse saved answers).
- Put a **hard spending limit** in the code, and check your actual credit amount on the Devpost resources page.

### 13.5 Rough budget (assumptions marked; same table as `EVALUATION_PLAN.md` section 9)
| Item | Cost |
|---|---|
| Development iterations (dev set, saved answers) | about $2.5 |
| Synthetic body pool | about $1.0 |
| Main evaluation run 1, 60,000 items (reader about $3.7, exams about $4.5) | about $8.2 |
| Main evaluation re-run (mostly saved answers) | about $2.0 |
| Baseline B3 (2 personas, Super) | about $2.9 |
| Drafts (about 1,000, about $0.0007 each) | about $0.7 |
| Habit and chain wording | about $0.5 |
| Exam, development runs | about $0.6 |
| Exam, final demo-persona runs (Ultra edits) | about $0.5 |
| **Total** | **about $19; with a 30% buffer about $25** |

The reader costs about $0.00006 per item (about 700 tokens in and 80 out, an **assumption**). The exam number rests on assumptions explained in `EVALUATION_PLAN.md` section 9.

If your credits are smaller, shrink the evaluation to 10 synthetic users (see `EVALUATION_PLAN.md` section 9).

---

## 14. How big is this? (scale for the hackathon)

- **Users:** one demo person, about 10 testers, and judges clicking around for a few minutes; at most about 10 at once.
- **Data:** about 3,000 situations per synthetic user over six months across all packs. Embeddings for 10,000 items take about 15 MB, so simple in-memory search is enough.
- **So:** one small virtual machine on Nebius AI Cloud, one SQLite file per user, no message broker, no Kubernetes of our own.
- **The public demo** replays a fixed synthetic person on a speed-up clock with saved AI answers, so it works even if the AI service is slow. Any "try your own item" box is rate-limited and has a spending kill-switch.

---

## 15. How we measure success

| Measure | Plain meaning |
|---|---|
| Agreement | How often its prediction equals what you did |
| Precision per licence | When it says "do X", how often you would have done X |
| Coverage | What share of your decisions it could take over |
| Interruptions per 100 | How often it has to ask you |
| Harmful mistakes | Costly wrong actions, weighted by how bad each is |
| Calibration | When it says 90%, is it right about 90% of the time? |
| Days to first licence | How quickly it earns trust |
| Change detection | How many items until it notices your habit changed, and false alarms |
| Exam results | Flip rate and "less careful" violations |
| Chain quality | Of the chains it proposes, how many you follow |
| Pack effort | How long it takes to add a new pack (target 2 days or less **(assumption)**) |
| Cost and speed | Dollars per 1,000 items; median and slowest time per item **(to be measured)** |
| Exposure | Amount of your text sent to the AI service per item |

**Compared against:** (a) ask for everything, (b) one generic rule for everyone, (c) act when the AI says it is confident. Aim: **fewer interruptions at the same low rate of harmful mistakes**. Treat any number as an aim until measured.

---

## 16. What can go wrong

| Risk | In plain words | Defence |
|---|---|---|
| Trick content | A mail or file name tries to fool the reader AI | The reader only fills a form and has no tools; answers are cross-checked against plain facts; the exam includes such edits; executables are on the hands-off list |
| Noisy labels | You handled something by phone, so it looks ignored | "Left alone" and chain links are weak: they can support suggestions but never automatic actions |
| Too little data | A rare task type | Borrow a little from the parent, but require a minimum of its own |
| Habits change | New semester, new job | Change detection, automatic demotion to suggest-only, re-exam |
| AI service slow or down | Rate limits, outages | Retry with waiting; if it still fails, ask |
| Different answers each time | AI output varies | Answers saved by fingerprint; model names pinned |
| Money runaway | A loop makes too many calls | Hard spending limit and kill-switch |
| Privacy | Your text goes to a cloud AI | Cleaning and hiding names first, local embeddings, sending as little as possible, logging how much is sent. I could not verify Nebius's data-retention terms; read them before using any real data **(check)** |
| Scope too wide | Four packs plus chains is a lot | Strict order and cut list (section 18) |
| Over-claiming | Saying "guaranteed safe" | The maths assumes the future resembles the past. Say "evidence", never "guarantee" |

---

## 17. What a pitch should say honestly

- "One engine that safely hands over **any repeated decision that leaves a footprint**, proven on mail, calendar, files and cross-tool chains."
- Not: "it automates everything you do on a computer". It cannot, and it deliberately avoids screen and keystroke recording.
- Acknowledge prior art: enterprise task mining and RPA, and research on "ask when unsure". Our difference is the personal, footprint-based, earn-your-licence design.

---

## 18. Build plan (summary)

The authoritative, phase-by-phase plan is `IMPLEMENTATION_PLAN.md` (13 phases, Day 1 = 3 Oct 2026, target submission 29 Oct 2026). In short:

- **Early (3-11 Oct):** foundations and spikes; database, ledger, language-model client and redaction; synthetic person and importers; mail and calendar packs.
- **Middle (10-23 Oct):** engine core and replay; licences, gate, executor and change detection; files pack; exam board; chains and habits. The dashboard is built in parallel.
- **Late (22-29 Oct):** evaluation, deployment on Nebius, polish, video, submission.

**Cut in this order if behind:** the Reading Triage pack, then the extra sandbox lock, then the human study, then simpler dashboard pages. Do **not** cut the files pack, the exam, or the core chain demo (reply plus block time), because those are what make it more than an email tool.

**The demo, in five beats:**
1. "Before it touches anything, here is what it would have done with your last six months."
2. A day in the life: a newsletter archived, a college file moved to the right folder, a declined early invite, a recruiter mail answered with a polite no (draft), and a professor's deadline mail producing a combined suggestion.
3. Three task types earn licences.
4. The exam catches a model that was only passing on a keyword shortcut.
5. The persona's habit changes, and the system demotes itself.

---

## 19. Things to verify on day 1

The authoritative checklist, with how to verify each item, is `DECISIONS_AND_OPEN_QUESTIONS.md` section 3. In short:

1. Exact model name strings on Token Factory, and which Nemotron models support strict JSON-schema output (fallback: ask for JSON and check it ourselves).
2. Your account's rate limits and the credit amount.
3. Nebius's data-retention terms.
4. OpenShell policy syntax, and whether it runs on a Nebius virtual machine.
5. Whether Super is on a per-token endpoint.
6. Nemotron 3.5 Lightning's price and limits.
7. The licence of the Nemotron-Personas-India dataset.
8. That your own Takeout export contains the label data (`X-Gmail-Labels`).
9. (Dropped with the GitHub pack.)
10. That your own files carry origin tags on your operating system.

---

## 20. Sources checked (2 Oct 2026)

**How systems "see" work**
- Celonis, what is task mining: https://www.celonis.com/insights/topics/what-is-task-mining
- UiPath docs, Task Mining FAQ: https://docs.uipath.com/task-mining/automation-cloud/latest/user-guide/faq
- UiPath docs, starting Task Mining from Process Mining (screenshots and logs per click and keystroke): https://docs.uipath.com/process-mining/automation-cloud/latest/user-guide/starting-a-task-mining-project-from-process-mining
- Mimica, what is task mining (quotes the Gartner definition): https://www.mimica.ai/articles/what-is-task-mining
- Process Excellence Network, task mining tools: https://www.processexcellencenetwork.com/process-mining/articles/top-9-task-mining-tools-for-achieving-process-excellence
- Microsoft Recall changes: https://www.engadget.com/microsoft-moves-to-resolve-privacy-concerns-over-its-recall-feature-170318905.html and https://hothardware.com/news/microsoft-flips-off-ai-recall-privacy-backlash
- ActivityWatch: https://github.com/odoo/activitywatch (mirror of the project) and https://activitywatch.net/blog/
- Firefox download origin metadata: https://firefox-source-docs.mozilla.org/toolkit/components/downloads/index.html
- Zone.Identifier details and caveats: https://kb.binalyze.com/air/features/acquisition/acquisition-profiles/windows-collections/downloads
- File origin traces across browsers and OSes (filegrail): https://pypi.org/project/filegrail/0.8.1/
- GitHub notifications REST API: https://docs.github.com/rest/activity/notifications

**Workload statistics**
- McKinsey 2012 figures via City A.M.: https://www.cityam.com/workers-should-not-be-spending-650-hours-year-email/
- Asana Anatomy of Work Index (Asana's own page, 2021 edition): https://asana.com/resources/anatomy-of-work-index
- Asana survey as described by Verdict: https://www.verdict.co.uk/?p=196906
- McKinsey figures also reported by Slate.fr: https://www.slate.fr/lien/60007/employes-bureau-650-heures-mail

**Models, prices, limits, login tokens**
- Nebius Nemotron page (Nano and Ultra prices, context): https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference
- Artificial Analysis, Super on Nebius: https://artificialanalysis.ai/models/nvidia-nemotron-3-super-120b-a12b/providers
- Nebius rate limits doc: https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits
- Nebius plan baselines: https://nebius.com/services/token-factory/enterprise-grade-inference
- Gmail OAuth Testing mode (7-day tokens, 100 test users): https://nango.dev/docs/api-integrations/google/how-to-register-your-own-google-oauth-app

---

## 21. Glossary

- **Agreement:** the system's prediction equals what you actually did.
- **Append-only notebook (ledger):** a table where rows are only added, each linked to the previous one by a fingerprint.
- **Calibration:** whether stated percentages match reality.
- **Chain:** a follow-up step (in any pack) that you reliably take after a trigger.
- **CUSUM:** a running tally that rises with unexpected mistakes and sets off an alarm when it crosses a line.
- **Domain pack:** a plug-in that connects the engine to one kind of work.
- **Embedding:** turning text into numbers so similar texts get similar numbers.
- **Executor:** the only worker holding keys; it performs actions.
- **Footprint:** the trace your action leaves in an app or on your computer.
- **Hash:** a short fingerprint of data; change the data and the fingerprint changes.
- **Licence:** permission for one (task type, action) pair, computed from current evidence.
- **Safe estimate (lower bound):** a pessimistic but reasonable guess of the true success rate, given the evidence so far.
- **Multinomial logistic regression:** the "scoring sheet" model.
- **Nebius:** a cloud company that rents computing. It is not an AI model.
- **Nebius AI Cloud:** Nebius's service for renting virtual machines and GPUs. Our own code runs on a small virtual machine here.
- **Nebius Token Factory:** Nebius's service that hosts AI models behind an API, billed per token. We call Nemotron models through it.
- **Nemotron:** NVIDIA's family of open AI language models (Nano, Super, Ultra). These are the models we use.
- **No peeking (walk-forward):** only using information that existed at the time of each decision.
- **OpenShell:** NVIDIA's tool for running programs in a sandbox with an allow-list of internet addresses.
- **Precision:** of the times the system said "do X", the share where you would have done X.
- **Task mining:** enterprise software that records screens, clicks and keystrokes to find repetitive tasks.
- **Task type (class):** a group of similar situations, for example "files from the college portal".
- **Token:** a piece of text (roughly three-quarters of a word) used to measure and charge AI use.

---

## 22. Addendum (4 Oct 2026): web grounding and two more packs

The specs now add three things; read `TAVILY_AND_NEW_PACKS.md` for the full design.

- **Tavily as an Entity Facts Service.** For unfamiliar organisations and unfamiliar links, the system searches the web for public facts (is there an official site, does this domain copy it, do results mention it with words like "scam"). The result can only make the system **more careful** or give you **evidence next to a question**. It can never give the system more freedom: "the web can warn you; only your history can trust." A separate worker (`webfacts`) does this; the brain never calls Tavily.
- **Never follow the link in the email.** For opportunity mails, the system finds the official page itself and compares it with the email's link.
- **Untrusted web text.** Page text is read only by a small quarantined AI step that outputs a fixed form; code checks every field; the writing model never sees page text.
- **Opportunity Radar** (hackathons, internships, scholarships): verifies, extracts the deadline, eligibility and any fee, and tracks the opportunity; it never applies or pays and refuses autonomy when money is asked.
- **Reading Triage:** files saved links into your collections the way you do, once it has earned permission.

The workers table in section 12 gains a sixth worker, `webfacts` (network: Tavily and the language service only; no mailbox keys). The GitHub stretch pack is dropped.
