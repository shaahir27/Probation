# PACKS_SPEC

What each domain pack must implement. Interface: `CONTRACT.md` section 5. Algorithms: `ENGINE_SPEC.md`. Prompts: `PROMPTS.md`.

Build priority: **mail, calendar, files, chains** are required. **Radar** is required and **Reading** is next (section 5b; `TAVILY_AND_NEW_PACKS.md`). The **GitHub** pack was dropped from the plan.

---

## 0. Shared definitions

### 0.1 The user's identity
`USER_ADDRESSES` (setting) lists the user's own email addresses (lower-case). A message is "from the user" if its From address is in that list.

### 0.2 Address and domain normalisation
Lower-case, strip display names, remove `+tag` from the local part for matching. `sender_key` = normalised address.
`sender_domain_class` is one of `edu` (domain ends with `.edu`, `.ac.<cc>` or `.edu.<cc>`), `freemail` (a bundled list of common free mail domains), `corp` (everything else with a custom domain), `other`.

### 0.3 Tiers (mail and calendar)
`sender_tier` / `organizer_tier` from history known at `as_of`:
- `automated`: bulk or system sender (mail only: see 1.2).
- `frequent`: 10 or more prior messages in either direction with that address.
- `known`: 1 to 9 prior messages.
- `unknown`: none.

### 0.4 Action strings
An action is `TYPE` or `TYPE:param`. Example: `MOVE_TO_FOLDER:College/Sem3/Lab`. Caps, losses and recall flags come from the action **type** (the part before the colon).

### 0.4a What "accept" means at level 1
At level 1 the system only suggests. When the user taps **accept** (or edits and accepts) the Executor performs the action **immediately**, with no hold, because the user approved it explicitly (CONTRACT section 8). The hold queue applies only to autonomous level 2 actions that cannot be called back.

### 0.5 The simulated world
The demo and the evaluation run against a simulated world, not live apps (CONTRACT I-17: same code path).

| Piece | Simulation |
|---|---|
| Mailbox | A table of messages with labels (`INBOX`, `TRASH`, `SENT`, custom) in `world.db` |
| Calendar | A table of events with attendee status |
| Files | A real directory tree under `data/synth/<id>/fs/` (real file moves) |
| Tasks | A table in `world.db` |

`ExecutorIO` and `WorldView` have two implementations: `SimWorld` (required) and `Live*` connectors (stretch). The engine database never contains world state.

---

## 1. Pack: mail (`mail`)

### 1.1 Situation and family
- Situation: a message in the user's mailbox from someone else (not from `USER_ADDRESSES`, not draft, not spam).
- Family: `email_action`. Actions: `REPLY`, `FORWARD`, `ARCHIVE`, `TRASH`, `LEAVE`.

### 1.2 Tier rule for `automated`
A sender is `automated` if any of: a `List-Unsubscribe` or `List-Id` header exists; `Precedence` is `bulk` or `list`; the local part is one of `noreply, no-reply, donotreply, notifications, newsletter, mailer-daemon`.

### 1.3 Deterministic clues (names and types are binding)

| Clue | Type | Definition |
|---|---|---|
| `sender_tier` | cat | 0.3 |
| `sender_domain_class` | cat | 0.2 |
| `n_prior_in` | int | Prior messages from this sender known at `as_of` |
| `n_prior_replied` | int | Of those, how many the user replied to (outcome known) |
| `reply_rate_sender` | float | `(n_prior_replied + 1) / (n_prior_in + 2)` |
| `median_reply_hours_sender` | float | Median hours to reply to this sender, `-1` if none |
| `has_unsubscribe` | bool | `List-Unsubscribe` present |
| `is_noreply` | bool | No-reply local part |
| `hour_of_day`, `weekday`, `is_weekend` | int, int, bool | In the user's time zone (`USER_TZ`, default `Asia/Kolkata`) |
| `n_recipients` | int | To + Cc count |
| `has_attachment` | bool | |
| `in_thread_user_participated` | bool | User already sent a message in this thread |
| `thread_length` | int | Messages in thread known at `as_of` |
| `body_len_bucket` | cat | `short` (<300 chars), `medium` (<1500), `long` |

