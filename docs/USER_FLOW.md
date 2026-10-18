# USER_FLOW

What the user sees and does, screen by screen, and what the system does behind each step. Authority: below `CONTRACT.md` (the API in CONTRACT section 9 is the only source of data for the dashboard).

Used by: the dashboard builder (Phase 9), the demo script (`DEMO_AND_SUBMISSION.md`), and anyone checking that the product makes sense to a non-technical person.

---

## 1. Principles

1. **Plain words.** The first screen never says "licence", "class" or "gate". See the word list in section 2.
2. **Evidence beside every permission.** Anywhere the system acts alone, the user can see why in one line and open the details.
3. **Undo is always one tap away** for anything the system did.
4. **The user is never surprised.** Nothing leaves the machine (a sent reply, a declined invite) without a visible hold or an explicit approval.
5. **When unsure, the system asks.** Asking is a normal, friendly state, not an error.
6. **Honest numbers.** Show counts and the pessimistic estimate; never use the words "guaranteed" or "safe".
7. **Works on a phone.** Single column, large tap targets.

---

## 2. Words the user sees

| Engine term | What the screen says |
|---|---|
| Level 0 (watch) | **Watching** |
| Level 1 (suggest) | **Suggests** |
| Level 2 (do with undo) | **Does it, with undo** |
| Level 3 (do silently) | **Does it quietly** |
| Licence / permission | **Permission** |
| Class / task type | **Kind of task** |
| Gate `ASK` | **Needs you** |
| Gate `SUGGEST` | **Ready for you** |
| Gate `HOLD_THEN_EXECUTE` | **Will do it in 10 minutes** (cancel any time before) |
| Gate `EXECUTE_UNDO`, `EXECUTE_SILENT` | **Done** |
| Audit holdout | **Spot check** ("I would have done this myself; checking that you agree") |
| Exam | **Trick-question test** |
| Drift or family-shift alarm | **Your habits changed** |
| Lower bound | **Safe estimate** |
| Ledger | **Activity record** (with a "verified" badge) |
| `ABSTAIN` | **Not enough history yet** |
| Entity status `confirmed_official` | **Matches the official site** (with sources) |
| Entity status `lookalike` | **Looks like a copy of {official domain}** (with sources) |
| Entity status `reports_found` | **Some web results mention this domain with words like "scam" or "fake"** (with sources) |
| Entity status `no_web_presence` | **I couldn't find this organisation online** |
| Entity status `unverified` / `not_checked` | **Not checked** |
| Radar `TRACK` | **Add to my opportunities** |

---

## 3. Journeys

Each journey lists what the user does, what the system does, the screens, and the API calls (CONTRACT section 9).

### F1. First run

**Two entry modes**
- **Demo mode** (default; used by judges): the user sees a pre-loaded synthetic person, Meena. No sign-in.
- **My own data** (v1: instructions only): a short page explains how to export mail, calendar and a folder snapshot and import them with the command line (`probation import ...`). The dashboard has no upload button in v1.

**Steps**
1. The user opens the app. **Home** shows a one-sentence explanation, a "Start the driving test" button (demo mode: "Watch the last six months replay") and the current mode.
2. Replay controls (play, pause, speed) are visible. `GET /replay/state`, `POST /replay/start`.
3. While the replay runs, a progress strip shows the simulated date and counters (items seen, suggestions, automatic actions).
4. When the replay reaches the end of the history window, the **Report card** opens (F2).

**Edge cases**
- Engine not reachable: full-width banner "Can't reach the engine. Showing the last saved view." with a retry button.
- No data imported (own-data mode): the Home screen shows the import instructions and nothing else.

### F2. The driving test (report card)

**Goal:** show what the system would have done with the user's past, before it touches anything, with results scoped to the kind of task and action being judged.

