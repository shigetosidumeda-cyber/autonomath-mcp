-- migration 053: stripe_webhook_events event-level idempotency dedup table
--
-- Background (P0 webhook robustness):
--   Stripe retries each webhook delivery up to 3 days. The dispatcher in
--   `api/billing.py::webhook` already has subscription-level idempotency
--   (api_keys.stripe_subscription_id UNIQUE), but the secondary side-effect
--   paths (welcome email, _refresh_subscription_status_from_stripe,
--   update_subscription_status, ...) can ALL fire twice on a retry of the
--   same event. That has manifested as duplicate D+0 welcome emails + a
--   spurious extra Stripe.Subscription.retrieve call per replay.
--
--   The fix is event-level dedup: store every event["id"] we see in this
--   table and short-circuit if the row already exists. Stripe guarantees
--   unique event ids globally (across livemode and testmode), so a
--   straight PRIMARY KEY uniqueness check is enough.
--
-- Idempotency:
--   IF NOT EXISTS on both the table and the index, so re-applying this
--   migration is a no-op. Required since `scripts/migrate.py` records the
--   applied id in schema_migrations and the runner short-circuits on
--   re-application — but defensive IF NOT EXISTS still matters when this
--   schema is loaded into a fresh test DB via init_db() (which executes
--   schema.sql, not migrations).
--
-- DOWN (commented — keep the dedup history on rollback; the table is
-- append-only and small):
--   -- DROP INDEX IF EXISTS ix_stripe_webhook_events_received_at;
--   -- DROP TABLE IF EXISTS stripe_webhook_events;

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    livemode INTEGER NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_stripe_webhook_events_received_at
    ON stripe_webhook_events(received_at DESC);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
