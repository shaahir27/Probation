PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Where data came from
CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  pack TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN
    ('mbox','ics','folder_snapshot','link_list','gmail_live','gcal_live','fs_watch','notion_live','github_live','synthetic')),
  ref TEXT NOT NULL,
  imported_at TEXT NOT NULL
);

-- Normalised raw records (mails, calendar events, file records, sent items)
CREATE TABLE raw_items (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  pack TEXT NOT NULL,
  item_kind TEXT NOT NULL,            -- 'mail_in','mail_sent','invite','cal_event','file','link_saved','gh_notification'
  source_ref TEXT NOT NULL,           -- Message-ID, UID, file path, etc.
  occurred_at TEXT NOT NULL,
  known_at TEXT NOT NULL,             -- when this record became knowable (usually = occurred_at)
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  content_hash TEXT NOT NULL,
  UNIQUE (source_id, source_ref)
);
CREATE INDEX idx_raw_items_pack_time ON raw_items(pack, occurred_at COLLATE UTC_TIMESTAMP);
CREATE INDEX idx_raw_items_known ON raw_items(known_at COLLATE UTC_TIMESTAMP);

-- A thing that arrived and may need a decision
CREATE TABLE situations (
  id TEXT PRIMARY KEY,
  raw_item_id TEXT NOT NULL REFERENCES raw_items(id),
  pack TEXT NOT NULL,
  family TEXT NOT NULL,
  variant TEXT NOT NULL DEFAULT '',   -- chain follow-up action for pack 'chains'; empty otherwise
  occurred_at TEXT NOT NULL,
  sender_key TEXT,                    -- normalised sender / organiser / origin domain
  content_hash TEXT NOT NULL,
  redacted_text TEXT,                 -- what may be sent to an LLM (already redacted)
  hands_off_reason TEXT,              -- non-null means never auto-act
  created_at TEXT NOT NULL,
  UNIQUE (raw_item_id, family, variant)
);
-- Time columns carry COLLATE UTC_TIMESTAMP because HistoryView bounds every read with
-- `occurred_at COLLATE UTC_TIMESTAMP <= ?`. An index built with the default BINARY
-- collation cannot serve that range term: the planner degrades to a single-column seek
-- and then filters, which measured ~6x slower at 200k rows. Keep the collations in sync
-- with core/clock.py::configure_clock_collation, which must be registered on the
-- connection before this script runs.
CREATE INDEX idx_situations_family_time ON situations(family, occurred_at COLLATE UTC_TIMESTAMP);
CREATE INDEX idx_situations_pack_time ON situations(pack, occurred_at COLLATE UTC_TIMESTAMP);
CREATE INDEX idx_situations_sender_time ON situations(sender_key, occurred_at COLLATE UTC_TIMESTAMP);

CREATE TABLE features (
  situation_id TEXT PRIMARY KEY REFERENCES situations(id),
  deterministic_json TEXT NOT NULL CHECK (json_valid(deterministic_json)),
  reader_json TEXT CHECK (reader_json IS NULL OR json_valid(reader_json)),
  reader_ok INTEGER NOT NULL CHECK (reader_ok IN (0,1)),
  featurizer_version TEXT NOT NULL,
  model_id TEXT,
  prompt_version TEXT,
  features_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  provenance_json TEXT CHECK (provenance_json IS NULL OR json_valid(provenance_json))
);

-- Deterministic LLM response cache (CONTRACT I-16)
CREATE TABLE llm_cache (
  cache_key TEXT PRIMARY KEY,         -- sha256(content_hash|prompt_id|prompt_version|model_id)
  kind TEXT NOT NULL,
  model_id TEXT NOT NULL,
  prompt_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  response_json TEXT NOT NULL CHECK (json_valid(response_json)),
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL
);

