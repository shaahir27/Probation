# Probation

> A personal AI that earns permission to act, one task type at a time, by proving on the user's own history that it would have done what they did.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/Node-20%2B-green.svg)](https://nodejs.org/)

Built for the **NVIDIA Global AI Hackathon** (Personal AI Track) using **NVIDIA Nemotron** on **Nebius Token Factory**, with **Tavily** web grounding for asymmetric entity verification.

---

## What this is

Probation is a **permission engine**, not a generic inbox assistant. It watches what you do, predicts one proposed action, explains the evidence, and then either asks, suggests, acts with undo, or acts quietly — only for the exact kind of task and action that has earned that level.

The current prototype demonstrates the idea through email:

- **Gmail is the first end-to-end integration.** The private demo uses a real Gmail test account with two separately consented grants: read-only observation and an Executor-only write grant for archive, trash, forward-to-self and reply. The approved manifest forbids third-party recipients and permanent delete.
- **Google Calendar and Google Drive are shown as planned integrations** in **Connect apps**. They are not connected and cannot be connected in this build.
- The engine is designed for more than email. Calendar, files, chains, Radar and Reading have pack-level work in the repository, but they are **not part of this focused email release** and are not presented as finished workflows.

The core promise is **earned autonomy**, not a trust score. A useful request for approval is a valid result. A new mailbox does not arrive with permission.

---

## What the demo currently shows

### The live email path

1. Sign in with a local **email and password** account, or use the **owner key** fallback. Passwords are verified against local scrypt hashes and local API clients receive a short-lived HS256 JWT; the browser itself uses only a short-lived, HttpOnly, SameSite=Strict owner session. No credential enters browser storage, a URL or a response body. A refresh keeps the session; sign-out destroys it server-side.
2. Open **More → Connect apps**. **Connect Gmail** opens a genuine Google read-only consent flow in a separate local setup process. **Grant read, change and send** starts a second, explicit consent showing all three Gmail choices. Change and send are required for action access, while read-only remains a valid standalone choice. The API receives no Google tokens, callbacks or authorization URLs.
3. The setup verifies the exact read-only and write scopes, the configured test account and the approved native label (`Label_1`). The read and write refresh tokens live in separate owner-only directories; the write grant moves the connection from `SHADOW` to `ACTIVE`. A fresh OAuth grant is recorded as newer authorization than any earlier pause or revoke control.
4. The supervised runtime starts **API, observation, Brain, Webfacts, Examiner, Resolver and Executor** roles. Observation reads only the approved label; the Executor alone holds the write grant and the approved operation manifest.
5. **Overview** is the review desk. **Review** is a Gmail-style inbox: a compact message list opens into a continuous reading pane with the email, the decision controls and the evidence. **Activity** records real effects; **Permissions** explains what is allowed for each task/action. **More** holds the connection controls, performance, counts, web privacy, cost, integrity, settings and limits.
6. The owner can grant action access, pause/resume the connection and disconnect it. Real provider effects in this build: **archive**, **trash** and **forward/send** were executed through the Executor and confirmed by provider receipts. Every eligible archive and trash undo was then executed and confirmed with the original labels restored; **reply** is only available when the pipeline produced a validated draft. No draft is fabricated.

The live account's first request was a cold-start **ASK** — the product asking for a decision, which is the correct outcome for an account without earned permission. The Nemotron/Tavily path is wired and has separate D5 live evidence; the live review did not incur a new paid model or Tavily call.

### What the jury can click

| Where | What it demonstrates |
|---|---|
| **Overview** | Real read/action access, the next email, the review desk, permission snapshot and workspace connection state. |
| **Review / item detail** | A Gmail-style message list and continuous reading pane: subject, preview, full body, the proposed action, evidence, web verification and the owner's exact decision controls. |
| **Activity** | What Probation actually did, pending/held/completed/undone/failed states, real provider results, and undo only where the server offers it. A completed undo reads as settled, never as “not completed yet.” |
| **Permissions** | One task/action at a time: Watching, Suggests, Acts with undo, Acts automatically; evidence counts and caps. Level 0 is not presented as an earned permission. |
| **More → Connect apps** | Gmail read access, separate action access, pause/resume and confirmed disconnect, plus Calendar and Drive clearly marked Planned. |
| **More → Performance / Counts & trends / Trick tests** | The historical record, measured counts and code-graded exam history. |
| **More → Privacy & web / Cost & usage / Integrity record / Settings / Help** | Exact web queries and sources, model/usage and spend authority, the hash-chained record, effective settings and limits. |

