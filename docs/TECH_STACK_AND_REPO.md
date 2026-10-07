# TECH_STACK_AND_REPO

Tools, repo layout, settings, commands and deployment. Authority: below `CONTRACT.md`.
Do not pin versions in this file. Pin them in lockfiles (`uv.lock` or `requirements.lock`, `package-lock.json`).

---

## 1. Stack choices

| Layer | Choice | Why |
|---|---|---|
| Language (backend) | Python 3.11 or newer | Best fit for the statistics and ML libraries |
| API | FastAPI + Uvicorn | Typed, fast to build, automatic docs |
| Types and validation | Pydantic v2 (+ `pydantic-settings`) | Contracts as code; settings from environment |
| Database | SQLite in WAL mode (stdlib `sqlite3`) | One file per user, no server, enough for our scale (`SYSTEM_DESIGN.md` section 14) |
| LLM access | `openai` Python SDK pointed at an OpenAI-compatible base URL | Nebius Token Factory is OpenAI-compatible |
| Retries | `tenacity` | Backoff and jitter |
| Web grounding | Tavily (`tavily-python` or plain `httpx` to `https://api.tavily.com`) | Entity vetting (Search) and page reading (Extract); `TAVILY_API_KEY` in `.env` |
| Numerics | `numpy`, `scipy`, `scikit-learn` | Logistic regression, Beta quantiles, temperature scaling |
| Local embeddings | `fastembed` (ONNX) with `all-MiniLM-L6-v2` **(check)**; fallback `sentence-transformers` | Avoids a heavy PyTorch install on a small VM |
| Parsing | stdlib `mailbox` and `email`; `icalendar`; `python-dateutil`; `dateparser` | MBOX, ICS and deadline text |
| Domains | An offline public-suffix list (`publicsuffix2` or similar) **(check)** | Registrable domains without network calls |
| CLI | `typer` + `rich` | Deterministic commands |
| Files (stretch live mode) | `watchdog` | File-system events |
| Tests | `pytest`, `pytest-cov`, `hypothesis` | Unit and property tests |
| Lint and types | `ruff`, `mypy` (strict on `core/` and `engine/`) | Catch mistakes early |
| Frontend | React + Vite + TypeScript + Tailwind + Recharts + TanStack Query | Fast dashboard with charts |
| Frontend tests | Vitest (optional Playwright smoke test) | |
| Container | Docker + Docker Compose | Reproducible deployment |
| Sandbox (optional lock) | NVIDIA OpenShell **(check)** | Network allow-list for `brain` and `examiner` |

Models (all via Nebius Token Factory): Nemotron Nano class for the reader, Super for writing and wording, Ultra for the final demo-persona exam edits (Nano or Super write the other exam edits). Exact model name strings come from the Token Factory console **(check)**.

---

## 2. Repo layout (create exactly this)

