-- D3 additive objects. Columns are added by migrate_lifecycle before this script.
CREATE UNIQUE INDEX IF NOT EXISTS d3_response_key ON user_responses(owner_id,request_key) WHERE schema_version=2;
CREATE UNIQUE INDEX IF NOT EXISTS d3_initial_response ON user_responses(proposal_id) WHERE schema_version=2 AND response IN ('accept','reject','edit');
CREATE TRIGGER IF NOT EXISTS d3_responses_immutable_update BEFORE UPDATE ON user_responses BEGIN SELECT RAISE(ABORT,'immutable response'); END;
CREATE TRIGGER IF NOT EXISTS d3_responses_immutable_delete BEFORE DELETE ON user_responses BEGIN SELECT RAISE(ABORT,'immutable response'); END;
CREATE TRIGGER IF NOT EXISTS d3_responses_valid BEFORE INSERT ON user_responses WHEN NEW.schema_version=2 BEGIN
 SELECT CASE WHEN NEW.owner_id IS NULL OR NEW.owner_id='' OR NEW.request_key IS NULL OR NEW.request_key='' OR NEW.reviewed_payload_json IS NULL OR NEW.reviewed_payload_hash IS NULL OR NEW.intent_hash IS NULL THEN RAISE(ABORT,'incomplete response') END;
 SELECT CASE WHEN (NEW.response='undo') != (NEW.action_id IS NOT NULL) THEN RAISE(ABORT,'invalid undo reference') END;
 SELECT CASE WHEN NEW.action_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM actions WHERE id=NEW.action_id AND proposal_id=NEW.proposal_id) THEN RAISE(ABORT,'wrong action reference') END;
