-- Durable spend accounting (W3-D03): budget scope, logical request, physical attempt.
-- Additive and re-runnable. Money is integer units of 1e-8 USD; every total is a derived
-- SUM over attempt rows, never a stored counter a crash could lose or invent.
CREATE TABLE IF NOT EXISTS budget_scopes (
  scope_id       TEXT PRIMARY KEY,
  provider       TEXT NOT NULL,
  account_label  TEXT NOT NULL,
  model_id       TEXT NOT NULL,
  period_rule    TEXT NOT NULL CHECK (period_rule IN ('total','calendar_day','calendar_month')),
  period_key     TEXT NOT NULL,
  cap_units      INTEGER NOT NULL CHECK (cap_units >= 0),
  price_version  TEXT NOT NULL,
  created_at_op  TEXT NOT NULL,
  UNIQUE (provider, account_label, model_id, period_rule, period_key)
);
CREATE TRIGGER IF NOT EXISTS budget_scopes_immutable BEFORE UPDATE ON budget_scopes
BEGIN SELECT RAISE(ABORT, 'budget_scopes rows are immutable'); END;
CREATE TABLE IF NOT EXISTS llm_requests (
  request_id       TEXT PRIMARY KEY,
  scope_id         TEXT NOT NULL REFERENCES budget_scopes(scope_id),
  owner_role       TEXT NOT NULL CHECK (owner_role IN ('brain','examiner','webfacts')),
  semantic_digest  TEXT NOT NULL,
  prompt_id        TEXT NOT NULL,
  prompt_version   TEXT NOT NULL,
  model_id         TEXT NOT NULL,
  cache_key        TEXT NOT NULL,
  situation_id     TEXT,
  result_state     TEXT NOT NULL CHECK (result_state IN
                     ('open','succeeded','failed_closed','unavailable')),
  created_at_op    TEXT NOT NULL,
  settled_at_op    TEXT,
  UNIQUE (scope_id, semantic_digest, prompt_id, prompt_version, model_id, situation_id)
);
CREATE TABLE IF NOT EXISTS llm_attempts (
  attempt_id        TEXT PRIMARY KEY,
  request_id        TEXT NOT NULL REFERENCES llm_requests(request_id),
  scope_id          TEXT NOT NULL REFERENCES budget_scopes(scope_id),
  owner_role        TEXT NOT NULL CHECK (owner_role IN ('brain','examiner','webfacts')),
  ordinal           INTEGER NOT NULL CHECK (ordinal >= 1),
  stage             TEXT NOT NULL CHECK (stage IN
                      ('structured','retry','format_fallback','repair')),
  state             TEXT NOT NULL CHECK (state IN
                      ('reserved','dispatched','reconciled','ambiguous','never_dispatched')),
  estimate_units    INTEGER NOT NULL CHECK (estimate_units >= 0),
  charged_units     INTEGER NOT NULL CHECK (charged_units >= 0),
  tokens_in_bound   INTEGER NOT NULL CHECK (tokens_in_bound >= 0),
  tokens_out_bound  INTEGER NOT NULL CHECK (tokens_out_bound >= 0),
  tokens_in         INTEGER CHECK (tokens_in IS NULL OR tokens_in >= 0),
  tokens_out        INTEGER CHECK (tokens_out IS NULL OR tokens_out >= 0),
  usage_provenance  TEXT NOT NULL CHECK (usage_provenance IN ('none','reported','estimated')),
  denial_code       TEXT CHECK (denial_code IS NULL OR denial_code IN
                      ('price_missing','price_invalid','price_table_missing','price_table_invalid',
                       'usage_invalid','amount_invalid','cost_metadata_invalid','cap_exceeded',
                       'transport','status','validation')),
  lease_owner       TEXT,
  lease_token       INTEGER NOT NULL DEFAULT 0,
  reserved_at_op    TEXT NOT NULL,
  dispatched_at_op  TEXT,
  reconciled_at_op  TEXT
);
CREATE INDEX IF NOT EXISTS llm_attempts_open_by_scope ON llm_attempts(scope_id) WHERE state IN ('reserved','dispatched','ambiguous');
CREATE INDEX IF NOT EXISTS llm_attempts_charged_by_scope ON llm_attempts(scope_id,state) WHERE state = 'reconciled';
CREATE UNIQUE INDEX IF NOT EXISTS llm_attempts_ordinal ON llm_attempts(request_id,ordinal);
-- Forward transitions only: a bound, an ordinal, an identity or a reservation timestamp is
-- history and cannot be rewritten, a charge and a lease token can only grow, and a settled
-- state is terminal. The allowed moves themselves are declared by the typed repository.
CREATE TRIGGER IF NOT EXISTS llm_attempts_no_history_update BEFORE UPDATE ON llm_attempts
WHEN NEW.attempt_id IS NOT OLD.attempt_id OR NEW.request_id IS NOT OLD.request_id
 OR NEW.scope_id IS NOT OLD.scope_id OR NEW.owner_role IS NOT OLD.owner_role
 OR NEW.ordinal IS NOT OLD.ordinal OR NEW.stage IS NOT OLD.stage
 OR NEW.estimate_units IS NOT OLD.estimate_units
 OR NEW.tokens_in_bound IS NOT OLD.tokens_in_bound OR NEW.tokens_out_bound IS NOT OLD.tokens_out_bound
 OR NEW.reserved_at_op IS NOT OLD.reserved_at_op OR NEW.lease_owner IS NOT OLD.lease_owner
 OR NEW.charged_units < OLD.charged_units OR NEW.lease_token < OLD.lease_token
 OR NOT ((OLD.state='reserved' AND NEW.state IN ('dispatched','never_dispatched'))
      OR (OLD.state='dispatched' AND NEW.state IN ('reconciled','ambiguous'))
      OR (OLD.state='ambiguous' AND NEW.state='reconciled'))
BEGIN SELECT RAISE(ABORT, 'llm_attempts rows transition forward only'); END;
CREATE TRIGGER IF NOT EXISTS llm_requests_no_history_update BEFORE UPDATE ON llm_requests
WHEN NEW.request_id IS NOT OLD.request_id OR NEW.scope_id IS NOT OLD.scope_id
 OR NEW.owner_role IS NOT OLD.owner_role OR NEW.semantic_digest IS NOT OLD.semantic_digest
 OR NEW.prompt_id IS NOT OLD.prompt_id OR NEW.prompt_version IS NOT OLD.prompt_version
 OR NEW.model_id IS NOT OLD.model_id OR NEW.cache_key IS NOT OLD.cache_key
 OR NEW.situation_id IS NOT OLD.situation_id OR NEW.created_at_op IS NOT OLD.created_at_op
 OR OLD.result_state != 'open' OR NEW.result_state NOT IN ('succeeded','failed_closed','unavailable')
BEGIN SELECT RAISE(ABORT, 'llm_requests history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS llm_attempts_no_delete BEFORE DELETE ON llm_attempts
BEGIN SELECT RAISE(ABORT, 'llm_attempts rows are the cost audit and are not deletable'); END;
CREATE TRIGGER IF NOT EXISTS llm_requests_no_delete BEFORE DELETE ON llm_requests
BEGIN SELECT RAISE(ABORT, 'llm_requests rows are the request audit and are not deletable'); END;
CREATE UNIQUE INDEX IF NOT EXISTS llm_requests_semantic_identity ON llm_requests(scope_id,semantic_digest,prompt_id,prompt_version,model_id);