**What the user sees**
- A task/action selector or task-specific list (for example, recruiter messages → draft a decline, or meeting invitations → accept). Never show one combined trust or accuracy score.
- For the selected task/action, show **Same as you**, **Different**, **Would have asked**, and **No answer yet** as counts. If a percentage is shown, calculate agreement as `same / (same + different)` and show the counts, time range, and censored count beside it.
- A family summary (Mail, Invites, Files) may remain as optional context, clearly labeled as a family total. Never repeat its score as if it belonged to each task/action.
- Tapping "Different" lists those items with what the system predicted and what the user actually did.
- A footnote: "Based only on what was known at the time. Recent items have no answer yet."

**Current API and required change:** `GET /report-card?family=email_action` (repeat for `invite_rsvp`, `file_destination`) returns family-scoped results. The user-requested task/action score needs an approved Contract Change Request to expose matching historical counts at the task/action grain. Until that is approved and implemented, label the family results accurately and say the task-specific backtest score is not available; do not infer it from `/licences` or `/exams`.
**Edge cases:** a task/action with too little history shows "Not enough history yet to guess", not a zero. Outcomes that are missing, weak, or not yet known are listed as censored/unresolved and excluded from the agreement denominator, per `ENGINE_SPEC.md` section 17.

### F3. Daily use: the queue

**Goal:** the user answers a short list, once or twice a day.

**What the user sees (Queue page)**
- Items grouped into a **digest** by kind of task and proposed action. Example: "7 recruiter mails: I'd send a polite no to 5. Needs you: 2."
- Two sections: **Needs you** (`ASK`) and **Ready for you** (`SUGGEST`).
- Each item shows a one-line summary, the proposed action, and three buttons: **Do it**, **Not this**, **Change**.
- A **Spot check** tag on items that are audit holdouts, with a one-line explanation.
- Tapping an item opens **Item detail** (F4a).

**What happens when the user responds**
1. **Do it** -> `POST /queue/{proposal_id}/respond {response: "accept"}`. The api writes a `user_responses` row. The Executor then performs the action **immediately** (no hold; the user approved it). A STRONG agreement outcome is recorded.
2. **Not this** -> `{response: "reject"}`. Nothing is done. A STRONG disagreement outcome is recorded.
3. **Change** -> the user picks a different action (for example "Archive" instead of "Reply") -> `{response: "edit", edited_action: "ARCHIVE"}`. The Executor performs the edited action; the outcome records the edited action.
4. The item leaves the queue; an "Undo" link appears for the action (F5).

**Batch answers**
- "Do all 5" sends 5 separate `respond` requests. There is no batch endpoint in v1. If this is too slow in practice, raise a contract change request.

**Edge cases**
- Two answers to the same item (double tap, or two tabs): the first wins; the second shows "Already answered".
- The user ignores the queue: items stay; after the outcome window closes (7 days for mail), the item is resolved from what the user did elsewhere (replied in their mail app, etc.). Resolved items disappear from the queue with the note "You handled this yourself."
- Reply drafts that need the user's input ("needs_user_input") show a banner "I need a detail from you before this can go" and never auto-send.

### F4a. Item detail: "why?"

**What the user sees (`GET /items/{proposal_id}`)**
- The item (redacted summary, never more than what the user would see anyway), the proposed action and the system's chance.
- **Why:** the top three clues (for example "You usually reply to this sender: 14 of 15 times").
- **Similar before:** the three most similar past items and what the user did with each.
- **Permission for this kind of task:** the evidence line (F6) and the current level.
- For replies: the draft, editable, with the note "Written in your style from 3 of your earlier replies."
- Buttons as in F3.

### F4b. Automatic actions

| Level | What the user experiences |
|---|---|
| **Suggests** (1) | Item in **Ready for you**; nothing happens until the user taps |
| **Does it, with undo** (2), reversible action (archive, move a file, create a private block) | The action is done; it appears in **Actions** with an **Undo** button for 7 days |
| **Does it, with undo** (2), action that cannot be recalled (reply, RSVP) | Appears in **Actions** as "Will do it in 10 minutes" with a **Cancel** button; after 10 minutes it is sent |
| **Does it quietly** (3) | Done without a notification; listed in **Actions** with an Undo button; counted in the weekly summary |

