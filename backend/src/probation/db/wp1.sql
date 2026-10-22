-- Additive CCR-F intent and Examiner correction-review receipts. No ledger rewrite.
CREATE TABLE IF NOT EXISTS admin_commands (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('deny_habit','run_exam')),
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
  status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SUCCEEDED','FAILED')),
  result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
  requested_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS admin_command_pending BEFORE INSERT ON admin_commands
WHEN NEW.status != 'PENDING' OR NEW.result_json IS NOT NULL OR NEW.updated_at != NEW.requested_at
BEGIN SELECT RAISE(ABORT, 'New commands must be pending'); END;
CREATE TRIGGER IF NOT EXISTS admin_command_immutable BEFORE UPDATE ON admin_commands
WHEN NEW.id != OLD.id OR NEW.kind != OLD.kind OR NEW.payload_json != OLD.payload_json
 OR NEW.requested_at != OLD.requested_at OR OLD.status != 'PENDING'
 OR NEW.status = 'PENDING' OR NEW.result_json IS NULL
BEGIN SELECT RAISE(ABORT, 'Command intent and terminal result are immutable'); END;
CREATE TRIGGER IF NOT EXISTS admin_command_no_delete BEFORE DELETE ON admin_commands
BEGIN SELECT RAISE(ABORT, 'Command history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS admin_command_no_replace BEFORE INSERT ON admin_commands
WHEN EXISTS (SELECT 1 FROM admin_commands WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT, 'Command intent already exists'); END;
CREATE TABLE IF NOT EXISTS drift_receipts (
  event_seq INTEGER PRIMARY KEY REFERENCES ledger(seq),
  class_key TEXT NOT NULL,
  action TEXT NOT NULL,
  known_at TEXT NOT NULL,
  is_correction INTEGER NOT NULL CHECK (is_correction IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_drift_receipts_pair ON drift_receipts(class_key,action,known_at);
CREATE TRIGGER IF NOT EXISTS drift_receipts_no_update BEFORE UPDATE ON drift_receipts
BEGIN SELECT RAISE(ABORT, 'Drift receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS drift_receipts_no_delete BEFORE DELETE ON drift_receipts
BEGIN SELECT RAISE(ABORT, 'Drift receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS drift_receipts_no_replace BEFORE INSERT ON drift_receipts
WHEN EXISTS (SELECT 1 FROM drift_receipts WHERE event_seq=NEW.event_seq)
BEGIN SELECT RAISE(ABORT, 'Drift receipt already exists'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_replace BEFORE INSERT ON ledger
WHEN EXISTS (SELECT 1 FROM ledger WHERE seq=NEW.seq)
BEGIN SELECT RAISE(ABORT, 'Ledger sequence already exists'); END;
