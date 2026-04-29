-- target_db: jpintel
-- 079_saved_searches.sql
-- Saved Searches + Daily Alert Digest (W3 retention).
--
-- Business context:
--   * Customers persist a query (q + filters) under a friendly name. A
--     daily/weekly cron diffs the saved query against the corpus and emails
--     a digest of NEW matches landed since `last_run_at`. Detection of "new"
--     piggybacks on `am_amendment_diff` (migration 075) so we surface
--     genuine changes rather than re-emailing every match.
--   * Unlike `alert_subscriptions` (migration 038, FREE) which is structural
--     event fan-out, saved-search digests are a delivery the customer pulled
--     for themselves. Each delivered email is a metered ¥3 charge through
--     `report_usage_async` so the cost stays inside our ¥3/req unit price
--     posture (project_autonomath_business_model).
--   * Solo + zero-touch — no admin review, no allow-list, fully self-serve
--     via POST/GET/DELETE under /v1/me/saved_searches.
--
-- Idempotency:
--   * `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` so this
--     file is safe to re-run via `scripts/migrate.py` or the entrypoint
--     self-heal loop. No DROP / ALTER paths.
--
-- Append + soft-delete contract:
--   * Rows are deleted hard via DELETE /v1/me/saved_searches/{id}; we do not
--     keep audit history here because the saved search itself is just a
--     bookmark. The digest delivery audit lives in `usage_events`
--     (endpoint='saved_searches.digest') as a side effect of metering.
--
-- DOWN:
--   `DROP TABLE saved_searches;` is the rollback. No companion file shipped
--   because the table is < 100 rows at MVP volume and recreating from scratch
--   is cheaper than maintaining a rollback path.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS saved_searches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_hash    TEXT NOT NULL,                         -- api_keys.key_hash (HMAC PRIMARY KEY)
    name            TEXT NOT NULL,                         -- customer-facing label e.g. "東京都の補助金"
    query_json      TEXT NOT NULL,                         -- canonical JSON: {q, prefecture, target_types, funding_purpose, amount_min, amount_max, ...}
    frequency       TEXT NOT NULL DEFAULT 'daily' CHECK (
                        frequency IN ('daily', 'weekly')
                    ),
    notify_email    TEXT NOT NULL,                         -- delivery target; required (no webhook channel for digests)
    last_run_at     TEXT,                                  -- ISO 8601 UTC of last cron processing (NULL until first run)
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Cron's only access pattern: "give me every saved_search whose
-- frequency window has elapsed". Composite (api_key_hash, frequency)
-- covers both the per-customer list query AND the cron sweep filter
-- (the cron `WHERE frequency = ? AND (last_run_at IS NULL OR
-- last_run_at < ?)` clause hits this index for `frequency=` and then
-- range-scans).
CREATE INDEX IF NOT EXISTS idx_saved_searches_key_freq
    ON saved_searches(api_key_hash, frequency);

-- Customer-side list query (`GET /v1/me/saved_searches`) hits this directly.
CREATE INDEX IF NOT EXISTS idx_saved_searches_key
    ON saved_searches(api_key_hash);

-- Bookkeeping recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