There are honest empty states where the current live account has no data — for example no Tavily calls for the cold-start item and no earned permission yet. Probation does not fill them with sample rows.

---

## App and pack coverage

| App or pack | Status in this repository |
|---|---|
| **Gmail** | **Prototype, read and approved write path.** Real OAuth consent, separate read and Executor write grants, observation, review, archive, trash, forward/send, pause/resume and disconnect. No third-party recipient or permanent delete. |
| **Google Calendar** | **Planned.** Shown in Connect apps; no connect action and no execution. |
| **Google Drive** | **Planned.** Shown in Connect apps; no connect action and no execution. |
| **Files** | Code exists in the wider engine; not part of this email release and not shown as a working workflow. |
| **Chains / Habits / Radar / Reading** | Not part of this focused release. Legacy deep links show an explicit unavailable explanation, never fake boards. |
| **Local data import** | Command-line import only; there is no browser upload. |

The Gmail, Google Calendar and Google Drive product icons are served locally from Google's Brand Resource Center. They identify the corresponding integrations; Google retains all rights, and inclusion does not imply endorsement or availability. See [`frontend/public/integrations/ATTRIBUTION.md`](frontend/public/integrations/ATTRIBUTION.md).

---

## Architecture and invariants

```mermaid
flowchart LR
  B[Browser dashboard] -->|same-origin, HttpOnly owner session| A[FastAPI API]
  A --> D[(SQLite engine, ledger and private connector store)]
  S[Local supervisor] --> O[Observation role]
  S --> BR[Brain role]
  S --> W[Webfacts role]
  S --> E[Examiner role]
  S --> R[Resolver role]
  S --> X[Executor role]
  O -->|read-only Gmail grant| G[Gmail]
  BR --> N[Nemotron on Nebius Token Factory]
  W --> T[Tavily]
  X -.->|separately provisioned write grant| G
```

**Non-negotiable rules:**

- LLM output is **data only**; it holds no credentials or tools, and every output is schema-validated.
- Only the **Executor** performs target side-effects and holds write credentials. The API, Brain, Webfacts and the local setup process hold no write credential.
- **Fail closed:** a validation, provider, budget or clock failure becomes ask or watch, never an autonomous action.
- **No peeking:** computation uses `HistoryView(as_of=t)` only.
- The ledger is **append-only and hash-chained**; it is never updated or deleted.
- **Licences are derived from evidence**, not stored as user-editable truth. Caps and hands-off rules are hard-coded.
- The Examiner is **code**, not an LLM.
- Redaction happens before egress; no message body is logged; no URL from a mail body is fetched.
- Web facts may only **restrict or inform**, never raise autonomy. Raw web text stays inside the quarantined extractor and never reaches the policy, licence code or reply writer.
- No `.env` or secret is committed, printed or sent to an LLM.

The detailed authority is `docs/CONTRACT.md`, and the D6 API and frontend contract is summarized in `docs/wp9/D6_API_CONTRACT.md`. Both live in the local-only documentation directory described at the end of this file.

### Interface

The dashboard uses a light **Ledger & Signal** system: warm stone paper, forest ink, and one citron permit mark used only for state and focus. Review is a Gmail-style master–detail workspace — a compact message list, continuous reading pane, and a decision surface attached to the email rather than a stack of cards. Activity, Permissions and Connect apps are flat, rule-separated work surfaces. All colours meet body-text contrast on the paper ground.

Fraunces (display) and Manrope (interface) are self-hosted from the app bundle; there is no remote font request at runtime. Both are SIL Open Font License 1.1.

### Model mapping

| Role | Configured model |
|---|---|
| Email reader (`reader.mail.v4`) | `nvidia/nemotron-3-super-120b-a12b` |
| Other reader / quarantined extraction | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| Writer / wording | `nvidia/nemotron-3-super-120b-a12b` |
| Exam edits | `nvidia/Nemotron-3-Ultra-550b-a55b` (listed; not claimed as exercised) |
| Local novelty | `sentence-transformers/all-MiniLM-L6-v2`, CPU ONNX, local only |

The model mapping is fixed in configuration. There is no automatic model fallback. The D5 six-case intent smoke is discussed under **Measured evidence**, with its scope stated.

---

## Live evidence and measured results

### Verification on the final tree

