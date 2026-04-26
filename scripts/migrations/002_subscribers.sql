-- 002_subscribers.sql
-- Newsletter/launch-updates email capture.
-- Idempotent when applied via scripts/migrate.py (tracked in schema_migrations).

CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    source TEXT,
    created_at TEXT NOT NULL,
    unsubscribed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_subscribers_email ON subscribers(email);
CREATE INDEX IF NOT EXISTS idx_subscribers_created_at ON subscribers(created_at);