-- What the system predicted (immutable; one per situation)
CREATE TABLE proposals (
  id TEXT PRIMARY KEY,
  situation_id TEXT NOT NULL UNIQUE REFERENCES situations(id),
  family TEXT NOT NULL,
  class_key TEXT NOT NULL,
  action TEXT NOT NULL,
  probs_json TEXT NOT NULL CHECK (json_valid(probs_json)),
  p_max REAL NOT NULL CHECK (p_max >= 0 AND p_max <= 1),
  novelty REAL NOT NULL,
  novel INTEGER NOT NULL CHECK (novel IN (0,1)),
  licence_level INTEGER NOT NULL CHECK (licence_level BETWEEN 0 AND 3),
  cap INTEGER NOT NULL CHECK (cap BETWEEN 0 AND 3),
  gate TEXT NOT NULL CHECK (gate IN
    ('SHADOW','SUGGEST','ASK','EXECUTE_UNDO','HOLD_THEN_EXECUTE','EXECUTE_SILENT')),
  reasons_json TEXT NOT NULL CHECK (json_valid(reasons_json)),
  params_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(params_json)),            -- action parameters, e.g. a BLOCK_TIME slot
  explanation_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(explanation_json)),  -- top feature contributions, similar past cases
  web_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(web_json)),                  -- {status, cap, source_ids}; restriction-only (CONTRACT I-21)
  policy_version TEXT NOT NULL,
  features_hash TEXT NOT NULL,
  audit_holdout INTEGER NOT NULL DEFAULT 0 CHECK (audit_holdout IN (0,1)),
  proposed_at TEXT NOT NULL,
  ledger_seq INTEGER NOT NULL
);
CREATE INDEX idx_proposals_class ON proposals(class_key, action, proposed_at COLLATE UTC_TIMESTAMP);

-- What the user actually did (written once)
CREATE TABLE outcomes (
  situation_id TEXT PRIMARY KEY REFERENCES situations(id),
  observed_action TEXT NOT NULL,
  strength TEXT NOT NULL CHECK (strength IN ('STRONG','WEAK')),
  source TEXT NOT NULL,               -- 'footprint','user_response','undo','override','window_close'
  observed_at TEXT NOT NULL,
  known_at TEXT NOT NULL,             -- when the system could first know this outcome
  details_json TEXT NOT NULL CHECK (json_valid(details_json)),
  ledger_seq INTEGER NOT NULL
);
CREATE INDEX idx_outcomes_known ON outcomes(known_at COLLATE UTC_TIMESTAMP);