**API:** `GET /actions`; undo or cancel: `POST /actions/{id}/undo`.
**What happens on undo:** the api writes an undo request; the Executor reverses the action (or cancels it if held) and records a strong disagreement outcome. The row shows "Undoing..." until `GET /actions` reports `UNDONE` or `CANCELLED`.
**Edge cases**
- Undo of a file move when the original place is occupied: the action shows "Couldn't undo: a file with that name is already there" and offers nothing destructive.
- Undo after 7 days: the Undo button is gone; the row says "Undo period ended."
- Two undos for the same `(kind of task, action)` within 30 days automatically lower the permission (F7); the user sees a short message.

### F5. A permission is earned

**Trigger:** the nightly review finds a kind of task that meets the numbers and passes the trick-question test.

**What the user sees**
- An in-app card on Home: "New permission: archive newsletters from automated senders. It matched you 148 of 148 times (safe estimate 98%) and passed the trick-question test."
- Buttons: **Looks good** (dismiss) and **See evidence** (opens the Licences page at that row). There is no "approve": the permission is derived from evidence, not granted by a click. The user can still **turn it off** by answering "Not this" to its actions or undoing them (F7).

**API:** `GET /licences` (current level, evidence, last 5 changes).

### F6. Reading a permission (Licences page)

**What the user sees**
- Rows grouped by pack. Each row: kind of task, action, a four-step ladder (Watching, Suggests, Does it with undo, Does it quietly) with the current step highlighted, and the **evidence line**.
- **Evidence line pattern:** "Matched you {k} of {n} times (safe estimate {lb}%). Test: {passed on DATE / not yet}. Last 30 days: {n_recent} checks."
- A reason when the level is capped, for example "Never fully automatic: this kind of action goes out to other people."
- A reason when held back, for example "Waiting for the trick-question test" or "Your habits changed on {date}; re-testing."

**Edge cases:** no rows yet shows "Nothing has earned a permission yet. It needs enough examples of the same kind of task."

### F7. Habits change; permission is lowered

**Trigger:** a drift alarm (mistakes piling up, or two undos in 30 days) or a family-shift alarm.

**What the user sees**
- A card on Home: "Your habits changed: you used to decline early invites and now you accept more of them. Automatic replies to invites are paused (back to suggestions) until a new test passes."
- **Licences** shows the affected rows at **Suggests** with the reason and the alarm date.
- **Metrics** shows the alarm on the timeline.
- After a new exam passes and the numbers still hold, the level rises again (F5 card).

**What happens behind the scenes:** `last_alarm_at` is set; level 2 and 3 need a new exam finished after the alarm (ENGINE_SPEC section 6.3); the effective level is at most 1 meanwhile.

### F8. Habits and chains

**Habits page (`GET /habits`)**
- Plain sentences with counts: "You declined 31 of 33 invites that start before 9 am." Each shows up to 5 example items.
- **That's not right** -> `POST /habits/{id}/deny`. The habit stops being shown. (The scoring model learns from your history, not from these sentences, so denying a habit does not change what it predicts; the page says this.)

**Chains page (`GET /chains`)**
- "After a mail from a known professor with a deadline, within 24 hours you usually: reply (38 of 40), block time (34 of 40)."
- Each step shows its own permission level. Chains appear in the queue as one combined suggestion; each step is accepted or rejected separately.

### F9. Trust and privacy views

- **Exposure (`GET /exposure`):** how much text left the machine: items sent to the language service, tokens per item, share handled with no call, with a plain explanation of what is hidden first (names, numbers, links).
- **Activity record (`GET /ledger/verify`):** a badge "Verified: N records, nothing altered" with the head fingerprint; if broken, "Record altered at entry {seq}" in a clear warning style.
- **Exams (`GET /exams`):** each test with its result and the edited items that flipped (before and after), so the user can see what trick questions were asked.
- **Settings (`GET /settings`, read-only in v1):** the current thresholds, which actions can never be fully automatic, the hands-off list (for example "programs and scripts are never touched"), and the spending limit.