| Check | Result |
|---|---|
| Frontend TypeScript | `npx tsc --noEmit` — clean |
| Frontend production build | `npm run build` — passed |
| Frontend unit tests | `npm run test:unit` — **18/18 passed** |
| Full browser acceptance | `npx playwright test --reporter=list` — **41/41 passed** (system Chrome, built bundle, isolated synthetic workspaces) |
| Focused Gmail setup/ACL/runtime tests | granted-identity, reconnect, migration, token ACL, setup API, callback parser and live-role allowlist suites passed |
| Gmail preflight | read and write token stores, ACLs and the fixed redirect `http://127.0.0.1:8765/` verified locally |
| Gmail consents | read-only consent completed; separate read/change/send action consent completed; both token ACLs verified |
| Live observation | four new labeled synthetic emails observed; **one demo ASK** remains unanswered; no fabricated watching rows |
| Gmail writes | **archive**, **trash** and **forward/send** executed through the Executor and confirmed by provider receipts |
| Gmail undos | all **four eligible archive/trash** requests now have `confirmed` Executor attempts and restored original labels; no undo is claimed without that receipt |
| Gmail reconnect | Real disconnect deleted both refresh tokens; fresh read and read/change/send consents restored `SHADOW` then `ACTIVE`; queued pre-reconnect disconnects are superseded by the new authorization sequence |
| Connect/action access | live UI shows **Connected / read-only** and **Granted** action access; four live undos processed after the fresh grant |
| Paid model/Tavily calls in this D6 live session | **0** |
| Full backend gate | `python scripts/check.py` — **1494 passed, 2 deselected, 0 failed**; ruff/format and both mypy gates clean; protected fixture/result hashes unchanged |

The browser suite covers known answer/copy truth, all primary routes, the More destinations, the Connect apps chooser, responsive layouts at 360/390/768/1440, 200% zoom, keyboard-only review, visible focus, announced errors, reduced motion, session isolation, safe links, production-bundle verification and zero console errors.

### The six-case Super smoke — scoped

The D5 frozen six-case mail-intent cohort scored **6/6 with configured Super** and **2/6 with Nano**. This is a **six-case smoke** only:

- it is **not** general model accuracy,
- it is **not** a Gmail flow score,
- it is **not** an autonomous permission result,
- and it does not transfer to the private account.

The live demo request is a cold-start ASK; the current demo does not claim that the live email produced a Nemotron draft.

### Budget authority

The paid-call authority is `data/d5/live/accounting.db`, scope `d5-nemotron-tavily` (gitignored local evidence; not committed). It has one budget scope per provider/model; ceilings are cumulative across milestones and worktrees.

| Provider | Confirmed | Unresolved | Usable position |
|---|---:|---:|---|
| Nebius Nano | $0.001109 (22 reconciled attempts) | 0 | per-model $1 scope; ~$0.9989 remaining |
| Nebius Super | $0.003896 (15 reconciled attempts) | 0 | per-model $1 scope; ~$0.9961 remaining |
| Tavily | 8.0 credits (9 recorded calls, 8 reconciled) | 1 `ambiguous` call | **11 credits usable** |

Nebius confirmed total across both scopes: **$0.005005** (29 succeeded, 8 failed closed). The one Tavily `ambiguous` row is an unresolved hold: it stays counted and must never be re-sent to "clear" it. **No new paid calls were made in this D6 live session.** Do not create a fresh allowance; re-read the authority before any paid run.

---

## Run it locally

### Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- Google Chrome is optional for the Playwright suite; the suite uses the installed system Chrome (`channel: "chrome"`).
- For live Gmail: a Google Cloud project with the Gmail API enabled, a test account, and either a **Desktop app** OAuth client (recommended) or a Web client with the exact redirect below.
- For live model/Tavily calls: Nebius/Tavily credentials and an approved spend position.

### Install

From the repository root:

```powershell
# Windows
C:\Users\shaah\miniconda3\python.exe -m pip install -e ./backend[dev]
cd frontend
npm install
cd ..
```

```bash
# macOS / Linux
python -m pip install -e './backend[dev]'
cd frontend && npm install && cd ..
```

If `make` is available, `make setup` is the shortcut; on Windows use `make.cmd setup`. The explicit commands above are the portable path.

### Configure

```powershell
Copy-Item .env.example .env
```

Set these local values in `.env` (never commit it, never paste them into chat or logs):