END;
CREATE TABLE IF NOT EXISTS command_requests(
 id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL CHECK(schema_version IN(1,2)),owner_id TEXT NOT NULL,
 request_key TEXT NOT NULL,type TEXT NOT NULL CHECK((schema_version=1 AND type IN('pause','resume','revoke')) OR (schema_version=2 AND type IN('replay_start','replay_pause','replay_speed'))),
 scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(owner_id,request_key)
);
CREATE TRIGGER IF NOT EXISTS d3_commands_immutable_update BEFORE UPDATE ON command_requests BEGIN SELECT RAISE(ABORT,'immutable command'); END;
CREATE TRIGGER IF NOT EXISTS d3_commands_immutable_delete BEFORE DELETE ON command_requests BEGIN SELECT RAISE(ABORT,'immutable command'); END;
CREATE TABLE IF NOT EXISTS command_receipts(
 id TEXT PRIMARY KEY,response_id TEXT REFERENCES user_responses(id),command_id TEXT REFERENCES command_requests(id),
 consumer TEXT NOT NULL CHECK(consumer IN('resolver','executor','examiner')),
 state TEXT NOT NULL CHECK(state IN('pending','claimed','succeeded','failed')),
 claim_owner TEXT,fence INTEGER NOT NULL DEFAULT 0 CHECK(fence>=0),lease_until TEXT,
 result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),safe_code TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 CHECK((response_id IS NOT NULL)+(command_id IS NOT NULL)=1),
 CHECK((command_id IS NOT NULL AND consumer='examiner') OR(response_id IS NOT NULL AND consumer IN('resolver','executor')))
);
CREATE UNIQUE INDEX IF NOT EXISTS d3_response_consumer ON command_receipts(response_id,consumer) WHERE response_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS d3_command_consumer ON command_receipts(command_id,consumer) WHERE command_id IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS d3_receipts_no_delete BEFORE DELETE ON command_receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
CREATE TRIGGER IF NOT EXISTS d3_receipts_identity BEFORE UPDATE ON command_receipts WHEN NEW.id IS NOT OLD.id OR NEW.response_id IS NOT OLD.response_id OR NEW.command_id IS NOT OLD.command_id OR NEW.consumer IS NOT OLD.consumer OR NEW.created_at IS NOT OLD.created_at OR OLD.state IN('succeeded','failed') OR NEW.fence<OLD.fence BEGIN SELECT RAISE(ABORT,'immutable receipt identity or result'); END;
CREATE TABLE IF NOT EXISTS outcome_events(
 id TEXT PRIMARY KEY,situation_id TEXT NOT NULL REFERENCES situations(id),proposal_id TEXT NOT NULL REFERENCES proposals(id),
 response_id TEXT REFERENCES user_responses(id),action_id TEXT REFERENCES actions(id),
 kind TEXT NOT NULL CHECK(kind IN('decision','footprint','override','undo','cancel')),
 source TEXT NOT NULL CHECK(source IN('user_response','footprint','window_close','override','undo')),
 actor TEXT NOT NULL CHECK(actor IN('human','system')),writer_role TEXT NOT NULL CHECK(writer_role IN('resolver','executor')),
 decision TEXT CHECK(decision IS NULL OR decision IN('accept','reject','edit')),observed_action TEXT,
 strength TEXT NOT NULL CHECK(strength IN('STRONG','WEAK')),observed_at TEXT NOT NULL,known_at TEXT NOT NULL,
 source_key TEXT NOT NULL,correction_of TEXT REFERENCES outcome_events(id),
 details_json TEXT NOT NULL CHECK(json_valid(details_json)),event_json TEXT NOT NULL CHECK(json_valid(event_json)),
 ledger_seq INTEGER NOT NULL UNIQUE REFERENCES ledger(seq),UNIQUE(source,source_key),
 CHECK((writer_role='resolver' AND kind IN('decision','footprint','override')) OR(writer_role='executor' AND kind IN('undo','cancel'))),
 CHECK(decision IS NOT 'reject' OR observed_action IS NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS d3_event_response ON outcome_events(response_id) WHERE kind='decision';
CREATE UNIQUE INDEX IF NOT EXISTS d3_event_correction ON outcome_events(action_id,kind) WHERE kind IN('undo','cancel');
CREATE TRIGGER IF NOT EXISTS d3_events_no_update BEFORE UPDATE ON outcome_events BEGIN SELECT RAISE(ABORT,'immutable outcome event'); END;
CREATE TRIGGER IF NOT EXISTS d3_events_no_delete BEFORE DELETE ON outcome_events BEGIN SELECT RAISE(ABORT,'immutable outcome event'); END;
CREATE TABLE IF NOT EXISTS execution_attempts(
 id TEXT PRIMARY KEY,action_id TEXT NOT NULL REFERENCES actions(id),operation TEXT NOT NULL CHECK(operation IN('execute','undo')),
 binding_hash TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('prepared','dispatched','unknown','confirmed','failed')),
 claim_owner TEXT NOT NULL,fence INTEGER NOT NULL CHECK(fence>=1),lease_until TEXT NOT NULL,
 before_json TEXT NOT NULL CHECK(json_valid(before_json)),result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
 safe_code TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(action_id,operation)
);
CREATE TRIGGER IF NOT EXISTS d3_attempts_no_delete BEFORE DELETE ON execution_attempts BEGIN SELECT RAISE(ABORT,'immutable attempt'); END;
CREATE TRIGGER IF NOT EXISTS d3_attempts_identity BEFORE UPDATE ON execution_attempts WHEN NEW.id IS NOT OLD.id OR NEW.action_id IS NOT OLD.action_id OR NEW.operation IS NOT OLD.operation OR NEW.binding_hash IS NOT OLD.binding_hash OR NEW.before_json IS NOT OLD.before_json OR NEW.created_at IS NOT OLD.created_at OR NEW.fence<OLD.fence OR OLD.state IN('confirmed','failed') OR (OLD.state IN('dispatched','unknown') AND NEW.state='prepared') OR (OLD.state='unknown' AND NEW.state='dispatched') BEGIN SELECT RAISE(ABORT,'immutable attempt identity or stage'); END;
CREATE UNIQUE INDEX IF NOT EXISTS d3_action_approval ON actions(approval_response_id) WHERE approval_response_id IS NOT NULL;
CREATE TRIGGER IF NOT EXISTS d3_action_binding BEFORE UPDATE ON actions WHEN OLD.binding_hash IS NOT NULL AND(NEW.binding_hash IS NOT OLD.binding_hash OR NEW.binding_json IS NOT OLD.binding_json OR NEW.authority_kind IS NOT OLD.authority_kind OR NEW.approval_response_id IS NOT OLD.approval_response_id OR NEW.proposal_id IS NOT OLD.proposal_id OR NEW.type IS NOT OLD.type OR NEW.pack IS NOT OLD.pack OR NEW.params_json IS NOT OLD.params_json OR NEW.level_required IS NOT OLD.level_required OR NEW.recallable IS NOT OLD.recallable OR NEW.created_at IS NOT OLD.created_at OR (OLD.status IN('UNDONE','CANCELLED','FAILED') AND NEW.status IS NOT OLD.status) OR(OLD.status='DONE' AND NEW.status NOT IN('DONE','UNDONE'))) BEGIN SELECT RAISE(ABORT,'immutable action binding or terminal'); END;