-- Reply drafts written by the brain: final text with placeholders restored locally (class B data)
CREATE TABLE drafts (
  proposal_id TEXT PRIMARY KEY REFERENCES proposals(id),
  body_text TEXT NOT NULL,
  needs_user_input INTEGER NOT NULL CHECK (needs_user_input IN (0,1)),
  validator_ok INTEGER NOT NULL CHECK (validator_ok IN (0,1)),
  model_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Side-effects (Executor only)
CREATE TABLE actions (
  id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES proposals(id),
  pack TEXT NOT NULL,
  type TEXT NOT NULL,
  params_json TEXT NOT NULL CHECK (json_valid(params_json)),
  level_required INTEGER NOT NULL CHECK (level_required BETWEEN 1 AND 3),
  recallable INTEGER NOT NULL CHECK (recallable IN (0,1)),
  status TEXT NOT NULL CHECK (status IN
    ('PENDING','HELD','DONE','UNDONE','CANCELLED','FAILED')),
  hold_until TEXT,
  undo_json TEXT CHECK (undo_json IS NULL OR json_valid(undo_json)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  executed_at TEXT
);
CREATE INDEX idx_actions_status ON actions(status, hold_until COLLATE UTC_TIMESTAMP);

-- Explicit answers from the user (written by the api only). 'undo' asks the Executor to undo an action.
CREATE TABLE user_responses (
  id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES proposals(id),
  action_id TEXT REFERENCES actions(id),            -- set when response = 'undo'
  response TEXT NOT NULL CHECK (response IN ('accept','reject','edit','undo')),
  edited_action TEXT,
  responded_at TEXT NOT NULL
);

-- Evidence summary per (class, action); recomputed, never authoritative (CONTRACT I-10)
CREATE TABLE class_stats (
  class_key TEXT NOT NULL,
  action TEXT NOT NULL,
  as_of TEXT NOT NULL,
  n_strong INTEGER NOT NULL, k_strong INTEGER NOT NULL,
  n_all INTEGER NOT NULL,    k_all INTEGER NOT NULL,
  n_recent INTEGER NOT NULL,
  lb_strong REAL NOT NULL, lb_all REAL NOT NULL,
  PRIMARY KEY (class_key, action, as_of)
);

-- Cache of derived licences (TTL); the Executor re-derives at action time
CREATE TABLE licence_cache (
  class_key TEXT NOT NULL,
  action TEXT NOT NULL,
  level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 3),
  lower_bound REAL NOT NULL,
  reasons_json TEXT NOT NULL CHECK (json_valid(reasons_json)),
  exam_run_id TEXT,
  computed_at TEXT NOT NULL,
  valid_until TEXT NOT NULL,
  PRIMARY KEY (class_key, action)
);

CREATE TABLE exam_runs (
  id TEXT PRIMARY KEY,
  class_key TEXT NOT NULL,
  action TEXT NOT NULL,
  level_tested INTEGER NOT NULL CHECK (level_tested IN (2,3)),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  n_cases INTEGER NOT NULL,
  invariance_flip_rate REAL,
  directional_violations_critical INTEGER,
  directional_violation_rate_other REAL,
  passed INTEGER CHECK (passed IN (0,1)),
  edit_model_id TEXT,
  details_json TEXT NOT NULL CHECK (json_valid(details_json))
);

CREATE TABLE exam_cases (
  id TEXT PRIMARY KEY,
  exam_run_id TEXT NOT NULL REFERENCES exam_runs(id),
  base_situation_id TEXT NOT NULL REFERENCES situations(id),
  operator TEXT NOT NULL,
  expectation TEXT NOT NULL CHECK (expectation IN ('invariant','no_more_autonomous')),
  edit_valid INTEGER NOT NULL CHECK (edit_valid IN (0,1)),
  decision_before TEXT NOT NULL,
  decision_after TEXT,
  violated INTEGER CHECK (violated IN (0,1)),
  critical INTEGER NOT NULL CHECK (critical IN (0,1))
);

CREATE TABLE drift_state (
  class_key TEXT NOT NULL,
  action TEXT NOT NULL,
  cusum REAL NOT NULL DEFAULT 0,
  baseline_err REAL NOT NULL DEFAULT 0.03,
  last_alarm_at TEXT,
  PRIMARY KEY (class_key, action)
);

CREATE TABLE family_shift (
  family TEXT NOT NULL,
  week_start TEXT NOT NULL,
  psi_json TEXT NOT NULL CHECK (json_valid(psi_json)),
  alarm INTEGER NOT NULL CHECK (alarm IN (0,1)),
  PRIMARY KEY (family, week_start)
);

CREATE TABLE habits (
  id TEXT PRIMARY KEY,
  family TEXT NOT NULL,
  clue TEXT NOT NULL,
  clue_value TEXT NOT NULL,
  action TEXT NOT NULL,
  k INTEGER NOT NULL, n INTEGER NOT NULL,
  lift REAL NOT NULL, q_value REAL NOT NULL,
  statement TEXT NOT NULL,            -- reworded by LLM, numbers validated unchanged
  examples_json TEXT NOT NULL CHECK (json_valid(examples_json)),
  status TEXT NOT NULL CHECK (status IN ('active','denied')) DEFAULT 'active',
  created_at TEXT NOT NULL
);

CREATE TABLE chains (
  id TEXT PRIMARY KEY,
  trigger_class_key TEXT NOT NULL,
  follow_action TEXT NOT NULL,
  k INTEGER NOT NULL, n INTEGER NOT NULL,
  base_rate REAL NOT NULL, lift REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','retired')) DEFAULT 'active',
  created_at TEXT NOT NULL,
  UNIQUE (trigger_class_key, follow_action)
);

-- Tamper-evident log (CONTRACT I-8)
CREATE TABLE ledger (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN
    ('proposal','outcome','action','user_response','licence_change',
     'exam_run','drift_alarm','audit_draw')),
  ref_id TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL,
  created_at TEXT NOT NULL            -- from Clock (simulated in replay mode)
);
CREATE TRIGGER ledger_no_update BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER ledger_no_delete BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

