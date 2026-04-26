-- migration 071: stripe_edge_cases (refund_requests + stripe_tax_cache)
--
-- target_db: jpintel.db
--
-- Background (P3.5, 2026-04-25):
--   Six Stripe edge cases (refund / dispute / tax-exempt / currency / invoice
--   modification / Stripe Tax fallback) live in
--   `src/jpintel_mcp/billing/stripe_edge_cases.py`. Two of them need durable
--   tables — the rest are stateless audit_log writes:
--
--     1. refund_requests — POST /v1/billing/refund_request intake. Mirrors
--        the §31 / §33 APPI intake pattern: persist + notify + manual review
--        within 14 days. Memory `feedback_autonomath_no_api_use` requires
--        the ¥3/req metering NOT be auto-reversed; this table only records
--        the request, the operator decides on the actual money movement.
--
--     2. stripe_tax_cache — last successful Stripe Tax calculation per
--        customer. Used by `stripe_tax_with_fallback()` to graceful-degrade
--        when Stripe Tax API returns 5xx — falling back to 0% would 消費税法
--        §63 mis-issue an 適格請求書 lacking the per-rate table, so we
--        instead restore the most recent successful rate.
--
-- Idempotency:
--   IF NOT EXISTS on tables + indexes. Safe to re-apply via migrate.py and
--   via init_db() on a fresh test/dev DB (DDL also mirrored at the bottom
--   of src/jpintel_mcp/db/schema.sql).
--
-- DOWN (commented — refund history must be retained for the operator's
-- review SLA + bookkeeping; tax cache rebuilds itself on the next
-- successful Stripe call so it is the only safe drop):
--   -- DROP INDEX IF EXISTS ix_refund_requests_status;
--   -- DROP INDEX IF EXISTS ix_refund_requests_received;
--   -- DROP TABLE IF EXISTS refund_requests;
--   -- DROP TABLE IF EXISTS stripe_tax_cache;

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. refund_requests
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refund_requests (
    request_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    amount_yen INTEGER,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_refund_requests_received
    ON refund_requests(received_at DESC);

CREATE INDEX IF NOT EXISTS ix_refund_requests_status
    ON refund_requests(status);

CREATE INDEX IF NOT EXISTS ix_refund_requests_customer
    ON refund_requests(customer_id);

-- ----------------------------------------------------------------------------
-- 2. stripe_tax_cache (one row per customer, UPSERT-driven)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stripe_tax_cache (
    customer_id TEXT PRIMARY KEY,
    rate_bps INTEGER NOT NULL,            -- basis points; 1000 = 10.00%
    jurisdiction TEXT NOT NULL DEFAULT 'JP',
    tax_amount_yen INTEGER,
    cached_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_stripe_tax_cache_cached_at
    ON stripe_tax_cache(cached_at DESC);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
