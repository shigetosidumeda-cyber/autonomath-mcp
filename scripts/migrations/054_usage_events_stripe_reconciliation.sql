-- Stripe usage reconciliation columns
-- Allows replay-from-Stripe if local usage_events are lost (DR scenario)
-- Audit: a37f6226fe319dc40 (2026-04-25)

ALTER TABLE usage_events ADD COLUMN stripe_record_id TEXT;
ALTER TABLE usage_events ADD COLUMN stripe_synced_at TEXT;

CREATE INDEX IF NOT EXISTS idx_usage_events_stripe_sync
  ON usage_events (stripe_synced_at)
  WHERE stripe_synced_at IS NULL;