CREATE TABLE exposure_log (
  id TEXT PRIMARY KEY,
  situation_id TEXT,
  call_kind TEXT NOT NULL,            -- 'reader','writer','wording','exam_edit','synth'
  model_id TEXT NOT NULL,
  tokens_in INTEGER NOT NULL,
  tokens_out INTEGER NOT NULL,
  redaction_counts_json TEXT NOT NULL CHECK (json_valid(redaction_counts_json)),
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL
);

-- ===== Web grounding (CONTRACT I-21 to I-26) =====
-- Facts about an entity (registrable domain). Restriction-only: never a feature, never evidence.
CREATE TABLE web_facts (
  entity_key TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN
    ('confirmed_official','lookalike','reports_found','no_web_presence','unverified','not_checked')),
  facts_json TEXT NOT NULL CHECK (json_valid(facts_json)),     -- official_candidates, lookalike_of, report_hits, domain_in_results
  sources_json TEXT NOT NULL CHECK (json_valid(sources_json)), -- [{title, url}], at most 5, plain text
  origin TEXT NOT NULL CHECK (origin IN ('local_brand_list','tavily','fixture')),
  present_knowledge INTEGER NOT NULL DEFAULT 0 CHECK (present_knowledge IN (0,1)),  -- 1 = fetched now, applied to replay
  fetched_at TEXT NOT NULL,
  ttl_until TEXT NOT NULL
);

-- Audit of every Tavily call, including the exact query sent
CREATE TABLE tavily_calls (
  id TEXT PRIMARY KEY,
  endpoint TEXT NOT NULL CHECK (endpoint IN ('search','extract')),
  purpose TEXT NOT NULL CHECK (purpose IN ('vet_ident','vet_report','find_official','extract_item')),
  query_text TEXT NOT NULL,            -- search: the query; extract: the sanitised URL
  params_json TEXT NOT NULL CHECK (json_valid(params_json)),
  credits REAL NOT NULL,
  ok INTEGER NOT NULL CHECK (ok IN (0,1)),
  latency_ms INTEGER,
  situation_id TEXT,
  created_at TEXT NOT NULL
);
-- Deliberately BINARY, unlike the time indexes above: web/client.py matches created_at with
-- LIKE to total a day's credits, which a collated index cannot serve, and nothing
-- range-compares this column against a COLLATE UTC_TIMESTAMP bound.
CREATE INDEX idx_tavily_calls_day ON tavily_calls(created_at);

-- Extracted page text for user-saved or officially-discovered URLs (class B data: reveals what the user saved)
CREATE TABLE extractions (
  id TEXT PRIMARY KEY,
  url_norm TEXT NOT NULL,
  extract_depth TEXT NOT NULL,
  query_hash TEXT NOT NULL,
  ok INTEGER NOT NULL CHECK (ok IN (0,1)),
  content_text TEXT,                   -- truncated to EXTRACT_MAX_CHARS
  content_hash TEXT,
  fetched_at TEXT NOT NULL,
  ttl_until TEXT NOT NULL,
  UNIQUE (url_norm, extract_depth, query_hash)
);

-- Typed output of the quarantined extractor, after code validation
CREATE TABLE quarantine_outputs (
  id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extractions(id),
  prompt_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model_id TEXT NOT NULL,
  fields_json TEXT NOT NULL CHECK (json_valid(fields_json)),
  validator_ok INTEGER NOT NULL CHECK (validator_ok IN (0,1)),
  validator_notes_json TEXT NOT NULL CHECK (json_valid(validator_notes_json)),
  created_at TEXT NOT NULL,
  UNIQUE (extraction_id, prompt_id, prompt_version)
);

CREATE TABLE clock_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  mode TEXT NOT NULL CHECK (mode IN ('replay','live')),
  sim_time TEXT,
  speed REAL NOT NULL DEFAULT 1.0,
  running INTEGER NOT NULL DEFAULT 0
);

-- WP4: bounded immutable event projection by subject; no ledger bytes are changed.
CREATE INDEX idx_ledger_kind_time ON ledger(kind, created_at COLLATE UTC_TIMESTAMP);
