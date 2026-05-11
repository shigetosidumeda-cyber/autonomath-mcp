-- target_db: autonomath
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS stripe_event_idempotency (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT,
    processing_outcome TEXT CHECK (processing_outcome IN ('success','retry','permanent_failure','duplicate_skipped','unknown')),
    error_message TEXT,
    api_key_id_minted TEXT,
    stripe_customer_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_stripe_event_type ON stripe_event_idempotency(event_type, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_stripe_event_customer ON stripe_event_idempotency(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stripe_event_outcome ON stripe_event_idempotency(processing_outcome, processed_at DESC);
