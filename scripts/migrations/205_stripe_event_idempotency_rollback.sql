-- target_db: autonomath (rollback)
DROP INDEX IF EXISTS idx_stripe_event_outcome;
DROP INDEX IF EXISTS idx_stripe_event_customer;
DROP INDEX IF EXISTS idx_stripe_event_type;
DROP TABLE IF EXISTS stripe_event_idempotency;
