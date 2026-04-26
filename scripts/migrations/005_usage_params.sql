-- 005_usage_params.sql
-- Adds per-call params digest to usage_events so the weekly digest (W7)
-- can group recent searches by equivalent-query and surface "前回のクエリに
-- 関連する" recommendations without replaying raw q/filter strings.
--
-- Column `params_digest` is a 16-char hex SHA-256 prefix over the canonical
-- JSON (sorted keys, no whitespace) of whitelisted query params; NULL for
-- endpoints that carry PII (me/billing/feedback/subscribers). Written at
-- INSERT time by `api/deps.py::log_usage`. Equivalent queries → identical
-- digest → cheap GROUP BY for the digest cron.
--
-- TTL: inherits from the parent usage_events row (docs/retention_digest.md
-- §3 declares 30 days for search history). No separate cleanup here —
-- whatever retention job trims usage_events covers this column too. When
-- the usage_events TTL cron lands (§5.1), no change needed for digests.
--
-- Idempotent via scripts/migrate.py's duplicate_column_skipping fallback:
-- re-running on a DB that already has the column records the migration id
-- and moves on.

ALTER TABLE usage_events ADD COLUMN params_digest TEXT;

CREATE INDEX IF NOT EXISTS idx_usage_events_key_params
    ON usage_events(key_hash, params_digest, ts);
