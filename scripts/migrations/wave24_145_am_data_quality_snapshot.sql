-- target_db: autonomath
-- W14-4 latent concern fix: precomputed snapshot for /v1/stats/data_quality.
--
-- Idempotent. Safe to re-run on every Fly boot via entrypoint.sh §4.
--
-- Why
-- ---
-- The /v1/stats/data_quality handler (api/stats.py) aggregates
--   * `am_uncertainty_view` (mig 069), and
--   * `am_source` (97k+ rows on the 9.4 GB autonomath.db volume)
-- inline on every request. Walking 97k+ source rows + the join-heavy
-- uncertainty view inside a Fly request can blow past the 60 s grace
-- window (memory `feedback_no_quick_check_on_huge_sqlite`, 2026-05-03).
--
-- This table holds exactly ONE row that is rebuilt by a daily cron
-- (scripts/cron/precompute_data_quality.py at 05:05 JST). The handler
-- reads it via `SELECT * FROM am_data_quality_snapshot ORDER BY
-- snapshot_at DESC LIMIT 1` (~1 ms), so the request budget is bounded
-- regardless of upstream row counts.
--
-- Schema notes
-- ------------
-- * Aggregates are stored as JSON blobs (label_histogram, license_breakdown,
--   freshness_buckets, field_kind_breakdown, cross_source_agreement) so
--   the table layout never has to change when the handler shape evolves.
-- * `fallback_source` mirrors the handler's existing fallback signal
--   ("am_uncertainty_view_missing" / "am_uncertainty_view_empty" /
--   "am_source_missing" / NULL on happy path).
-- * `source_url_freshness_pct` is the share of `am_source` rows whose
--   `last_fetched_at` is within the last 30 days (helper KPI carried
--   for the trust-signal page; cron computes it once and parks it here).
-- * Primary key on `snapshot_at` (ISO-8601 UTC string with Z suffix)
--   means cron INSERTs are idempotent across same-second restarts.

CREATE TABLE IF NOT EXISTS am_data_quality_snapshot (
    snapshot_at                 TEXT PRIMARY KEY,
    source_count                INTEGER NOT NULL DEFAULT 0,
    fact_count_total            INTEGER NOT NULL DEFAULT 0,
    mean_score                  REAL,
    label_histogram_json        TEXT NOT NULL DEFAULT '{}',
    license_breakdown_json      TEXT NOT NULL DEFAULT '{}',
    freshness_buckets_json      TEXT NOT NULL DEFAULT '{}',
    field_kind_breakdown_json   TEXT NOT NULL DEFAULT '{}',
    cross_source_agreement_json TEXT NOT NULL DEFAULT '{}',
    source_url_freshness_pct    REAL,
    fallback_source             TEXT,
    fallback_note               TEXT,
    am_source_total_rows        INTEGER,
    model                       TEXT NOT NULL DEFAULT 'beta_posterior_v1',
    compute_ms                  INTEGER
);

-- Read path uses ORDER BY snapshot_at DESC LIMIT 1; index keeps that O(1).
CREATE INDEX IF NOT EXISTS idx_am_data_quality_snapshot_at
    ON am_data_quality_snapshot(snapshot_at DESC);