```text
PROBATION_GMAIL_OWNER_API_KEY=<local owner key used by the dashboard>
PROBATION_GMAIL_OWNER_ID=local-owner
PROBATION_GMAIL_STORE=data/private/connectors/gmail_metadata.db
PROBATION_GMAIL_ACCOUNT=<the Google test account>
PROBATION_GMAIL_CLIENT_ID=<OAuth client id>
PROBATION_GMAIL_CLIENT_SECRET=<OAuth client secret>
PROBATION_GMAIL_LABEL=Label_1
PROBATION_GMAIL_REDIRECT_PORT=8765
LLM_API_KEY=<Nebius Token Factory key>
TAVILY_API_KEY=<Tavily key>
```

`PROBATION_GMAIL_LABEL` is the **native Gmail label ID**, not the display name. The setup script also accepts `PROBATION_GMAIL_READ_CLIENT_ID` / `PROBATION_GMAIL_READ_CLIENT_SECRET` if you keep a separate read-only OAuth client.

For a **Web** OAuth client, add this exact URI under **Authorized redirect URIs**:

```text
http://127.0.0.1:8765/
```

For a **Desktop app** client, no redirect registration is needed; the loopback port is accepted by that client type. The setup script pins the callback to the same fixed URI so both client types can work.

The `.env.example` documents the model and embedding settings. The local MiniLM novelty model is optional when only reading email but is required for the policy/novelty path; if it is missing, novelty is unavailable and autonomous execution cannot be authorized. The reviewed manifest command is:

```text
python -B scripts/verify_embeddings.py --model-dir data/models/all-MiniLM-L6-v2/d13954661f83248295ba75c1ed411eef3b7b936e --manifest data/models/all-MiniLM-L6-v2/manifest.json
```

### Initialize the database

```powershell
C:\Users\shaah\miniconda3\python.exe -m probation.cli db migrate
```

`db migrate` applies the complete current schema (WP1, lifecycle, replay, provenance and accounting) and leaves the ledger records unchanged. It refuses a missing database rather than creating one silently. Back up `data/db/probation.db` before changing an existing local database.

### Start the app

Use a local terminal from the repository root. Do not run a plain `serve` on port 8000 at the same time as the live runtime.

```powershell
# Terminal 1 — supervised API + observation + Brain + Webfacts + Examiner + Resolver
make.cmd serve-live
# equivalently:
# C:\Users\shaah\miniconda3\python.exe -m probation.cli serve --gmail-runtime

# Terminal 2 — frontend
make.cmd web
```

Open `http://localhost:5173` (or the alternate local port `http://localhost:5174`) and sign in with a local email/password account, or choose **Use owner key instead** and enter `PROBATION_GMAIL_OWNER_API_KEY`. Then open **More → Connect apps**. An account created in the app starts with its own empty workspace and can connect its own Gmail; the owner-key route opens the workspace already bound to the configured local owner.

If port 8000 is occupied by another server, keep the single runtime on 8001 and point the frontend proxy at it before starting Vite:

```powershell
C:\Users\shaah\miniconda3\python.exe -m probation.cli serve --gmail-runtime --port 8001
cd frontend
$env:PROBATION_D6_E2E_API_TARGET="http://127.0.0.1:8001"
npm run dev -- --port 5173
```

Open `http://localhost:5173`. Do not run a separate plain API on 8000: access changes and undo must go to the same runtime that owns the Executor and workers.

### Connect Gmail

1. Sign in with the local account, or use the owner-key fallback.
2. **More → Connect apps → Connect Gmail** and approve **read-only Gmail access**.
3. The setup child writes the read-only refresh token under the owner-only `data/private/` store and registers a `SHADOW` connection. It verifies the exact scope, account and label before persisting anything.
4. The runtime then observes the approved label. The UI shows **Connected / read-only**; email processing and suggestions have their own separate state.
5. **Grant read, change and send** starts a second consent that shows all three Gmail choices. Change and send are required for action access; choosing only read leaves the connection read-only. The write token is stored in a separate owner-only directory, never exposed to the API, Brain or Webfacts, and the connection moves to `ACTIVE`.
6. **Pause access**, **Resume access** and **Disconnect Gmail** are durable connection commands. Disconnect deletes both owner-only refresh tokens and requires a new Google consent, with both read and action choices again, before any further email is read or acted on. A fresh OAuth grant supersedes controls completed before it; a revoke issued after that grant still blocks immediately.

If Google blocks the request, run the safe preflight from the project root:

```powershell
C:\Users\shaah\miniconda3\python.exe -B scripts\d6_gmail_setup.py --check
```

It prints booleans and the exact redirect URI, never a token or secret. The common cause is a Web OAuth client without the saved `http://127.0.0.1:8765/` redirect; the other causes are the wrong test account, a non-Desktop client with no registered loopback URI, or an expired consent window.

