-- 007_anon_rate_limit.sql
-- Per-IP MONTHLY quota for anonymous (no X-API-Key) callers.
--
-- Why a separate table (not usage_events): usage_events is keyed on key_hash
-- and would need NOT NULL relaxation + a FK bypass to accept anon rows. A
-- standalone table keeps anon accounting fully detached from user accounting
-- and makes retention cleanup trivial (DELETE WHERE date < ...).
--
-- IP storage: never raw. Written as HMAC-SHA256(ip, api_key_salt) hex digest
-- by api/anon_limit.py. Matches the same salt strategy used by api_keys and
-- feedback.ip_hash so an operator with DB access cannot back-derive an IP.
--
-- Bucketing: 2026-04-23 switched from daily → monthly (50 req/month per IP).
-- Column name `date` is retained for schema stability; now stores YYYY-MM-01
-- (first-of-month JST) instead of YYYY-MM-DD. One UPSERT per call, zero scan.
-- SQLite `date()` comparisons still work on a YYYY-MM-01 value.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS — safe to re-run via
-- scripts/migrate.py.
--
-- NO foreign key to any other table — anon IPs must stay decoupled from
-- users; coupling them would let an operator pivot from an IP hash to a
-- customer via JOIN.

CREATE TABLE IF NOT EXISTS anon_rate_limit (
    ip_hash TEXT NOT NULL,
    date TEXT NOT NULL,          -- YYYY-MM-01 in JST (first of month, bucket key)
    call_count INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (ip_hash, date)
);

CREATE INDEX IF NOT EXISTS idx_anon_date ON anon_rate_limit(date);