```
probation/
  AGENTS.md
  LICENSE
  README.md
  Makefile
  .env.example
  .gitignore
  docs/                                  <- the documents in this folder
  config/
    brands.json                          <- about 150 brand -> official domains (verify each entry)
    prices.json                          <- model price table (USD per 1M tokens), see 4.2
  backend/
    pyproject.toml
    src/probation/
      __init__.py
      config.py                          <- all tunables (ENGINE_SPEC section 12)
      cli.py
      core/
        types.py                         <- Pydantic models (CONTRACT section 4)
        enums.py
        clock.py                         <- Clock (replay | live)
        hashing.py                       <- det_id, canonical_json, ledger_hash
        history.py                       <- HistoryView(as_of)
      db/
        schema.sql                       <- DATA_MODEL section 1, verbatim
        connection.py
        access.py                        <- per-process write helpers (CONTRACT section 3)
        ledger.py
      llm/
        client.py                        <- LLMClient (CONTRACT section 6)
        cache.py
        budget.py
        redact.py                        <- PROMPTS section 1
        prompts/                         <- {id}.v{N}.md files (PROMPTS section 2)
        schemas/                         <- JSON schemas
      packs/
        base.py                          <- PackAdapter protocol
        registry.py
        mail/        (clues.py, resolver.py, executor.py, exam_ops.py, importer.py)
        calendar/    (same set)
        files/       (same set)
        chains/      (mining.py, proposer.py, executor.py)
        radar/       (Opportunity Radar)
        reading/     (Reading Triage)
      engine/
        replay.py                        <- ENGINE_SPEC section 1
        features.py
        policy.py                        <- section 4
        novelty.py                       <- section 5
        evidence.py                      <- section 6.1
        licence.py                       <- sections 6.2, 6.3
        caps.py                          <- section 8 (hard-coded)
        handsoff.py                      <- section 8.2 (hard-coded)
        gate.py                          <- section 7
        drift.py                         <- section 11
        habits.py                        <- section 13
        exam.py                          <- section 15
        report.py                        <- section 17
      web/                               <- Tavily grounding (TAVILY_AND_NEW_PACKS.md); NEVER imported by policy, evidence or licence code
        client.py  query_guard.py  derive.py  view.py
      links/
        sanitise.py  extract.py          <- URL hands-off rules and the quarantined-extractor plumbing
      workers/
        ingestor.py  brain.py  resolver.py  examiner.py  executor.py  scheduler.py  webfacts.py
      api/
        app.py
        routes/      (one module per path group in CONTRACT section 9)
      synth/
        personas.py  habits_dsl.py  generator.py  render.py  world.py
      eval/
        baselines.py  metrics.py  run_eval.py  human_study.py
    tests/
      unit/  property/  integration/  fixtures/
  frontend/
    package.json  vite.config.ts  tailwind.config.ts
    src/  (pages: ReportCard, Licences, Queue, ItemDetail, Actions, Habits, Chains, Exams, Metrics, Exposure, Ledger, Settings, Replay; see USER_FLOW.md)
  deploy/
    docker-compose.yml
    Dockerfile.backend  Dockerfile.frontend
    vm-setup.sh
    openshell/        <- sandbox policy files (check)
  scripts/
    spike_llm.py  spike_embed.py  spike_tavily.py  snapshot_folder.py  verify_budget.py
  data/                                  <- gitignored
    private/  synth/  db/
```

---

## 3. Commands (`Makefile`)

| Command | Does |
|---|---|
| `make setup` | Create the virtual environment, install backend and frontend dependencies, run `probation db init` |
| `make check` | `ruff check`, `ruff format --check`, `mypy`, `pytest -q` (**must pass before any phase is "done"**) |
| `make test` | `pytest -q` with coverage report |
| `make synth PERSONA=1 SEED=1` | Generate one synthetic persona into `data/synth/1` |
| `make backtest FAMILY=email_action` | Run the replay for one family |
| `make serve` | API on port 8000 |
| `make web` | Frontend dev server |
| `make eval SUITE=main` | Run an evaluation suite (`EVALUATION_PLAN.md`) |
| `make ledger-verify` | Verify the hash chain |
| `make budget` | Show estimated LLM spend |

---

## 4. Environment template

### 4.1 `.env.example`

```bash
# --- LLM (Nebius Token Factory, OpenAI-compatible) ---
LLM_BASE_URL=https://api.tokenfactory.nebius.com/v1     # confirm in the Nebius docs
LLM_API_KEY=                                            # never commit
MODEL_READER=                                           # copy the Nemotron Nano model name from the console
MODEL_WRITER=                                           # Nemotron Super
MODEL_EXAM_EDITS=                                       # Nano or Super for development and the main evaluation; Ultra only for final demo runs
MODEL_SYNTH=                                            # Nano or Super
LLM_MAX_CONCURRENCY=8
LLM_TIMEOUT_S=60
LLM_MAX_RETRIES=3
BUDGET_HARD_LIMIT_USD=20
PRICE_TABLE_PATH=config/prices.json

# --- Storage ---
DB_PATH=data/db/probation.db
WORLD_DB_PATH=data/synth/world.db

# --- Runtime ---
CLOCK_MODE=replay                                        # replay | live
USER_ADDRESSES=meena@example.test
USER_TZ=Asia/Kolkata
EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2       # check fastembed support

# --- Web grounding (Tavily) ---
TAVILY_API_KEY=                                          # never commit
TAVILY_BASE_URL=https://api.tavily.com
TAVILY_MAX_CALLS_PER_DAY=100
TAVILY_MONTHLY_CREDIT_BUDGET=800
USER_NAME_TOKENS=                                        # the user's own name parts, blocked from queries

# --- Files pack ---
FILES_WATCH_DIRS=data/synth/1/fs/Downloads,data/synth/1/fs/Desktop
FILES_ALLOWED_ROOTS=data/synth/1/fs
FILES_READER_ENABLED=false

# --- Tunables: any name from ENGINE_SPEC section 12 may be overridden here ---
# AUDIT_FRACTION=0.10
# L2_MIN_LB=0.95
```

