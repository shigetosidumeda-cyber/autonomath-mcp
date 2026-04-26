-- migration 052: api_keys.stripe_subscription_status durable cache
--
-- Background (P0 dashboard dunning banner):
--   The static dashboard at site/dashboard.html shows a dunning banner when
--   the customer's Stripe subscription is past_due / unpaid / canceled. The
--   banner reads from /v1/me.subscription_status, but until now /v1/me did
--   not surface Stripe state at all — it returned only tier + customer_id.
--
-- Why a durable column (option a) over an in-memory TTL cache (option b):
--   * /v1/me is hit on every dashboard load + every webhook-bound poll. A
--     live Stripe.Subscription.retrieve per request would burn the
--     ~100 req/sec rate limit during a dunning incident (when banners
--     trigger fan-out).
--   * Webhooks already deliver the canonical state transitions
--     (subscription.updated / payment_failed / paid). Persisting the last
--     observed status is just write-through cache with hard durability.
--   * Survives process restart — an in-memory cache cold-starts to "no
--     status" until the next webhook, which can leave the banner missing
--     for hours after a deploy.
--
-- Schema:
--   stripe_subscription_status TEXT
--     One of: 'active' | 'trialing' | 'past_due' | 'canceled' | 'unpaid'
--             | 'incomplete' | 'incomplete_expired'
--     NULL on legacy rows + on free/anonymous keys (which have no
--     subscription); the API surface translates NULL to 'no_subscription'.
--   stripe_subscription_status_at INTEGER
--     Unix epoch seconds of the last write. Lets us reason about staleness
--     when triaging — if a row is days old we can compare against
--     `subscription.current_period_end` to decide if a forced refresh is
--     warranted. NULL until first webhook update.
--   stripe_subscription_current_period_end INTEGER
--     Unix epoch seconds of `subscription.current_period_end` from Stripe.
--     Surfaced as ISO 8601 by /v1/me; the column stays as INTEGER so we
--     can do efficient WHERE comparisons in admin tooling.
--   stripe_subscription_cancel_at_period_end INTEGER
--     0 / 1 boolean. 1 means the customer (or operator) scheduled a
--     cancellation at period end; the subscription is still 'active' until
--     that moment, but the dashboard should advise the customer.
--
-- Idempotency:
--   ALTER TABLE ADD COLUMN is a no-op the second time around (the migrate
--   runner records the duplicate-column error and proceeds). Re-applying
--   this migration is safe.
--
-- DOWN (commented — SQLite does not support ALTER TABLE DROP COLUMN until
-- 3.35; reversing requires a table rebuild. Leaving the columns in place
-- on rollback is harmless because they are nullable and unindexed):
--
--   -- Manual reversal (only if absolutely necessary):
--   -- CREATE TABLE api_keys_v2 AS SELECT
--   --     key_hash, customer_id, tier, stripe_subscription_id, created_at,
--   --     revoked_at, last_used_at, monthly_cap_yen
--   --   FROM api_keys;
--   -- DROP TABLE api_keys;
--   -- ALTER TABLE api_keys_v2 RENAME TO api_keys;
--   -- CREATE INDEX idx_api_keys_customer ON api_keys(customer_id);
--   -- CREATE INDEX idx_api_keys_tier ON api_keys(tier);

PRAGMA foreign_keys = ON;

ALTER TABLE api_keys ADD COLUMN stripe_subscription_status TEXT;
ALTER TABLE api_keys ADD COLUMN stripe_subscription_status_at INTEGER;
ALTER TABLE api_keys ADD COLUMN stripe_subscription_current_period_end INTEGER;
ALTER TABLE api_keys ADD COLUMN stripe_subscription_cancel_at_period_end INTEGER;

-- Composite index for admin "show me everyone in dunning" queries.
-- Partial index to keep the on-disk footprint trivial — most rows have
-- status='active' and don't need to be indexed.
CREATE INDEX IF NOT EXISTS idx_api_keys_subscription_status
    ON api_keys(stripe_subscription_status)
    WHERE stripe_subscription_status IS NOT NULL
      AND stripe_subscription_status != 'active';

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
