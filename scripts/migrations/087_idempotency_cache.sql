-- target_db: jpintel
-- migration 087_idempotency_cache (anti-runaway 三点セット — Idempotency-Key 24h replay cache + spike-guard column)
--
-- Why this exists:
--   The Idempotency-Key middleware (`api/middleware/idempotency.py`) caches
--   the response body of a successful POST request keyed on
--   sha256(api_key_hash || endpoint || body || idempotency_key) so a duplicate
--   submission within 24h replays the cached response with
--   X-Idempotency-Replayed: true and is NOT metered (¥0). This is what makes
--   agent-loop bulk operations safe — a Claude / ChatGPT agent that retries a
--   batch_get_programs call after a transient network blip cannot accidentally
--   double-bill the customer.
--
--   This migration also wires the customer-controlled `spike_threshold_factor`
--   onto api_keys for the SpikeGuardMiddleware (anti-runaway 三点セット D).
--
-- Storage shape:
--   * Table `am_idempotency_cache(cache_key, response_blob, expires_at)`.
--     The cache_key embeds api_key_hash so cross-customer collision is
--     cryptographically impossible. Anonymous keys never get cached because
--     anon tier is non-billable (replay protection adds no value).
--   * api_keys.spike_threshold_factor — INTEGER, NULL/0 = disabled.
--     Customer sets via POST /v1/me/spike_guard. When set to N>0 the
--     SpikeGuardMiddleware compares current-hour usage against trailing 24h
--     average; when current_hour > N * trailing_avg, returns 503 + Retry-After.
--
-- Eviction:
--   Lazy on read (middleware checks expires_at on lookup) plus a daily cron
--   sweep `scripts/cron/idempotency_cache_sweep.py` that DELETEs rows where
--   expires_at < datetime('now'). Without the sweep the table grows unbounded
--   at ~tens of KB per cached POST.
--
-- Idempotency: ALTER TABLE ADD COLUMN is a no-op on the second run because
--   `scripts/migrate.py` swallows `duplicate column` OperationalError and
--   records the migration as applied. CREATE TABLE IF NOT EXISTS handles the
--   am_idempotency_cache side. Re-applying this migration is safe.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_idempotency_cache (
    -- sha256 hex digest (64 chars) over the request fingerprint:
    --   sha256(api_key_hash || ':' || endpoint || ':' || body || ':' || key)
    -- Where:
    --   api_key_hash = HMAC(api_key_salt, raw_key) hex (matches deps.hash_api_key)
    --   endpoint     = request.url.path (e.g. /v1/programs/batch)
    --   body         = raw request body bytes (POST only)
    --   key          = client-supplied Idempotency-Key header value
    cache_key       TEXT PRIMARY KEY,
    -- Cached HTTP response: JSON {"status": int, "headers": {...}, "body_b64": "..."}
    -- with the body base64-encoded so binary responses (rare but possible)
    -- survive round-trip. Headers are filtered to drop hop-by-hop ones
    -- (set-cookie / authorization / x-request-id) before serialising.
    response_blob   TEXT NOT NULL,
    -- ISO-8601 UTC string. expires_at = created_at + 24h. Lazily checked on
    -- lookup; daily cron sweeps anything older.
    expires_at      TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Eviction sweep hot path (daily cron WHERE expires_at < ?).
CREATE INDEX IF NOT EXISTS idx_am_idempotency_expires
    ON am_idempotency_cache(expires_at);

-- Spike-guard opt-in column on api_keys (anti-runaway 三点セット D).
-- INTEGER, NULL/0 = disabled. Customer sets via POST /v1/me/spike_guard.
ALTER TABLE api_keys ADD COLUMN spike_threshold_factor INTEGER;

-- Bookkeeping recorded by scripts/migrate.py.