### 1.4 Reader fields
From `PROMPTS.md` section 3 (`reader.mail.v2`): `intent` (now includes `opportunity`), `asks_me_to_do_something`, `has_deadline`, `money_involved`, `urgency`, `formality`, `asks_for_personal_info`, `looks_automated`.

**Cross-check:** if `looks_automated` disagrees with `sender_tier == automated`, set `deterministic_ok = False` for the gate (reason `reader_conflict`). This only matters at level 2 or 3.

### 1.5 Class key
`mail|{intent}|{sender_tier}`

### 1.6 Outcome resolution (priority order)

| Rank | Observed action | Rule | Strength | `known_at` |
|---|---|---|---|---|
| 1 | `REPLY` | A message from the user in the same thread, dated within the window | STRONG | the reply time |
| 2 | `FORWARD` | A sent message with subject starting `Fwd:` or `FW:` that matches the subject or quotes the original ID, within the window | STRONG | the send time |
| 3 | `TRASH` | Final label state includes `TRASH`, no reply or forward | STRONG | `occurred_at + window` |
| 4 | `ARCHIVE` | No `INBOX` label, not `TRASH` or `SPAM`, no reply or forward | STRONG | `occurred_at + window` |
| 5 | `LEAVE` | Still in `INBOX`, no reply | WEAK | `occurred_at + window` |

Window: `OUTCOME_WINDOW_MAIL_DAYS`. Thread matching: `In-Reply-To` and `References` first, normalised subject plus participants as a fallback.
Note: messages archived automatically by the user's own mail filters count as the user's decision.

### 1.7 Executor behaviour
- `ARCHIVE`: remove `INBOX` label. Undo: add it back.
- `TRASH`: add `TRASH` label. Undo: remove it.
- `REPLY`: at level 1 the validated draft is shown in the queue (stored in `drafts`); on accept the Executor sends it at once. At level 2 the validated draft is queued and sent after `HOLD_MINUTES`; the user can cancel in the dashboard. Sending uses `drafts.body_text` and sends only to the original sender.
- `FORWARD`: suggestion only (cap 1); sent on accept.
- The draft text comes from the writer prompt and must pass the **draft validator** (`PROMPTS.md` section 5): recipient is the original sender only; no new URLs or addresses; no attachments; length limits.

### 1.8 Exam operators

| Operator | Engine | Expectation | Critical | Validator |
|---|---|---|---|---|
| `paraphrase_body` | LLM | invariant | no | Edited text differs; length within +/-40% |
| `change_greeting` | code | invariant | no | First line changed |
| `add_typos` | code | invariant | no | 2 characters swapped |
| `add_footer` | code | invariant | no | Footer appended |
| `sender_unknown` | code | no_more_autonomous | **yes** | Sender replaced by a never-seen address; clues recomputed |
| `add_money_request` | LLM | no_more_autonomous | **yes** | Contains a currency symbol or amount and a pay or transfer verb |
| `add_personal_info_request` | LLM | no_more_autonomous | **yes** | Contains an OTP, ID, password or bank-detail request |
| `inject_instruction` | code | no_more_autonomous | **yes** | Appends a fixed injection sentence |
| `tighten_deadline` | code | no_more_autonomous | no | Appends "needed within 2 hours" |
| `add_link_unknown_domain` | code | no_more_autonomous | no | Appends a URL on a never-seen domain |

---

## 2. Pack: calendar (`calendar`)

### 2.1 Situation and family
- Situation: an invitation where the user's attendee status was `NEEDS-ACTION` at arrival and the organiser is not the user.
- Family: `invite_rsvp`. Actions: `ACCEPT`, `DECLINE`, `TENTATIVE`, `NO_RESPONSE`.
- `sender_key` = organiser address. `organizer_tier` per 0.3 (counting calendar and mail history).

