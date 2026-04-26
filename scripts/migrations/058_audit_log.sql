-- Security audit log for forensics
-- 不正アクセス禁止法 incident response baseline
-- audit: a4298e454aab2aa43 (2026-04-25)

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,  -- key_rotate, key_revoke, login, login_failed, billing_portal, cap_change
  key_hash TEXT,             -- old key hash (or current for non-rotation events)
  key_hash_new TEXT,         -- new key hash on rotate (NULL for other events)
  customer_id TEXT,
  ip TEXT,
  user_agent TEXT,
  metadata TEXT              -- JSON for event-specific fields
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_log_key_hash ON audit_log(key_hash);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type, ts DESC);
