-- 061_telemetry_columns.sql
-- Search-quality regression detection (P0 from audit ada8db68240c63c66).
--
-- Adds two nullable columns to usage_events so we can compute p50/p95/p99
-- latency per endpoint AND detect FTS5 query degradation by tracking
-- result_count over time. Existing rows backfill as NULL — we never
-- retroactively invent latency we did not measure.
--
-- Composite index on (endpoint, created_at) speeds up the per-endpoint
-- 24h aggregation that the operator dashboard runs.
--
-- usage_events.ts is the existing UTC ISO8601 column; we ALSO add
-- created_at as an alias semantic via the index — but to keep schema
-- diffs minimal we index on (endpoint, ts) which is the actual column
-- name. Naming the index idx_usage_events_endpoint_created so the call
-- site in the audit can stay endpoint-agnostic about column names.
--
-- Idempotent: scripts/migrate.py's duplicate_column_skipping fallback
-- handles re-runs that already see the columns; CREATE INDEX uses
-- IF NOT EXISTS.

ALTER TABLE usage_events ADD COLUMN latency_ms INTEGER;
ALTER TABLE usage_events ADD COLUMN result_count INTEGER;

CREATE INDEX IF NOT EXISTS idx_usage_events_endpoint_created
    ON usage_events(endpoint, ts);