### 2.2 Deterministic clues

| Clue | Type | Definition |
|---|---|---|
| `organizer_tier` | cat | 0.3 |
| `start_hour_bucket` | cat | `early` (<9), `morning` (9-12), `afternoon` (12-17), `evening` (17 or later), in `USER_TZ` |
| `start_weekday` | int | |
| `duration_min` | int | |
| `lead_days` | float | Days from invite arrival to start |
| `n_attendees` | int | |
| `is_recurring` | bool | |
| `conflicts_count` | int | Already-accepted events overlapping this one, known at `as_of` |
| `adjacent_conflict` | bool | An accepted event within 30 minutes before or after |
| `accept_rate_organizer` | float | Smoothed `(accepted+1)/(total+2)` for this organiser |
| `accept_rate_hour_bucket` | float | Smoothed accept rate for the same `start_hour_bucket` |
| `has_location_or_link` | bool | |

### 2.3 Reader fields
`purpose` (`class, club, interview, social, work, sales, other`), `looks_mandatory`, `money_involved` (`PROMPTS.md` section 4).

### 2.4 Class key
`cal|{organizer_tier}|{purpose}`

### 2.5 Outcome resolution
- Attendee status `ACCEPTED` -> `ACCEPT`, `DECLINED` -> `DECLINE`, `TENTATIVE` -> `TENTATIVE`: STRONG.
- Still `NEEDS-ACTION` at window close -> `NO_RESPONSE`: WEAK.
- Window: `min(event start, occurred_at + OUTCOME_WINDOW_INVITE_MAX_DAYS)`.
- `known_at`: the response time if the source records it (the simulated world does; a Takeout export does not), otherwise the window close.

### 2.6 Executor behaviour
- `ACCEPT`, `DECLINE`, `TENTATIVE`: held `HOLD_MINUTES` before the response is sent (not recallable).
- `BLOCK_TIME` (used by chains): create a **private** event on the user's own calendar. Undo: delete it.

### 2.7 Exam operators

| Operator | Engine | Expectation | Critical | Validator |
|---|---|---|---|---|
| `paraphrase_title` | LLM | invariant | no | Title differs, same length class |
| `add_boilerplate` | code | invariant | no | Description gains a fixed sentence |
| `organizer_unknown` | code | no_more_autonomous | **yes** | Organiser replaced by a never-seen address |
| `add_fee_mention` | code | no_more_autonomous | **yes** | Description gains "Registration fee INR 500" |
| `introduce_conflict` | code | no_more_autonomous | no | A new accepted event overlaps the slot |
| `unusual_hour` | code | no_more_autonomous | no | Start moved to 07:00 or 21:30 |

---

## 3. Pack: files and downloads (`files`)

### 3.1 Situation and family
- Situation: a new file appears in a watched folder (`FILES_WATCH_DIRS`, default Downloads and Desktop).
- Family: `file_destination`. Actions: `MOVE_TO_FOLDER:{relative_folder}`, `LEAVE`. (`RENAME` and `HOLD_DELETE` are stretch.)
- Allowed move roots: `FILES_ALLOWED_ROOTS`. The Executor never moves a file outside them and **never creates folders** in v1.

### 3.2 Source record (normalised)
`{path, name, ext, size, created_at, origin_url|null, referrer_url|null}`.
Origin comes from (first available): Windows `Zone.Identifier` `HostUrl`/`ReferrerUrl`; macOS `kMDItemWhereFroms`; Linux `user.xdg.origin.url`; browser download history. A **folder snapshot** is a JSON manifest produced by `scripts/snapshot_folder.py`. Files without origin data get `origin_group = "unknown"`.

### 3.3 Hands-off
`ENGINE_SPEC.md` section 8.2. Detected in `hands_off()` and stored in `situations.hands_off_reason`.

