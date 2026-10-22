# DATA_MODEL

SQLite (WAL mode), one database file per user. Authority: below `CONTRACT.md`.

Conventions:
- IDs are `TEXT`. Deterministic IDs are the first 32 hex chars of `sha256(...)` (see section 2).
- Timestamps are `TEXT` in ISO-8601 UTC with a trailing `Z` (`2026-03-14T09:30:00Z`).
- Booleans are `INTEGER` 0/1.
- JSON columns are `TEXT` with `CHECK (json_valid(col))`.
- Foreign keys ON. All writes go through the per-process helpers in `db/access.py` (CONTRACT section 3).

---

## 1. Schema (DDL)

```sql
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
CREATE INDEX idx_raw_items_pack_time ON raw_items(pack, occurred_at);
CREATE INDEX idx_raw_items_known ON raw_items(known_at);

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
CREATE INDEX idx_situations_family_time ON situations(family, occurred_at);

CREATE TABLE features (
  situation_id TEXT PRIMARY KEY REFERENCES situations(id),
  deterministic_json TEXT NOT NULL CHECK (json_valid(deterministic_json)),
  reader_json TEXT CHECK (reader_json IS NULL OR json_valid(reader_json)),
  reader_ok INTEGER NOT NULL CHECK (reader_ok IN (0,1)),
  featurizer_version TEXT NOT NULL,
  model_id TEXT,
  prompt_version TEXT,
  features_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
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
CREATE INDEX idx_proposals_class ON proposals(class_key, action, proposed_at);

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
CREATE INDEX idx_outcomes_known ON outcomes(known_at);

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
CREATE INDEX idx_actions_status ON actions(status, hold_until);

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
```

---

## 2. Deterministic IDs

```python
def det_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]

situation_id = det_id(pack, source_ref, occurred_at, family, variant)
raw_item_id  = det_id(source_id, source_ref)
action_id    = det_id(proposal_id, action_type, json_canonical(params))
```

Using deterministic IDs makes ingestion and replay idempotent.

---

## 3. Timestamps and "known_at"

- WP1 representation: new context-clock timestamps use UTC `Z`, retaining six
  fractional digits when microseconds are nonzero and the legacy whole-second form
  otherwise. Inputs with more than six fractional digits are rejected rather than
  truncated. Existing payload strings and ledger hashes are not rewritten.
- Compare instants, not ISO spelling. `core/clock.py` parses offsets and legacy naive
  UTC strings; connection/bootstrap helpers register `UTC_TIMESTAMP` collation.
  Repaired SQL cutoffs/orderings use that collation, including aggregate time heads.
  A raw SQLite connection must be configured before using these queries.
- A same-instant event does not satisfy strict I-7. Precision preserves real ordering;
  it does not authorize manufacturing a later footprint timestamp. Response/outcome
  event ownership and the complete replay event chronology remain separately gated.
- `occurred_at`: when the thing happened (mail received, invite sent, file created).
- `known_at` (raw items): when the system could first know the record. Usually equal to `occurred_at`.
- `known_at` (outcomes): when the outcome could first be observed. For a reply it is the reply's send time. For a window-close weak outcome it is `occurred_at + window`.
- Replay mode replays events in order of `max(occurred_at, known_at)`; see `ENGINE_SPEC.md` section 1.

---

## 4. Ledger hash chain

```python
GENESIS = "0" * 64

def canonical_json(obj) -> str:
    # sorted keys, no spaces, UTF-8, floats rounded to 6 decimals,
    # datetimes as ISO-8601 UTC 'Z' strings
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def ledger_hash(prev_hash: str, kind: str, ref_id: str, payload: dict) -> str:
    material = "\n".join([prev_hash, kind, ref_id, canonical_json(payload)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
```

- `append(kind, ref_id, payload)` runs inside one transaction: read the last row's `hash` (or `GENESIS`), compute, insert.
- `verify()` recomputes the whole chain and returns the first broken `seq` or `ok`.
- **Payloads contain ids, decisions and numbers, never message text.**

Ledger payload shapes:

| kind | payload |
|---|---|
| `proposal` | `{situation_id, class_key, action, p_max, gate, licence_level, policy_version, features_hash, audit_holdout}` |
| `outcome` | `{situation_id, observed_action, strength, source, known_at}` |
| `action` | `{action_id, type, status, level_required}` |
| `user_response` | `{proposal_id, action_id, response, edited_action}` |
| `licence_change` | `{class_key, action, old_level, new_level, lower_bound, reasons}` |
| `exam_run` | `{exam_run_id, class_key, action, level_tested, passed}` |
| `drift_alarm` | `{class_key, action, cusum, kind}` |
| `audit_draw` | `{situation_id, draw, fraction, selected}` |

---

## 5. Retention and privacy

- `redacted_text` holds only what is allowed to leave the machine. Raw bodies stay in `raw_items.payload_json` and never go to an LLM.
- Real exports live under `data/private/` (gitignored). Synthetic data lives under `data/synth/`.
- A `probation db purge --before DATE` command may delete `raw_items`, `situations` text and `drafts`, but never the ledger.
- `drafts.body_text` contains restored personal names and is class B data (`SECURITY_PRIVACY.md` section 4). So is `extractions.content_text`, because it reveals what the user saved.