### 4.2 `config/prices.json` (verify against the Nebius pricing page before relying on it)

```json
{
  "_note": "USD per 1M tokens. Replace keys with the exact model names from the Token Factory console.",
  "REPLACE_WITH_NANO_MODEL_NAME":  {"in": 0.06, "out": 0.24},
  "REPLACE_WITH_SUPER_MODEL_NAME": {"in": 0.30, "out": 0.90},
  "REPLACE_WITH_ULTRA_MODEL_NAME": {"in": 1.00, "out": 3.00}
}
```

### 4.3 `.gitignore` must include
`.env`, `data/`, `*.db`, `node_modules/`, `.venv/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `frontend/dist/`.

---

## 5. Run modes

| Mode | Clock | Data | Used for |
|---|---|---|---|
| **Replay** | Simulated (`CLOCK_MODE=replay`), speed adjustable | Synthetic persona | Backtest, evaluation, the public demo |
| **Live** (stretch) | Real time | Own mailbox, calendar and folders | Our own accounts and the demo video |

Replay is the default. Live code paths must not exist in engine code; only the pack connectors differ (CONTRACT I-17).

---

## 6. Deployment on Nebius

- **Where the code runs:** one small virtual machine on Nebius AI Cloud (check the machine presets in the console). **Where the models run:** Nebius Token Factory (hosted Nemotron).
- `deploy/docker-compose.yml` services: `api` (FastAPI plus the built frontend), `brain`, `resolver`, `examiner`, `executor`, `scheduler`. They share a `data/` volume. Each worker container gets only the environment variables it needs (the Executor alone has write credentials; in replay mode these are for the simulated world).
- If sharing the SQLite file between containers causes locking or corruption problems, switch to one Postgres container and keep the same schema (open question O-5).
- **Public demo:** the replay service runs a fixed synthetic persona with saved LLM answers, so it works even if the LLM endpoint is slow. Put a reverse proxy (for example Caddy) in front for HTTPS. Add per-IP rate limits and the budget kill-switch.
- **Availability:** the hackathon requires the demo to stay available free of charge until judging ends (15 Dec 2026). Keep it replay-only with cached answers and check the VM cost for about 7 weeks (open question O-16).
- **Optional OpenShell lock:** run `brain` and `examiner` inside a sandbox whose policy allows only the LLM host. Time-box to 3 hours on day 1. If it fails, ship without it and state this honestly (open question O-4).

---

## 7. Day-1 spikes (Phase 0)

| Spike | Script | Pass condition |
|---|---|---|
| LLM call | `scripts/spike_llm.py` | One reader-prompt call returns schema-valid JSON; prints model name, tokens, latency and any rate-limit headers; JSON-schema mode result recorded (works or not) |
| Embeddings | `scripts/spike_embed.py` | Embeds 1,000 short texts on CPU; prints time and memory |
| Sandbox | `deploy/openshell/README.md` notes | A program in the sandbox can reach the LLM host and nothing else, or a recorded decision to skip |
| Tavily | `scripts/spike_tavily.py` | One Search and one Extract call succeed; credits used and latency printed; the first functional runtime call (bonus eligibility) is on record |
| Budget | `scripts/verify_budget.py` | Estimated cost of the spike call matches the usage shown in the Nebius console within 20% |

Record all outcomes in `DECISIONS_AND_OPEN_QUESTIONS.md` section 3.

---

## 8. Coding conventions

- Type hints everywhere; `mypy --strict` on `core/` and `engine/`.
- No `datetime.now()` or `time.time()` outside `core/clock.py` (CONTRACT I-9).
- No network calls outside `llm/client.py`, `web/client.py` (Tavily), pack connectors and `workers/executor.py`.
- Pure functions for engine logic (`gate`, `licence`, `evidence`, `drift`); I/O at the edges.
- Randomness only through seeded generators; seeds are parameters.
- Errors: raise typed exceptions (`BudgetExceeded`, `LLMValidationError`, `LedgerCorrupt`); callers handle them by failing closed (CONTRACT I-3).
- Log with structured key-value pairs; never log message bodies or secrets.
- One module, one responsibility; keep files under about 400 lines.
- Commit messages: `phase-N: short description`.