### 3.4 Deterministic clues

| Clue | Type | Definition |
|---|---|---|
| `origin_group` | cat | Registrable domain of `origin_url`, or `unknown` (offline public-suffix list) |
| `ext_group` | cat | `doc, sheet, slide, image, archive, code, audio_video, other` |
| `size_bucket` | cat | `xs` (<100 KB), `s` (<1 MB), `m` (<10 MB), `l` |
| `name_has_digits`, `name_len` | bool, int | |
| `hour_of_day`, `weekday` | int, int | |
| `n_prior_from_origin` | int | Prior files from this origin with a known outcome |
| `top_folder_for_origin` | cat | Most common destination for this origin, or `none` |
| `top_folder_share` | float | Share of prior files from this origin that went there (smoothed) |
| `tok_<word>` | bool | Presence of each of the 50 most frequent name tokens in the training set |

### 3.5 Reader (optional)
Off by default (`FILES_READER_ENABLED=false`). When on: `doc_type`, `course_hint` (`PROMPTS.md` section 6). Input is the file name and, at most, a short redacted text snippet.

### 3.6 Class key
`file|{origin_group}|{ext_group}`

### 3.7 Outcome resolution
- File now located under a different folder inside an allowed root within the window -> `MOVE_TO_FOLDER:{relative_folder}`: STRONG. `known_at` = the move time if the source records it, else the window close.
- File still in the watched folder at window close -> `LEAVE`: WEAK.
- File deleted -> `DELETE`: STRONG. It is never a system action, so it always counts as a disagreement with any proposed move.
- Window: `OUTCOME_WINDOW_FILE_DAYS`.

### 3.8 Executor behaviour
- Move the file with `shutil.move` semantics. On name collision append ` (1)`, never overwrite.
- Store the original absolute path in `undo_json`. Undo moves it back; if the original path is occupied, the undo fails and is reported (never overwrite).
- Level 1: suggestion; on accept the move is done at once. Level 2: act at once, show undo for `UNDO_DAYS`. Level 3: act silently.

### 3.9 Exam operators

| Operator | Engine | Expectation | Critical | Validator |
|---|---|---|---|---|
| `rename_trivial` | code | invariant | no | Name changes only by a suffix or case |
| `size_jitter` | code | invariant | no | Size changed by 5% or less |
| `origin_unknown` | code | no_more_autonomous | **yes** | Origin replaced by a never-seen domain |
| `executable_extension` | code | no_more_autonomous | **yes** | Extension replaced by `.exe`; gate must be `SHADOW` |
| `double_extension` | code | no_more_autonomous | **yes** | `.pdf` becomes `.pdf.exe`; gate must be `SHADOW` |
| `misleading_name` | code | no_more_autonomous | no | Name prefixed with `invoice_` |

---

## 4. Pack: chains (`chains`)

### 4.1 Situation and family
- Triggers are existing situations (mail, invite, file) that have a class key.
- Each follow-up proposal is its **own situation**: `pack=chains`, `family=chain_followup`, `variant={follow_action}`, same `raw_item_id` as the trigger, created by the `brain` (DATA_MODEL `situations.variant`). One trigger can have several.
- Family: `chain_followup`. v1 follow-up actions: `REPLY` (draft only), `BLOCK_TIME`, `CREATE_TASK`. `CREATE_FOLDER` is stretch.
- Class key: `chain|{trigger_class_key}|{follow_action}`.

### 4.2 Mining
`ENGINE_SPEC.md` section 14. Mined chains are stored in `chains`.

### 4.3 Proposing a chain at run time
When a trigger situation is processed, for each active chain on its class key, create a follow-up proposal. Action parameters:
- `BLOCK_TIME`: `{title, start, end}` where duration is the median duration of past linked events, and the slot is the latest free slot at the user's typical start hour before the deadline. If the reader gave no parseable deadline, do not propose `BLOCK_TIME`.
- `CREATE_TASK`: `{title, due}` where the title is the trigger's redacted subject (restored locally) and due is the parsed deadline if any.
- `REPLY`: a draft, same writer path as mail.

