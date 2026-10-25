-- D4 connector objects. This script builds the private connector metadata store only.
-- It is never applied to the engine database: imported mail reaches the engine through
-- the existing ingestor path, and CONTRACT.md section 3 role rows stay unchanged.
-- Time columns are plain TEXT; comparisons apply COLLATE UTC_TIMESTAMP from the store.
CREATE TABLE IF NOT EXISTS gmail_connections(
 connection_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,owner_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN('UNCONFIGURED','AUTHORIZING','AUTHORIZED','BACKFILLING','SHADOW','ACTIVE','PAUSED','DEGRADED','AUTH_REQUIRED','DISCONNECTED')),
 selection_revision INTEGER NOT NULL CHECK(selection_revision>=1),
 label_ids TEXT NOT NULL CHECK(json_valid(label_ids)),credential_ref TEXT NOT NULL,
 granted_scopes TEXT NOT NULL CHECK(json_valid(granted_scopes)),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(account_id,connection_id),CHECK(credential_ref NOT LIKE '%:%//%')
);
CREATE TRIGGER IF NOT EXISTS d4_connection_identity BEFORE UPDATE ON gmail_connections WHEN NEW.connection_id IS NOT OLD.connection_id OR NEW.account_id IS NOT OLD.account_id OR NEW.owner_id IS NOT OLD.owner_id OR NEW.created_at IS NOT OLD.created_at OR NEW.credential_ref IS NOT OLD.credential_ref OR NEW.granted_scopes IS NOT OLD.granted_scopes OR NEW.selection_revision<OLD.selection_revision BEGIN SELECT RAISE(ABORT,'immutable connection identity'); END;
CREATE TRIGGER IF NOT EXISTS d4_connection_no_delete BEFORE DELETE ON gmail_connections BEGIN SELECT RAISE(ABORT,'connection rows are not deleted'); END;
CREATE TABLE IF NOT EXISTS gmail_history_events(
 connection_id TEXT NOT NULL,account_id TEXT NOT NULL,history_id INTEGER NOT NULL,
 native_message_id TEXT NOT NULL,label_id TEXT NOT NULL,
 event_type TEXT NOT NULL CHECK(event_type IN('messageAdded','messageDeleted','labelAdded','labelRemoved')),
 observed_at TEXT NOT NULL,
 PRIMARY KEY(connection_id,history_id,native_message_id,event_type,label_id)
);
CREATE TRIGGER IF NOT EXISTS d4_history_immutable BEFORE UPDATE ON gmail_history_events BEGIN SELECT RAISE(ABORT,'immutable history event'); END;
CREATE TRIGGER IF NOT EXISTS d4_history_no_delete BEFORE DELETE ON gmail_history_events BEGIN SELECT RAISE(ABORT,'immutable history event'); END;
CREATE INDEX IF NOT EXISTS d4_history_message ON gmail_history_events(connection_id,native_message_id,history_id);
CREATE TABLE IF NOT EXISTS gmail_observations(
 connection_id TEXT NOT NULL,account_id TEXT NOT NULL,native_message_id TEXT NOT NULL,
 history_id INTEGER NOT NULL CHECK(history_id>=0),
 event_type TEXT NOT NULL CHECK(event_type IN('message_added','label_added','label_removed','message_deleted','sent_observed')),
 content_hash TEXT NOT NULL,version_hash TEXT NOT NULL,
 observed_at TEXT NOT NULL,occurrence_time TEXT,
 occurrence_provenance TEXT NOT NULL CHECK(occurrence_provenance IN('provider_occurrence','observed_locally','unknown')),
 thread_id TEXT,rfc_message_id TEXT,payload_ref TEXT,label_ids TEXT NOT NULL CHECK(json_valid(label_ids)),
 is_sent INTEGER NOT NULL DEFAULT 0 CHECK(is_sent IN(0,1)),
 PRIMARY KEY(connection_id,native_message_id,history_id,event_type),
 CHECK(event_type='message_deleted' OR payload_ref IS NOT NULL),
 CHECK(event_type<>'message_deleted' OR payload_ref IS NULL)
);
CREATE TRIGGER IF NOT EXISTS d4_observation_immutable BEFORE UPDATE ON gmail_observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
CREATE TRIGGER IF NOT EXISTS d4_observation_no_delete BEFORE DELETE ON gmail_observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
CREATE INDEX IF NOT EXISTS d4_observation_account ON gmail_observations(account_id,native_message_id);
CREATE TABLE IF NOT EXISTS gmail_sync_cursors(
 connection_id TEXT NOT NULL,account_id TEXT NOT NULL,resource_key TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN('read','write')),filter_revision INTEGER NOT NULL CHECK(filter_revision>=1),
 protocol_version TEXT NOT NULL DEFAULT 'gmail-v1',
 committed_history_id INTEGER NOT NULL DEFAULT 0 CHECK(committed_history_id>=0),
 bootstrap_history_id INTEGER CHECK(bootstrap_history_id IS NULL OR bootstrap_history_id>=0),
 watermark_at TEXT,page_token TEXT,
 catchup_complete INTEGER NOT NULL DEFAULT 0 CHECK(catchup_complete IN(0,1)),
 claim_owner TEXT,fence INTEGER NOT NULL DEFAULT 0 CHECK(fence>=0),lease_until TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 PRIMARY KEY(connection_id,resource_key,role,filter_revision)
);
CREATE TRIGGER IF NOT EXISTS d4_cursor_identity BEFORE UPDATE ON gmail_sync_cursors WHEN NEW.connection_id IS NOT OLD.connection_id OR NEW.account_id IS NOT OLD.account_id OR NEW.resource_key IS NOT OLD.resource_key OR NEW.role IS NOT OLD.role OR NEW.filter_revision IS NOT OLD.filter_revision OR NEW.protocol_version IS NOT OLD.protocol_version OR NEW.created_at IS NOT OLD.created_at BEGIN SELECT RAISE(ABORT,'immutable cursor identity'); END;
CREATE TRIGGER IF NOT EXISTS d4_cursor_monotonic BEFORE UPDATE ON gmail_sync_cursors WHEN NEW.committed_history_id<OLD.committed_history_id OR NEW.fence<OLD.fence OR(NEW.catchup_complete=0 AND OLD.catchup_complete=1 AND OLD.committed_history_id>0) BEGIN SELECT RAISE(ABORT,'cursor watermark or fence went backwards'); END;
CREATE TRIGGER IF NOT EXISTS d4_cursor_no_delete BEFORE DELETE ON gmail_sync_cursors BEGIN SELECT RAISE(ABORT,'cursor rows are not deleted'); END;
CREATE TABLE IF NOT EXISTS gmail_capabilities(
 connection_id TEXT NOT NULL,account_id TEXT NOT NULL,
 name TEXT NOT NULL CHECK(name IN('read','archive','trash','send','forward','reconciliation','undo_history_proof','conditional_write','attribution')),
 owner_role TEXT NOT NULL CHECK(owner_role IN('read','write')),
 supported INTEGER NOT NULL CHECK(supported IN(0,1)),
 evidence TEXT NOT NULL CHECK(evidence IN('supported','unsupported','unverified')),
 reason TEXT,manifest_version INTEGER NOT NULL CHECK(manifest_version>=1),
 verified_at TEXT NOT NULL,
 PRIMARY KEY(connection_id,name,owner_role),
 CHECK(supported=0 OR reason IS NULL),CHECK(supported=1 OR reason IS NOT NULL),
 CHECK((owner_role='read' AND name IN('read','attribution')) OR(owner_role='write' AND name IN('archive','trash','send','forward','reconciliation','undo_history_proof','conditional_write')))
);
CREATE TRIGGER IF NOT EXISTS d4_capability_identity BEFORE UPDATE ON gmail_capabilities WHEN NEW.connection_id IS NOT OLD.connection_id OR NEW.account_id IS NOT OLD.account_id OR NEW.name IS NOT OLD.name OR NEW.owner_role IS NOT OLD.owner_role BEGIN SELECT RAISE(ABORT,'immutable capability identity'); END;
CREATE TABLE IF NOT EXISTS gmail_worker_leases(
 connection_id TEXT NOT NULL,job_key TEXT NOT NULL,owner TEXT NOT NULL,
 fence INTEGER NOT NULL CHECK(fence>=1),acquired_at TEXT NOT NULL,expires_at TEXT NOT NULL,
 PRIMARY KEY(connection_id,job_key)
);
CREATE TRIGGER IF NOT EXISTS d4_lease_identity BEFORE UPDATE ON gmail_worker_leases WHEN NEW.connection_id IS NOT OLD.connection_id OR NEW.job_key IS NOT OLD.job_key OR NEW.acquired_at IS NOT OLD.acquired_at BEGIN SELECT RAISE(ABORT,'immutable lease identity'); END;
CREATE TRIGGER IF NOT EXISTS d4_lease_monotonic BEFORE UPDATE ON gmail_worker_leases WHEN NEW.fence<=OLD.fence BEGIN SELECT RAISE(ABORT,'lease fence must advance'); END;
CREATE TABLE IF NOT EXISTS gmail_effect_receipts(
 operation_id TEXT PRIMARY KEY,connection_id TEXT NOT NULL,account_id TEXT NOT NULL,
 action_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('execute','undo')),
 outcome TEXT NOT NULL CHECK(outcome IN('confirmed','failed','unknown')),
 native_ref_hash TEXT,anchor_history_id INTEGER CHECK(anchor_history_id IS NULL OR anchor_history_id>=0),
 payload_hash TEXT NOT NULL,safe_code TEXT,
 verified_no_effect INTEGER NOT NULL DEFAULT 0 CHECK(verified_no_effect IN(0,1)),
 created_at TEXT NOT NULL,
 CHECK(verified_no_effect=0 OR outcome='failed')
);
CREATE TRIGGER IF NOT EXISTS d4_receipt_immutable BEFORE UPDATE ON gmail_effect_receipts BEGIN SELECT RAISE(ABORT,'immutable effect receipt'); END;
CREATE TRIGGER IF NOT EXISTS d4_receipt_no_delete BEFORE DELETE ON gmail_effect_receipts BEGIN SELECT RAISE(ABORT,'immutable effect receipt'); END;
CREATE TABLE IF NOT EXISTS gmail_command_receipts(
 command_id TEXT NOT NULL,consumer TEXT NOT NULL CHECK(consumer='connector'),
 state TEXT NOT NULL CHECK(state IN('applied','failed')),
 connection_id TEXT NOT NULL,applied_state TEXT NOT NULL,safe_code TEXT,
 applied_at TEXT NOT NULL,
 PRIMARY KEY(command_id,consumer)
);
CREATE TRIGGER IF NOT EXISTS d4_command_receipt_immutable BEFORE UPDATE ON gmail_command_receipts BEGIN SELECT RAISE(ABORT,'immutable connector command receipt'); END;
CREATE TRIGGER IF NOT EXISTS d4_command_receipt_no_delete BEFORE DELETE ON gmail_command_receipts BEGIN SELECT RAISE(ABORT,'immutable connector command receipt'); END;
CREATE TABLE IF NOT EXISTS gmail_credential_state(
 credential_ref TEXT PRIMARY KEY,connection_id TEXT NOT NULL,account_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN('read','write')),
 generation INTEGER NOT NULL CHECK(generation>=1),
 granted_scopes TEXT NOT NULL CHECK(json_valid(granted_scopes)),
 access_expires_at TEXT,refresh_updated_at TEXT,rotation_origin TEXT,
 CHECK(credential_ref NOT LIKE '%//%')
);
CREATE TRIGGER IF NOT EXISTS d4_credential_identity BEFORE UPDATE ON gmail_credential_state WHEN NEW.credential_ref IS NOT OLD.credential_ref OR NEW.connection_id IS NOT OLD.connection_id OR NEW.account_id IS NOT OLD.account_id OR NEW.role IS NOT OLD.role BEGIN SELECT RAISE(ABORT,'immutable credential identity'); END;
CREATE TRIGGER IF NOT EXISTS d4_credential_generation BEFORE UPDATE ON gmail_credential_state WHEN NEW.generation<OLD.generation BEGIN SELECT RAISE(ABORT,'stale credential generation'); END;