### F10. When something fails

| Situation | What the user sees | What the system does |
|---|---|---|
| Language service slow or down | Banner: "The reading service is slow. New items will wait in Needs you." | Fail closed: items become `ASK` (CONTRACT I-3) |
| Spending limit reached | Banner: "Spending limit reached. Nothing will act on its own until it is raised." | `BudgetExceeded`; fall back to `ASK` and `SHADOW` |
| Engine not reachable | Banner with retry; last saved data stays visible and is marked "as of {time}" | |
| An action fails (for example the target app refused) | The row in Actions shows "Couldn't do this" with a Retry or "Do it myself" | Status `FAILED`; no automatic retry loop |
| A suggestion was already handled elsewhere | Item shows "You already handled this" | Resolved from outcome |

### F11. Replay controls (demo)

- A persistent control bar: **Play / Pause**, speed (1x, 10x, 100x), and the simulated date. `POST /replay/start`, `/pause`, `/speed`; `GET /replay/state`.
- At high speed the dashboard refreshes counters rather than animating every item.
- There is no "jump to date" in v1 (no endpoint). Pre-run the demo database to a chosen date instead.

### F12. Check the sender (web evidence)

**Trigger:** an item from an unfamiliar organisation, or with a link to an unfamiliar domain, whose web status is a restriction (`lookalike`, `reports_found`, `no_web_presence`).

**What the user sees (Item detail, `GET /items/{id}`)**
- A banner "Check the sender" with one plain sentence from the table in section 2 and up to 3 **sources** (title and link, shown as plain text).
- The item is in **Ready for you**, never done automatically, even if the kind of task has permission. A line explains: "I never act on my own when I can't confirm who it's from."
- If the status is `confirmed_official` the item gets a small "Matches the official site" line with sources. It changes nothing about what I may do.

**Rules for the copy:** say "I found...", never "this is a scam"; always show the sources; never show web text as if it were the user's own mail.

**Privacy view:** `GET /web-facts` lists every web search made, with the exact query text, so the user can see that only public names and domains were sent.

**Edge cases:** web service unavailable -> "Not checked"; behaviour is unchanged from normal (nothing becomes less safe).

### F13. Opportunity Radar

