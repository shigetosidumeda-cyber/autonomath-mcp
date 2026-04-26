-- Postmark webhook event dedup
-- audit: a9fd80e134b538a32 (2026-04-25)

CREATE TABLE IF NOT EXISTS postmark_webhook_events (
  message_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,  -- bounce, spam_complaint, etc.
  received_at TEXT NOT NULL,
  processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_postmark_webhook_received
  ON postmark_webhook_events(received_at);