To diagnose a failure with visible safe output, run the same local setup child for the required role:

```powershell
C:\Users\shaah\miniconda3\python.exe -u -B scripts\d6_gmail_setup.py --authorize-read
C:\Users\shaah\miniconda3\python.exe -u -B scripts\d6_gmail_setup.py --authorize-write
```

### Tests

```powershell
# Full backend gate (isolated snapshot; ruff, format, mypy and pytest)
C:\Users\shaah\miniconda3\python.exe scripts\check.py

# Frontend
cd frontend
npx tsc --noEmit
npm run test:unit
npx playwright test --reporter=list
```

The Playwright harness builds the production bundle, starts a throwaway synthetic API and a built frontend on separate loopback ports, and uses the installed system Chrome. It does not use the private Gmail account or the private owner key.

---

## Security and privacy

- Local accounts store only salted scrypt password hashes in an owner-only SQLite file. The browser signs in with the HttpOnly, SameSite=Strict session; local API clients can receive a short-lived HS256 JWT. No password, JWT or owner key enters browser storage, a URL or a response body. Logout destroys the server-side session, cached private data, drafts and in-flight responses. The browser suite verifies that no private row is left in storage or the DOM.
- The API holds **no Google credential** and receives no OAuth callback, authorization URL or token. The setup child runs locally; the runtime supervisor reads the owner-only refresh files and injects the read grant into the observation child and the write grant into the Executor child only.
- The private connector store and refresh files are protected by verified Windows owner-only ACLs. A failed ACL check denies the setup instead of falling back to an unprotected path.
- Only the Executor can perform target side-effects, and only with the approved manifest: self-forward, archive, trash, reply and their undo paths. A send or unknown result is never automatically retried; an ambiguous result is reconciled or left unknown.
- Message bodies are not logged, sent to Tavily, or used to fetch URLs. Tavily queries are built by code from public entity strings only. Raw web text is quarantined and never reaches the policy, licence code or reply writer.
- Web facts can only restrict or inform; they never raise autonomy or change policy probabilities.
- `.env`, `data/private/`, provider manifests, tokens and local logs are not committed. The repository contains synthetic data only.

---

## Limitations and what is not claimed

- This is the **D6 demo release**, not the full F01–F42 product.
- Gmail writes are limited to the approved manifest: **archive**, **trash**, **forward-to-self** and a reviewed **reply** only when a validated draft exists. There is no third-party recipient, permanent delete, settings change or automatic retry.
- Live **undo** is proven for archive and trash: all four eligible requests have confirmed Executor attempts and restored original labels. Undo still fails closed when the provider's state or history evidence is incomplete, and a forward/send cannot be recalled. A refused undo is reported as refused and changes nothing.
- **Google Calendar and Google Drive are planned**, not implemented.
- Files, chains, habits, Radar and Reading are not part of this focused email release. Their legacy routes state that they are unavailable; they do not render fake data.
- No public deployment, hosted multi-user service, real personal data, mobile app, push notifications or hosted URL is claimed here. Local accounts exist only on this machine. Deployment is a separate step and was intentionally not performed.
- The six-case Super smoke is not accuracy, a Gmail score or an autonomy result.
- The live demo item is a cold-start request for approval; it does not claim that a model draft was produced for that specific email.
- The local cost panel reflects the app's recorded spend; the cumulative D5 accounting authority is a separate record. Neither is a provider invoice.

---

## Documentation

The product contract, plans, handoffs, acceptance matrix and test catalogue are maintained in the local `docs/` directory. Both `docs/` and `build_history/` are intentionally ignored and are not published in the GitHub repository.

## License

MIT License. See [`LICENSE`](LICENSE).

## Credits and assets

- Dashboard: React, TypeScript, Vite, TanStack Query, Tailwind CSS and Lucide.
- Backend: Python 3.11, FastAPI and SQLite.
- Models: NVIDIA Nemotron served through Nebius Token Factory.
- Web grounding: Tavily.
- Gmail, Google Calendar and Google Drive icons: Google Brand Resource Center; see [`frontend/public/integrations/ATTRIBUTION.md`](frontend/public/integrations/ATTRIBUTION.md). Google retains all rights; the marks identify the integrations and do not imply endorsement.
- Fraunces and Manrope fonts: SIL Open Font License 1.1; see [`frontend/public/fonts/ATTRIBUTION.md`](frontend/public/fonts/ATTRIBUTION.md). Files are served locally, not from a remote font foundry.
