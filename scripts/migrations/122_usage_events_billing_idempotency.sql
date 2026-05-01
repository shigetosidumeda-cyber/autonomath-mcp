-- migration 122_usage_events_billing_idempotency
--
-- Store a stable logical-request key derived from HTTP Idempotency-Key so a
-- retry cannot create multiple local usage rows or multiple Stripe increments
-- if the handler succeeded but idempotency response-cache finalization failed.

ALTER TABLE usage_events ADD COLUMN billing_idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_events_billing_idempotency
    ON usage_events(key_hash, billing_idempotency_key)
    WHERE billing_idempotency_key IS NOT NULL;
