-- target_db: autonomath
-- migration 160_am_adoption_trend_monthly
--
-- Why this exists (post Wave 24+ launch substrate, 2026-05-05):
--   Per-industry monthly time-series view of 採択 (adoption) records so
--   downstream tools (weekly KPI digest, industry pack tools, public
--   "trending industries" surface) can answer "which JSIC major saw the
--   biggest 採択 surge in the last quarter" without re-aggregating
--   201,845 rows on every request.
--
--   Source signals:
--     * jpi_adoption_records (201,845 rows, 192,985 with announced_at;
--       17 distinct industry_jsic_medium values — actually JSIC majors
--       A..T encoded as a single letter despite the column name).
--     * programs.jsic_majors (W20-3, 14,472 rows, JSON list per program)
--       reachable via ATTACH DATABASE on data/jpintel.db when an
--       adoption row has a resolved program_id (81,218 rows). The
--       populator prefers programs.jsic_majors per-major-letter when
--       available, else falls back to industry_jsic_medium.
--
--   Date range observed: 2020-04 .. 2026-03 (~72 month buckets × 17
--   majors → ≤1,224 rows). Tiny mat view, full-rebuild populator.
--
-- Schema:
--   * year_month TEXT NOT NULL                — YYYY-MM (strftime on
--                                               announced_at)
--   * jsic_major TEXT NOT NULL                — single letter A..T
--   * adoption_count INTEGER DEFAULT 0        — # adoption rows in bucket
--   * distinct_houjin_count INTEGER DEFAULT 0 — distinct houjin_bangou
--   * distinct_program_count INTEGER DEFAULT 0— distinct program_id /
--                                               program_id_hint fallback
--   * trend_flag TEXT                         — 'increasing' / 'decreasing' /
--                                               'stable'. 3-month rolling
--                                               avg vs prior 3-month avg.
--                                               +>=10% = increasing,
--                                               -<=10% = decreasing, else
--                                               stable. NULL when window
--                                               cannot be formed (first 3
--                                               months per major).
--   * computed_at TEXT NOT NULL DEFAULT (datetime('now'))
--   * PRIMARY KEY (year_month, jsic_major)
--
-- Indexes:
--   * (jsic_major, year_month) — per-industry time-series scans
--   * (year_month) — cross-industry monthly snapshot
--   * (trend_flag) WHERE trend_flag IS NOT NULL — trending-industry rollups
--
-- Populator:
--   `scripts/etl/build_adoption_trend.py` (NON-LLM). Pure SQL aggregation
--   on jpi_adoption_records with optional ATTACH on data/jpintel.db to
--   pull programs.jsic_majors when --jpintel-db is provided. Re-runs are
--   idempotent (DELETE FROM am_adoption_trend_monthly; INSERT ... in a
--   single transaction).
--
-- Idempotency:
--   CREATE TABLE / INDEX use IF NOT EXISTS. Populator does full rebuild
--   each run; mat view is small (≤1,224 rows expected), wipe+repopulate
--   is cheaper than per-bucket UPSERT and avoids stale-PK drift when new
--   majors enter the corpus.
--
-- DOWN:
--   See companion 160_am_adoption_trend_monthly_rollback.sql.
--
-- Bookkeeping is recorded by entrypoint.sh autonomath self-heal loop
-- into schema_migrations(id, checksum, applied_at). Do NOT INSERT here.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS am_adoption_trend_monthly (
    year_month              TEXT NOT NULL,
    jsic_major              TEXT NOT NULL,
    adoption_count          INTEGER NOT NULL DEFAULT 0,
    distinct_houjin_count   INTEGER NOT NULL DEFAULT 0,
    distinct_program_count  INTEGER NOT NULL DEFAULT 0,
    trend_flag              TEXT
                            CHECK (trend_flag IS NULL OR
                                   trend_flag IN ('increasing',
                                                  'decreasing',
                                                  'stable')),
    computed_at             TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (year_month, jsic_major)
);

CREATE INDEX IF NOT EXISTS ix_adoption_trend_jsic
    ON am_adoption_trend_monthly(jsic_major, year_month);

CREATE INDEX IF NOT EXISTS ix_adoption_trend_ym
    ON am_adoption_trend_monthly(year_month);

CREATE INDEX IF NOT EXISTS ix_adoption_trend_flag
    ON am_adoption_trend_monthly(trend_flag)
    WHERE trend_flag IS NOT NULL;
