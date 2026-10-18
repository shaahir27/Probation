# SCAFFOLD.md — Probation Canonical Project Structure

This document is the **strict, authoritative directory and file layout** for the entire Probation codebase.
Every file and folder listed here has a defined purpose, owner phase, strict interface boundary, and spec reference.

**NO UNWANTED FILES:**
Do not add files, packages, databases, brokers, or helper modules outside this specification unless explicitly approved via a Contract Change Request (CCR).
- **No external message brokers** (no Redis, Celery, RabbitMQ, Kafka).
- **No external vector databases** (no Pinecone, Chroma, Qdrant, Milvus). Embeddings run locally via ONNX on CPU.
- **No heavy ML runtime dependencies** (no PyTorch, CUDA, torchvision).
- **No screen, click, or keystroke loggers** (explicitly refused per CONTRACT section 14).
- **No dropped packs** (GitHub notifications pack is dropped per D-18; Slack, Discord, invoice auditor are rejected).
- **No unapproved LLM providers** (no OpenRouter, Ollama, Anthropic API, or free tiers; Nebius Token Factory only).
- **No web scraping outside Tavily** (no BeautifulSoup or Selenium browsing; only Tavily Search & Extract via quarantined extractors).

---

## 1. Master Repository Tree

```text
probation/
│
├── AGENTS.md                                 # Standing rules for coding agents (repo root)
├── LICENSE                                   # Open-source license (MIT or Apache-2.0, chosen Phase 0)
├── README.md                                 # Architecture diagram, pitch, setup, results summary
├── Makefile                                  # Canonical entry commands (make setup, check, test, synth, backtest, etc.)
├── .env.example                              # Environment variable template with documentation
├── .gitignore                                # Git ignore rules (locks out .env, data/, *.db, caches)
│
├── docs/                                     # System documentation suite (Highest authority: CONTRACT.md)
│   ├── README.md                             # Reading order, conflict resolution, doc index
│   ├── CONTRACT.md                           # Invariants I-1 to I-26, process roles, core interfaces
│   ├── DATA_MODEL.md                         # SQLite DDL schema, deterministic IDs, ledger hashing
│   ├── ENGINE_SPEC.md                        # Mathematical formulas, policy, gate, CUSUM, exam board
│   ├── PACKS_SPEC.md                         # Pack adapter contracts (mail, calendar, files, chains)
│   ├── PROMPTS.md                            # Prompts, schemas, redaction, draft validators
│   ├── TAVILY_AND_NEW_PACKS.md               # Tavily EFS, quarantine, Radar, Reading, CCR-1
│   ├── IMPLEMENTATION_PLAN.md                # Phases 0 to 12 timeline, lane allocations, slip rules
│   ├── TEST_PLAN.md                          # Test catalog T-ID to T-EVAL, golden benchmark numbers
│   ├── EVALUATION_PLAN.md                    # 20 personas, metrics, baselines B0-B3, ablations
│   ├── SECURITY_PRIVACY.md                   # Threat model T1-T18, trust boundaries, public hardening
│   ├── TECH_STACK_AND_REPO.md                # Technology choices, package inventory, day-1 spikes
│   ├── USER_FLOW.md                          # User journeys F1-F14, plain-language microcopy, UI states
│   ├── FRONTEND_IMPLEMENTATION_PLAN.md     # Phase 9 design brief: navigation, UX, accessibility, and score scope
│   ├── AGENT_PLAYBOOK.md                     # Agent loop, lane rules, kickoff prompts, review checklist
│   ├── DECISIONS_AND_OPEN_QUESTIONS.md       # Decision log (D-01 to D-18), day-1 checklist (O-1 to O-18)
│   ├── DEMO_AND_SUBMISSION.md                # 3-minute video storyboard, 5 demo beats, Devpost checklist
│   ├── SCAFFOLD.md                           # Authoritative project structure blueprint (this file)
│   ├── BUILD_LOGGING_PROTOCOL.md             # Rules governing local build_history logging and feature maps
│   ├── templates/
│   │   └── log_schema.md                     # Feature log template (functions, roles, callers, tests)
│   └── agent-kit/
│       └── workflows/
│           ├── run-phase.md                  # Antigravity workflow: /run-phase N
│           └── verify-phase.md               # Antigravity workflow: /verify-phase N
│
├── build_history/                            # GITIGNORED: Local construction logs & feature map (NEVER pushed)
│   ├── index.md                              # Master index mapping every feature, phase, status, and log file
│   ├── phase_00_foundations_spikes/          # Feature logs (feature_[name].md) & phase_00_summary.md
│   └── phase_01_core_ledger_llm/             # (Subdirectories for all phases 00 to 12)
│
├── config/                                   # Shipped static configuration files
│   ├── brands.json                           # ~150 verified brand-to-official-domain mappings for local EFS pre-check
│   └── prices.json                           # Model pricing table (USD per 1M tokens) for budget tracker
│
├── data/                                     # GITIGNORED: local database and execution state
│   ├── db/                                   # Engine databases (probation.db in SQLite WAL mode)
│   ├── synth/                                # Generated synthetic persona data (.mbox, .ics, fs/, world.db)
│   └── private/                              # Real Takeout / personal files for local testing (NEVER committed)
│
├── deploy/                                   # Deployment, VM setup, and sandboxing
│   ├── docker-compose.yml                    # Multi-worker container definition sharing data volume
│   ├── Dockerfile.backend                    # Minimal Python 3.11+ container for backend workers
│   ├── Dockerfile.frontend                   # Static build / Nginx container for React dashboard
│   ├── vm-setup.sh                           # Nebius AI Cloud Ubuntu VM bootstrap script
│   └── openshell/
│       └── README.md                         # NVIDIA OpenShell network egress sandbox policy & spike notes
│
├── scripts/                                  # Day-1 spikes and administrative CLI helpers
│   ├── spike_llm.py                          # Phase 0 spike: Nebius Token Factory JSON-schema & latency check
│   ├── spike_embed.py                        # Phase 0 spike: CPU fastembed / sentence-transformers benchmark
│   ├── spike_tavily.py                       # Phase 0 spike: Runtime Tavily Search & Extract bonus eligibility check
│   ├── verify_budget.py                      # Phase 0 spike: Estimated spend vs Nebius console discrepancy check
│   └── snapshot_folder.py                    # Files pack helper: generates JSON manifest of folder snapshot
│
├── backend/                                  # Python 3.11+ Backend application
│   ├── pyproject.toml                        # Build configuration, pinned dependencies, ruff & mypy settings
│   │
│   ├── src/
│   │   └── probation/                        # Root Python package
│   │       ├── __init__.py                   # Package exports & version (__version__ = "0.1.0")
│   │       ├── config.py                     # Central configuration & tunables (ENGINE_SPEC section 12 defaults)
│   │       ├── cli.py                        # Typer CLI entrypoint (`probation db`, `synth`, `backtest`, `serve`)
│   │       │
│   │       ├── core/                         # Core domain primitives, clocks, types, hashing
│   │       │   ├── __init__.py
│   │       │   ├── types.py                  # Pydantic v2 domain models (Situation, Features, Proposal, Outcome, Action, LicenceView)
│   │       │   ├── enums.py                  # Enums (Gate, ActionStatus, Strength, ItemKind, PackName, FamilyName)
│   │       │   ├── clock.py                  # Clock protocol, Monotonic ReplayClock & LiveClock (CONTRACT I-9)
│   │       │   ├── hashing.py                # Deterministic IDs (det_id), canonical JSON, ledger SHA-256
│   │       │   └── history.py                # HistoryView(as_of) interface enforcing walk-forward "no peeking" (CONTRACT I-6)
│   │       │
│   │       ├── db/                           # SQLite database connection, access helpers, and ledger
│   │       │   ├── __init__.py
│   │       │   ├── schema.sql                # SQLite DDL schema verbatim from DATA_MODEL.md section 1
│   │       │   ├── connection.py             # SQLite connection factory (WAL mode, PRAGMA foreign_keys = ON)
│   │       │   ├── access.py                 # Role-specific DB connection wrappers enforcing CONTRACT section 3
│   │       │   └── ledger.py                 # Append-only hash-chained ledger engine (append, verify, triggers)
│   │       │
│   │       ├── llm/                          # LLM integration, redaction, cache, budget guard
│   │       │   ├── __init__.py
│   │       │   ├── client.py                 # LLMClient (OpenAI SDK to Nebius, retries, backoff, JSON fallback)
│   │       │   ├── cache.py                  # Deterministic LLM response cache (sha256 content/prompt/model)
│   │       │   ├── budget.py                 # Hard budget enforcement guard raising BudgetExceeded (CONTRACT I-15)
│   │       │   ├── redact.py                 # PII redaction engine (Email, Phone, UPI, Aadhaar, PAN, Cards, URLs, Names)
│   │       │   ├── prompts/                  # Versioned prompt templates with YAML frontmatter
│   │       │   │   ├── reader.mail.v2.md     # Mail reader prompt (Nemotron Nano)
│   │       │   │   ├── reader.invite.v1.md   # Invite reader prompt (Nemotron Nano)
│   │       │   │   ├── reader.file.v1.md     # Optional file reader prompt (Nemotron Nano)
│   │       │   │   ├── reader.opportunity.v1.md # Radar opportunity mail reader (Nemotron Nano)
│   │       │   │   ├── writer.reply.v1.md    # Persona style reply writer (Nemotron Super)
│   │       │   │   ├── wording.v1.md         # Habit & chain humanizer prompt (Nemotron Super)
│   │       │   │   ├── exam.paraphrase.v1.md # Exam invariance paraphrase edit (Nemotron Nano/Super/Ultra)
│   │       │   │   ├── exam.add_money_request.v1.md # Exam directional money insertion
│   │       │   │   ├── exam.add_personal_info_request.v1.md # Exam directional PII insertion
│   │       │   │   ├── extract.opportunity.v1.md # Quarantined opportunity page extractor
│   │       │   │   ├── extract.link.v1.md    # Quarantined saved link extractor
│   │       │   │   ├── radar.digest.v1.md    # Radar weekly digest writer (Nemotron Super)
│   │       │   │   ├── synth.mail_body.v1.md # Synthetic email generator (Nemotron Nano/Super)
│   │       │   │   └── synth.invite.v1.md    # Synthetic invite generator (Nemotron Nano/Super)
│   │       │   └── schemas/                  # Strict JSON schemas matching each prompt output
│   │       │       ├── reader_mail.json
│   │       │       ├── reader_invite.json
│   │       │       ├── reader_file.json
│   │       │       ├── reader_opportunity.json
│   │       │       ├── writer_reply.json
│   │       │       ├── wording.json
│   │       │       ├── exam_edit.json
│   │       │       ├── extract_opportunity.json
│   │       │       ├── extract_link.json
│   │       │       └── radar_digest.json
│   │       │
│   │       ├── web/                          # Tavily Web Grounding & Entity Facts Service (CCR-1)
│   │       │   ├── __init__.py               # NOTE: Forbidden from being imported by policy, evidence, or licence code
│   │       │   ├── client.py                 # Tavily HTTP client (Search and Extract, rate limiting, credit ledger)
│   │       │   ├── query_guard.py            # Code guard: checks length, characters, strips PII from Tavily queries (CONTRACT I-23)
│   │       │   ├── derive.py                 # Deterministic EntityFacts derivation from search results (lookalike, confirmed)
│   │       │   └── view.py                   # WebFactsView returning RestrictionOnly types (web_cap, citations)
│   │       │
│   │       ├── links/                        # URL sanitisation and quarantine extraction substrate
│   │       │   ├── __init__.py
│   │       │   ├── sanitise.py               # URL sanitisation: strips tracking, blocks private tokens, auth, IP hosts
│   │       │   └── extract.py                # Wrapper for Tavily Extract on user-saved & Search-discovered URLs (CONTRACT I-24)
│   │       │
│   │       ├── packs/                        # Domain packs implementing the PackAdapter protocol
│   │       │   ├── __init__.py
│   │       │   ├── base.py                   # PackAdapter protocol definition (iter_situations, clues, execute, undo, window)
│   │       │   ├── registry.py               # Central pack registry and pack lookup
│   │       │   ├── mail/                     # Email Pack (`email_action`)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── clues.py              # Sender tiering, reply rates, thread features via HistoryView
│   │       │   │   ├── resolver.py           # Outcome detection (REPLY, FORWARD, ARCHIVE, TRASH, LEAVE)
│   │       │   │   ├── executor.py           # Side-effects (ARCHIVE, TRASH, REPLY draft send, undo)
│   │       │   │   ├── exam_ops.py           # Exam operators (paraphrase, sender_unknown, typos, footer, money)
│   │       │   │   └── importer.py           # MBOX parser to raw_items and situations
│   │       │   ├── calendar/                 # Calendar Pack (`invite_rsvp`)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── clues.py              # Organizer tiering, conflicts, time buckets, lead days
│   │       │   │   ├── resolver.py           # Outcome detection (ACCEPT, DECLINE, TENTATIVE, NO_RESPONSE)
│   │       │   │   ├── executor.py           # RSVP send (held 10 min), BLOCK_TIME private creation, undo
│   │       │   │   ├── exam_ops.py           # Exam operators (conflict, unusual_hour, unknown_organizer, fee)
│   │       │   │   └── importer.py           # ICS parser to raw_items and situations
│   │       │   ├── files/                    # Files & Downloads Pack (`file_destination`)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── clues.py              # Origin domain, extension group, size buckets, top folder share
│   │       │   │   ├── resolver.py           # Outcome detection (MOVE_TO_FOLDER, LEAVE, DELETE)
│   │       │   │   ├── executor.py           # shutil.move, path collision handling, undo restoration
│   │       │   │   ├── exam_ops.py           # Exam operators (executable_extension, double_extension, origin_unknown)
│   │       │   │   └── importer.py           # Folder snapshot JSON manifest parser
│   │       │   ├── chains/                   # Cross-pack Follow-up Chains Pack (`chain_followup`)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── mining.py             # Cross-tool pattern mining (lift, support, Fisher exact test)
│   │       │   │   ├── proposer.py           # Generates chain situation proposals from trigger events
│   │       │   │   └── executor.py           # Follow-up execution (BLOCK_TIME, CREATE_TASK, REPLY draft)
│   │       │   ├── radar/                    # Opportunity Radar Pack (`opportunity_triage`)
│   │       │   │   ├── __init__.py
│   │       │   │   ├── clues.py              # Opportunity clues (platform type, deadline bucket, tracked share)
│   │       │   │   ├── resolver.py           # Outcome detection (TRACK, DISMISS, LEAVE)
│   │       │   │   ├── executor.py           # Tracker entry creation in SimWorld, undo deletion
│   │       │   │   ├── exam_ops.py           # Exam operators (page_injection, add_fee_request, lookalike_domain)
│   │       │   │   └── importer.py           # Opportunity mail / user-pasted link intake
│   │       │   └── reading/                  # Reading Triage Pack (`link_triage`)
│   │       │       ├── __init__.py
│   │       │       ├── clues.py              # Domain, path type, content type, length bucket, topic
│   │       │       ├── resolver.py           # Outcome detection (FILE_TO_COLLECTION, ARCHIVE_LINK, LEAVE)
│   │       │       ├── executor.py           # Collection assignment in SimWorld library, undo restoration
│   │       │       ├── exam_ops.py           # Exam operators (private_token_in_url, lookalike_domain, page_injection)
│   │       │       └── importer.py           # Saved bookmarks / link list intake
│   │       │
│   │       ├── engine/                       # Core mathematical engine & decision logic (pure functions)
│   │       │   ├── __init__.py
│   │       │   ├── replay.py                 # Event-sourced replay loop (OUTCOME_KNOWN, LICENCE_REVIEW, RETRAIN, SITUATION)
│   │       │   ├── features.py               # Deterministic + Reader feature fusion, one-hot encoding, feature hashing
│   │       │   ├── policy.py                 # Multinomial logistic regression, recency decay weighting, temperature scaling
│   │       │   ├── novelty.py                # Embedding distance novelty detector (k-NN distance vs training quantile)
│   │       │   ├── evidence.py               # Evidence aggregator, Beta posterior lower bound, clipped hierarchical pooling
│   │       │   ├── licence.py                # Runtime licence derivation (levels 0-3), cache TTL, exam & drift validity
│   │       │   ├── caps.py                   # Hard-coded base caps, conditional caps (unknown sender, fee, personal info)
│   │       │   ├── handsoff.py               # Hard-coded hands-off checks (executable files, double exts, RTL overrides)
│   │       │   ├── gate.py                   # Pure gate decision function (economic test, audit draw, recallable routing)
│   │       │   ├── drift.py                  # CUSUM mistake tracking per (c, a) and PSI weekly family shift detector
│   │       │   ├── habits.py                 # Habit pattern mining, Fisher exact test, Benjamini-Hochberg FDR correction
│   │       │   ├── exam.py                   # Trick-question exam runner, sampling, case evaluation, code verdicts
│   │       │   └── report.py                 # Report card generator (same, different, would_ask)
│   │       │
│   │       ├── workers/                      # Background asynchronous workers & execution boundaries
│   │       │   ├── __init__.py
│   │       │   ├── ingestor.py               # Ingests source items into raw_items and initial situations
│   │       │   ├── brain.py                  # Featurizes, scores policy, checks novelty, preview gate, writes drafts & proposals
│   │       │   ├── resolver.py               # Scans world footprints, detects user actions, commits outcomes
│   │       │   ├── examiner.py               # Nightly licence reviews, drift/PSI alarms, exam scheduling, mining
│   │       │   ├── executor.py               # Only process with write credentials: acts on PENDING/HELD actions, performs undos
│   │       │   ├── scheduler.py              # Replay/live timeline driver for review and retrain ticks
│   │       │   └── webfacts.py               # Background Tavily entity vetter: writes web_facts & tavily_calls
│   │       │
│   │       ├── api/                          # FastAPI REST API (CONTRACT section 9)
│   │       │   ├── __init__.py
│   │       │   ├── app.py                    # FastAPI application initialization, CORS, exception handlers
│   │       │   └── routes/                   # Endpoint routers
│   │       │       ├── __init__.py
│   │       │       ├── health.py             # GET /api/health
│   │       │       ├── report_card.py        # GET /api/report-card
│   │       │       ├── licences.py           # GET /api/licences
│   │       │       ├── queue.py              # GET /api/queue, POST /api/queue/{proposal_id}/respond
│   │       │       ├── items.py              # GET /api/items/{proposal_id}
│   │       │       ├── actions.py            # GET /api/actions, POST /api/actions/{id}/undo
│   │       │       ├── habits.py             # GET /api/habits, POST /api/habits/{id}/deny
│   │       │       ├── chains.py             # GET /api/chains
│   │       │       ├── exams.py              # GET /api/exams, POST /api/exams/run
│   │       │       ├── web_facts.py          # GET /api/web-facts (transparency: exact Tavily queries & credits)
│   │       │       ├── boards.py             # GET /api/boards/{pack} (radar board, reading library)
│   │       │       ├── metrics.py            # GET /api/metrics/summary
│   │       │       ├── settings.py           # GET /api/settings (read-only system tunables & caps)
│   │       │       ├── exposure.py           # GET /api/exposure (PII redaction and token egress counts)
│   │       │       ├── ledger.py             # GET /api/ledger/verify
│   │       │       └── replay.py             # GET /api/replay/state, POST /api/replay/{start|pause|speed}
│   │       │
│   │       ├── synth/                        # Synthetic persona world generation engine
│   │       │   ├── __init__.py
│   │       │   ├── personas.py           # Loads personas (Nemotron-Personas-India or 5 fallback student personas)
│   │       │   ├── habits_dsl.py         # Habit rule DSL parser, rule evaluation engine, noise generator
│   │       │   ├── generator.py          # 180-day timeline generator with planted drift and hidden truth
│   │       │   ├── render.py             # Renders .mbox, .ics, folder snapshots, and directory tree
│   │       │   └── world.py              # SimWorld: SQLite world.db simulating mailbox, calendar, filesystem, tasks
│   │       │
│   │       └── eval/                         # Evaluation, metrics, baselines, and human study
│   │           ├── __init__.py
│   │           ├── baselines.py          # Baselines B0 (majority), B1 (ask-always), B2 (generic), B3 (LLM-confidence)
│   │           ├── metrics.py            # Metric calculation (agreement, precision, ECE, CUSUM delay, attention units)
│   │           ├── run_eval.py           # Main evaluation runner over 20 personas (15 dev, 5 test)
│   │           └── human_study.py        # Harness for 150-item human study data collection
│   │
│   └── tests/                                # Test suite (strict test-first discipline)
│       ├── __init__.py
│       ├── conftest.py                       # Pytest fixtures (seeded RNG, fake LLM, clock, test DB)
│       │
│       ├── unit/                             # Fast unit tests (< 5 seconds total)
│       │   ├── test_clock.py                 # T-CLOCK: monotonic clock, no system time calls
│       │   ├── test_hashing.py               # T-ID: deterministic sha256 IDs, canonical JSON
│       │   ├── test_ledger.py                # T-LEDGER: hash chaining, genesis, triggers block UPDATE/DELETE
│       │   ├── test_redact.py                # T-REDACT: PII pattern masking, restore map isolation
│       │   ├── test_llm_client.py            # T-LLM: fake server, retries, backoff, schema fallback, cache
│       │   ├── test_budget.py                # T-LLM: budget guard raises BudgetExceeded before limit
│       │   ├── test_security_imports.py      # T-SEC: static import boundary audit (brain has no exec credentials)
│       │   ├── test_lower_bound.py           # T-LB: golden numbers (58 for LB>=0.95, 148 for LB>=0.98)
│       │   ├── test_policy.py                # T-POLICY: multinomial logreg, cold start, recency weights, calibration
│       │   ├── test_novelty.py               # T-NOVELTY: cosine distance against training set quantile
│       │   ├── test_evidence.py              # T-EVIDENCE: auto-executed excluded from Beta, audit holdout included
│       │   ├── test_caps.py                  # T-CAPS: base caps, conditional caps min-combination, recallable levels
│       │   ├── test_handsoff.py              # T-HANDSOFF: blocked file extensions, double extensions, RTL override
│       │   ├── test_gate.py                  # T-GATE: golden table-driven gate decisions
│       │   ├── test_drift_cusum.py           # T-CUSUM: mistake accumulation, 2-undo rule, alarm demotion
│       │   ├── test_drift_psi.py             # T-PSI: population stability index on shifted feature distributions
│       │   ├── test_habits.py                # T-HABIT: pattern discovery, BH correction, wording validator
│       │   ├── test_chains.py                # T-CHAIN: cross-tool mining, weak vs strong evidence rules
│       │   ├── test_web_query_guard.py       # T-WEBQ: character, token, length, and PII guard on Tavily queries
│       │   ├── test_web_isolation.py         # T-WEBISO: policy/licence do not import web/; web_cap can only lower autonomy
│       │   ├── test_web_vetting.py           # T-VET: EntityFacts derivation on fixtures (lookalikes, homoglyphs)
│       │   ├── test_quarantine.py            # T-QUAR: prompt injection in scraped web pages leaves decisions unchanged
│       │   ├── test_link_sanitise.py         # T-LINK: URL sanitiser, token stripping, sensitive path block
│       │   └── test_eval_metrics.py          # T-EVAL: metric functions match hand-computed values to 1e-9
│       │
│       ├── property/                         # Hypothesis / property tests
│       │   ├── test_no_peeking.py            # T-NOPEEK: mutating future data (known_at > t) leaves proposals at t identical
│       │   └── test_ledger_immutability.py   # Tampering with any historical ledger payload breaks verify()
│       │
│       ├── integration/                      # Component integration tests
│       │   ├── test_pack_conformance.py      # T-PACK: 7 conformance checks across all registered packs
│       │   ├── test_outcome_resolution.py    # T-RESOLVE: outcome resolution across crafted fixture states
│       │   ├── test_executor_lifecycle.py    # T-EXEC: action execution, hold queues, idempotency, undos
│       │   ├── test_exam_board.py            # T-EXAM: sound policy passes; cheating policy fixture fails
│       │   ├── test_api_endpoints.py         # T-API: FastAPI endpoint contracts, response shapes, errors
│       │   ├── test_synth_generator.py       # T-SYNTH: generator determinism, habit adherence, truth isolation
│       │   └── test_e2e_backtest.py          # T-E2E: import -> backtest -> licences -> exam on tiny_synth
│       │
│       └── fixtures/                         # Static test fixtures (committed, synthetic only)
│           ├── tiny_synth/                   # ~200 situation synthetic test persona
│           ├── sim_world/                    # Seeded test mailbox, calendar, and directory tree
│           └── tavily/                       # Recorded offline Tavily API responses for test replay
│
└── frontend/                                 # React + Vite + TypeScript Dashboard
    ├── package.json                          # Frontend dependencies (React, Lucide, Tailwind, TanStack Query, Recharts)
    ├── vite.config.ts                        # Vite configuration with proxy to FastAPI :8000
    ├── tailwind.config.ts                    # Design system tokens (curated color palette, dark mode)
    ├── tsconfig.json                         # Strict TypeScript configuration
    ├── index.html                            # HTML5 root with semantic metadata & modern Google Fonts
    │
    └── src/
        ├── main.tsx                          # App bootstrapping with QueryClientProvider
        ├── App.tsx                           # Main router & layout shell
        ├── index.css                         # Core CSS design system, CSS variables, typography
        │
        ├── types/                            # TypeScript interfaces matching backend models
        │   ├── api.ts                        # API response types (ReportCard, Queue, Licences, Actions, etc.)
        │   └── domain.ts                     # UI domain types (AutonomyLevel, TaskDigest, Evidence)
        │
        ├── api/                              # HTTP API client
        │   └── client.ts                     # Typed fetch client communicating with /api
        │
        ├── components/                       # Focused, reusable UI components
        │   ├── common/
        │   │   ├── Header.tsx                # App header with connection badge & mode indicator
        │   │   ├── Sidebar.tsx               # Desktop nav: Home, Queue, Actions, Permissions, More; secondary routes grouped under More
        │   │   ├── Button.tsx                # Styled button with loading and active states
        │   │   ├── Badge.tsx                 # Status and level badges (Watching, Suggests, Does with undo)
        │   │   ├── Card.tsx                  # Restrained solid-surface card using FRONTEND_IMPLEMENTATION_PLAN.md tokens
        │   │   ├── Modal.tsx                 # Accessible modal dialog
        │   │   ├── LoadingSkeleton.tsx       # Shimmer loading skeleton
        │   │   ├── ErrorBanner.tsx           # Inline and toast error alerts with retry
        │   │   └── ReplayControls.tsx        # Persistent replay bar (play, pause, speed: 1x, 10x, 100x)
        │   │
        │   └── dashboard/
        │       ├── EvidenceLine.tsx          # "Matched you 148 of 148 times (safe estimate 98%)"
        │       ├── DigestGroup.tsx           # Grouped queue items ("7 recruiter mails: polite no for 5")
        │       ├── DraftEditor.tsx           # In-line editable reply draft with style facts
        │       ├── SimilarCases.tsx          # Three most similar historical cases
        │       ├── WebFactBadge.tsx          # "Matches official site" or "Check sender" with source citations
        │       └── UndoToast.tsx             # Floating undo notification with countdown timer
        │
        └── pages/                            # Route views; group navigation per FRONTEND_IMPLEMENTATION_PLAN.md and use USER_FLOW.md section 4 for screen content
            ├── Home.tsx                      # System status, pending queue count, habit change alerts
            ├── ReportCard.tsx                # Task/action-scoped history when API supports it; family summary labeled as family
            ├── Queue.tsx                     # Review queue (Needs you, Ready for you, one-tap accept/reject/edit)
            ├── ItemDetail.tsx                # Deep explanation: why, similar cases, evidence line, web facts
            ├── Actions.tsx                   # Executed and held actions with 7-day Undo & 10-min Cancel buttons
            ├── Licences.tsx                  # Licences ladder (Watch, Suggest, Do with undo, Do silently) + evidence
            ├── Habits.tsx                    # Mined habits with humanized wording & deny capability
            ├── Chains.tsx                    # Discovered multi-step chains across packs
            ├── Exams.tsx                     # Trick-question exam board results & flipped counterfactual cases
            ├── Metrics.tsx                   # Scoped operational trends and drift alarms; no overall accuracy score
            ├── Exposure.tsx                  # Data privacy counter: characters scrubbed, tokens egressed
            ├── Ledger.tsx                    # Append-only activity record with tamper verification badge
            ├── Settings.tsx                  # Read-only tunables, hard-coded caps, and hands-off lists
            ├── RadarBoard.tsx                # More destination only when Radar pack/API are active
            ├── ReadingLibrary.tsx            # Deferred while Reading is cut from v1
            └── ImportHelp.tsx                # Instructions for importing Takeout/folder snapshots
```