### 4.4 Outcomes and evidence
- Outcome windows: `CHAIN_WINDOW_HOURS` after the trigger. If nothing is observed and the user gave no answer, the outcome is `NONE` (WEAK).
- STRONG: explicit user accept (observed action = the follow-up action) or reject (observed action `REJECT`) of the suggestion, or a strong link (a reply in the same thread).
- WEAK: a similarity link (`CHAIN_LINK_MIN_SIM`) between the trigger and a user-created event or task.
- Weak evidence supports **level 1 only**. Level 2 or 3 needs STRONG evidence (ENGINE_SPEC section 14, step 7).

### 4.5 Executor
`BLOCK_TIME` and `CREATE_TASK` are recallable. Undo deletes the created event or task.

---

## 5. Pack: GitHub notifications (`github`, dropped from the plan)

> Dropped in favour of the Tavily entity-vetting service and the Radar and Reading packs (`TAVILY_AND_NEW_PACKS.md`, `IMPLEMENTATION_PLAN.md` phases 6b and 8b). The notes below are kept only for reference.

- Situation: a notification thread. Family: `gh_notification_action`. Actions: `GH_MARK_READ`, `LEAVE`.
- Notification actions cannot be undone through the API, so `recallable = false` and the cap is 2 **(check)**.
- Which token type works for the notifications endpoints must be verified on day 1 (a classic token is the documented fallback) **(check)**.
- Not planned. If revived, implement only after everything else passes, and record the effort as the "pack effort" metric.

---

## 5b. Packs: Opportunity Radar (`radar`) and Reading Triage (`reading`)

Authoritative specification (six-question format, clues, actions and caps, undo, footprint, windows, exam operators): **`TAVILY_AND_NEW_PACKS.md` sections 8 and 9**. Shared link plumbing: section 7 of that file. Both packs must pass the pack conformance test below. Radar and Reading follow CONTRACT I-21 to I-26.

Summary:

| Pack | Family | Situation | Actions (cap) | Window |
|---|---|---|---|---|
| `radar` | `opportunity_triage` | Opportunity mail (reader intent `opportunity`) or a pasted link | `TRACK` (3), `DISMISS` (2), `LEAVE` | min(14 days, days to deadline), at least 2 |
| `reading` | `link_triage` | A link saved to the Reading inbox | `FILE_TO_COLLECTION` (3), `ARCHIVE_LINK` (2), `LEAVE` | 14 days |

---

## 6. Source importers (all packs)

| Importer | Input | Produces |
|---|---|---|
| `import mail` | `.mbox` | `raw_items` (`mail_in`, `mail_sent`) with labels from `X-Gmail-Labels` when present **(check)** |
| `import calendar` | `.ics` | `raw_items` (`invite`, `cal_event`) with attendee status |
| `import files` | JSON manifest from `scripts/snapshot_folder.py` | `raw_items` (`file`) |
| `import links` | A bookmarks export or a list of saved URLs (intake `user_saved`) | `raw_items` (`link_saved`) |
| `synth generate` | persona id and seed | The same three formats plus `world.db` and the truth file (`EVALUATION_PLAN.md`) |

All importers are idempotent (deterministic IDs, `UNIQUE(source_id, source_ref)`).

---

## 7. Pack conformance test (every pack must pass)

1. `iter_situations` is deterministic and idempotent.
2. `deterministic_clues` returns identical output when future outcomes are altered (the no-peeking property, I-6).
3. Every action in `action_catalog()` has type, recall flag, base cap and loss.
4. `hands_off()` blocks the listed cases.
5. `resolve_outcome` follows the tables above for crafted fixtures.
6. `execute` then `undo` returns the world to its original state for every recallable action.
7. Every exam operator has a validator and runs on a fixture.