1. A mail about a hackathon, internship or scholarship arrives. The system finds the **official page itself** (it does not open the email's link), compares the two, reads the page, and shows a card on the **Radar board**: title, organiser, deadline (with "mail says / official page says" if they differ), eligibility lines, a fee warning if payment is asked, and **sources**.
2. If money or personal documents are requested, or the sender can't be confirmed, the card is **Ready for you** with a red note and no automatic action.
3. **Add to my opportunities** tracks it (undo available; a deadline reminder may be suggested as a follow-up step). **Not interested** dismisses it (undo available).
4. A **weekly digest** (text written only from the card fields, each line with its source number) appears on Home.

**API:** `GET /boards/radar`, `GET /queue`, `POST /queue/{id}/respond`, `GET /items/{id}`.

### F14. Reading Triage

1. The user saves links to the Reading inbox. Each link is read (only links the user saved), given a topic and a type, and offered a collection.
2. With enough history the system files links itself ("Does it, with undo"). Archive is never fully automatic.
3. Links with private tokens, login or payment pages are left alone ("I never open private or sensitive links").

**API:** `GET /boards/reading`, `GET /queue`, `POST /queue/{id}/respond`, `GET /actions`.

---

## 4. Screen inventory

| Screen | Navigation group | Purpose | Main data | Actions |
|---|---|---|---|---|
| **Home** | Primary | Where am I; what needs me | `/replay/state`, `/queue` count, recent permission or habit-change cards | Open Queue, task-specific report, replay controls |
| **Queue** | Primary | Answer what needs you | `/queue` | accept, reject, edit |
| **Actions** | Primary | What was done; cancel or undo | `/actions` | undo, cancel |
| **Permissions** (Licences) | Primary | What is allowed for each task/action, and why | `/licences` | none (read-only) |
| **Report card** | More → Insights | Historical results, with task/action scope when API supports it | `/report-card` | Drill into "Different" |
| **Habits** | More → Insights | Patterns found | `/habits` | deny |
| **Chains** | More → Insights | Follow-up patterns | `/chains` | none |
| **Tests** (Exams) | More → Insights or task detail | Trick-question results for one task/action | `/exams` | run a test (admin only) |
| **Metrics** | More → Insights | Attention and habit-change trends, with clear scope | `/metrics/summary` | none |
| **Privacy & web** (Exposure) | More | What text left for model processing and what web lookups were made | `/exposure`, `/web-facts` | none |
| **Record** (Ledger) | More | Tamper check | `/ledger/verify` | re-verify |
| **Settings** | More | Effective settings | `/settings` | none (read-only in v1) |
| **Radar board** | More, only when active | Verified opportunities with deadlines, sources and fee warnings | `/boards/radar`, `/items/{id}` | accept, reject, edit |
| **Library** | Deferred; hidden in v1 while Reading is cut | Saved links filed into collections | `/boards/reading` when implemented | accept, reject, edit |
| **Import help** | More/help | How to use your own data | static | none |

**States every screen must have:** loading (skeleton), empty (a friendly sentence), error (banner with retry), and "as of {time}" when showing stale data.

---

## 5. Navigation map

There are five primary destinations on desktop and mobile: **Home**, **Queue**, **Actions**, **Permissions**, and **More**. The route tree below shows the secondary screens reached from those destinations; it does not make each screen a separate top-level tab. More contains Insights (Report card, Metrics, Habits, Chains, Tests), Privacy & web, Record, Settings, and Import help. Radar appears in More only while its pack and API are active. Keep Reading's Library hidden until that pack is in scope.

Item detail opens from Queue, the report card, or Radar; it is a focused view, not another primary tab. Keep replay controls and service alerts persistent only when relevant to the current mode/state.

```
 Home ──┬── Report card ── (drill into "Different") ── Item detail
        ├── Queue ──────── Item detail
        ├── Actions ────── (undo / cancel)
        ├── Permissions ── (evidence, history)
        ├── Habits ┬ Chains
        ├── Tests
        ├── Metrics
        ├── Radar ─── Item detail (Check the sender)
        ├── Library
        ├── Privacy (includes web searches made)
        ├── Record
        └── Settings
 Persistent: replay bar (demo), banners (service slow, spending limit), mode badge (Demo / My data)
 Mobile: bottom bar with Home, Queue, Actions, Permissions, More (the rest)
```

---

## 6. Lifecycles the UI must reflect

### 6.1 An item

```
 arrives -> [Not enough history yet] (ABSTAIN, watch only)
         -> Watching (level 0)            -> nothing shown unless the user opens it
         -> Ready for you (SUGGEST)       -> user: Do it / Not this / Change -> Done or dismissed
         -> Needs you (ASK)               -> same answers
         -> Will do it in 10 minutes      -> user: Cancel   or   time passes -> Done
         -> Done (EXECUTE_UNDO / SILENT)  -> user: Undo within 7 days
 any state -> "You handled this yourself" when the footprint shows the user acted first
```

### 6.2 An action

`PENDING -> HELD -> DONE -> UNDONE`, or `HELD -> CANCELLED`, or `PENDING -> FAILED` (CONTRACT section 4).

### 6.3 A permission

```
 Watching -> Suggests -> Does it, with undo -> Does it quietly
     ^           ^               |                   |
     |           +---------------+-------------------+   after an alarm: back to Suggests until a new test passes
     +--------------------------- evidence falls below the bar: lower
```

Caps (CONTRACT I-4) are shown as "Never fully automatic: {reason}".

---

## 7. Microcopy

Tone: calm, specific, first person for the system ("I"), no jargon, no hype.

| Moment | Copy |
|---|---|
| Empty queue | "Nothing needs you right now." |
| Evidence line | "Matched you 148 of 148 times (safe estimate 98%). Passed the trick-question test on 14 Oct." |
| Capped permission | "Never fully automatic: this goes out to other people, so I'll always wait for you or give you 10 minutes to cancel." |
| Spot check | "Spot check: I would have done this myself. Tell me if you agree, so I keep the evidence honest." |
| Not enough history | "Not enough history yet to guess. I'm just watching." |
| Hands-off | "I never touch programs or scripts. Left as is." |
| Habit change | "Your habits changed. I'm back to suggesting until I pass the test again." |
| Failure | "Couldn't do this. Nothing was changed." (only if true; otherwise say what changed) |

Never write: "guaranteed", "safe", "100% accurate", "AI decided".
Numbers: show counts and the safe estimate as whole percentages (round down).

---

## 8. Edge cases (all screens)

| Case | Behaviour |
|---|---|
| Same item answered twice | First answer wins; second shows "Already answered" |
| Undo request arrives after the hold ended and the reply was sent | Undo is refused: "Already sent" (not recallable) |
| Permission lost while an action is held | The Executor re-checks and cancels; the item returns to Ready for you (CONTRACT section 8) |
| Item referenced in the queue is purged | Row shows "No longer available" |
| Very long text | Truncate with "Show more"; never render raw HTML from items (render as plain text) |
| Mixed languages in an item | Show as received; the system works best in English (the models' listed languages do not include Hindi or Tamil **(check)**), and the UI says "reading may be less reliable in this language" when the reader reports `other` |
| Clock skew in replay | The simulated date is the only date shown; real time appears only in the footer |

---

## 9. Accessibility and layout

- Tap targets at least 44 px; one-handed layout on a phone.
- Never use colour alone for meaning: levels use text and an icon.
- Contrast meets WCAG AA **(check with a tool)**.
- Every button has an accessible name; the queue is fully keyboard-operable.
- Respect reduced-motion settings; no auto-playing animation except the optional replay counter.
- Text scales to 200% without breaking the layout.

---

## 10. Mapping to the demo beats

| Demo beat (`DEMO_AND_SUBMISSION.md` section 2) | Journey | Screens |
|---|---|---|
| 1. The driving test | F1, F2 | Home, Report card |
| 2. A day in the life | F3, F4b, F8 | Queue, Actions, Chains |
| 3. Permissions earned | F5, F6 | Home card, Permissions |
| 4. The trick-question test | F9 | Tests |
| 5. Habit change | F7 | Home card, Permissions, Metrics |
| 2b. Opportunity Radar (Tavily) | F12, F13 | Radar board, Item detail, Privacy |
| Throughout | F9, F11 | Record badge, Privacy counter, replay bar |

---

## 11. UI acceptance checklist (Phase 9)

- [ ] Every journey F1 to F11 can be completed in the browser with the demo database.
- [ ] Every automatic action shows its reason and an Undo or Cancel button.
- [ ] No screen uses the words "licence", "class", "gate" or "ledger" in user-facing text.
- [ ] The five primary destinations are Home, Queue, Actions, Permissions, and More; secondary screens are grouped as described in section 5.
- [ ] No overall score is shown. Historical agreement names its task/action and includes counts, time range, and unresolved count; any family total is labeled as family-level context.
- [ ] A task-level score is not displayed until an approved API/contract change supplies that scope; a family score is never copied onto individual tasks.
- [ ] Loading, empty, error and stale states exist for every screen.
- [ ] The five demo beats run without console errors on a phone-sized viewport.
- [ ] Replay controls work at 1x, 10x and 100x without freezing the page.
- [ ] A tampered ledger (test fixture) shows the warning state.
- [ ] Text from items and web sources is never rendered as HTML.
- [ ] Every web-derived line shows its sources; no screen says "scam" as a verdict.
- [ ] The Privacy page lists the exact web queries sent.

---

## 12. Out of scope in v1

Editing settings; uploading real data in the browser; live Gmail or calendar connections; push notifications, email or chat notifications; multiple users; a "jump to date" replay control; a batch-answer endpoint (use repeated single answers).