---

## 2. Directory Allocation by Build Lane & Phase

| Directory Path | Build Lane | Primary Phase | Primary Specs |
|---|---|---|---|
| `docs/` | Planning | Phase 0 | `README.md`, `CONTRACT.md` |
| `config/` | Lane A & B | Phase 0, 6b | `TECH_STACK_AND_REPO.md`, `TAVILY_AND_NEW_PACKS.md` |
| `scripts/` | Lane A & B | Phase 0 | `TECH_STACK_AND_REPO.md` |
| `backend/src/probation/core/` | Lane A (Engine) | Phase 1 | `CONTRACT.md`, `DATA_MODEL.md` |
| `backend/src/probation/db/` | Lane A (Engine) | Phase 1 | `DATA_MODEL.md`, `CONTRACT.md` |
| `backend/src/probation/llm/` | Lane A (Engine) | Phase 1 | `PROMPTS.md`, `CONTRACT.md` |
| `backend/src/probation/synth/` | Lane B (Data) | Phase 2 | `EVALUATION_PLAN.md`, `PACKS_SPEC.md` |
| `backend/src/probation/packs/mail/` | Lane A (Engine) | Phase 3 | `PACKS_SPEC.md` section 1 |
| `backend/src/probation/packs/calendar/` | Lane A (Engine) | Phase 3 | `PACKS_SPEC.md` section 2 |
| `backend/src/probation/engine/` (core) | Lane A (Engine) | Phase 4 | `ENGINE_SPEC.md` sections 1–5 |
| `backend/src/probation/engine/` (gate/licence) | Lane A (Engine) | Phase 5 | `ENGINE_SPEC.md` sections 6–11 |
| `backend/src/probation/packs/files/` | Lane B (Data) | Phase 6 | `PACKS_SPEC.md` section 3 |
| `backend/src/probation/web/` | Lane B (Data) | Phase 6b | `TAVILY_AND_NEW_PACKS.md`, `CONTRACT.md` CCR-1 |
| `backend/src/probation/engine/exam.py` | Lane A (Engine) | Phase 7 | `ENGINE_SPEC.md` section 15 |
| `backend/src/probation/packs/chains/` | Lane A (Engine) | Phase 8 | `PACKS_SPEC.md` section 4 |
| `backend/src/probation/links/` | Lane B (Data) | Phase 8b | `TAVILY_AND_NEW_PACKS.md` section 7 |
| `backend/src/probation/packs/radar/` | Lane B (Data) | Phase 8b | `TAVILY_AND_NEW_PACKS.md` section 8 |
| `backend/src/probation/packs/reading/` | Lane B (Data) | Phase 8b | `TAVILY_AND_NEW_PACKS.md` section 9 |
| `backend/src/probation/api/` & `frontend/` | Lane C (UI) | Phase 9 | `CONTRACT.md` section 9, `USER_FLOW.md`, `FRONTEND_IMPLEMENTATION_PLAN.md` |
| `backend/src/probation/eval/` | Lane D (Eval) | Phase 10 | `EVALUATION_PLAN.md` |
| `deploy/` | Lane D (Deploy) | Phase 11 | `TECH_STACK_AND_REPO.md` section 6 |

---

## 3. Strict Boundary Invariants

1. **Isolation of Policy & Evidence from Web**:
   - Files in `engine/policy.py`, `engine/evidence.py`, `engine/licence.py`, and `engine/features.py` **MUST NEVER** import from `web/`.
   - Web facts are restriction-only and accessed only via `web/view.py` (`WebFactsView`).
2. **Isolation of Brain from Side-Effects**:
   - Files in `workers/brain.py` and `workers/examiner.py` **MUST NEVER** import `workers/executor.py` or hold write credentials.
3. **Isolation of Truth from Engine**:
   - Files in `engine/`, `packs/`, and `workers/` **MUST NEVER** read `truth.json` or `data/private/`.
4. **Time Mediation**:
   - No Python file outside `core/clock.py` may call `datetime.now()` or `time.time()`.
5. **Ledger Immutability**:
   - `db/ledger.py` only executes `INSERT` queries on the `ledger` table. Database triggers abort any `UPDATE` or `DELETE`.
