-- 003_feedback.sql
-- Developer feedback capture (POST /v1/feedback).
-- Lets devs flag weird responses or name suggestions without opening GitHub.
-- Idempotent when applied via scripts/migrate.py (tracked in schema_migrations).

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT,
    customer_id TEXT,
    tier TEXT,
    message TEXT NOT NULL,
    rating INTEGER,
    endpoint TEXT,
    request_id TEXT,
    ip_hash TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_key_hash ON feedback(key_hash);
CREATE INDEX IF NOT EXISTS idx_feedback_ip_hash ON feedback(ip_hash);
