-- target_db: jpintel
-- migration 081_invoice_registrants_bulk_index
--
-- Why this exists:
--   Migration 019 sized indexes for a 13K-row delta-only mirror. Now
--   that the monthly NTA zenken bulk (~4M rows) lands via
--   scripts/cron/ingest_nta_invoice_bulk.py, two access patterns become
--   hot enough that the existing single-column indexes cause table
--   scans on every probe:
--
--     1. v_houjin_360 join — joining invoice_registrants → houjin_master
--        by houjin_bangou and ordering by registered_date DESC for the
--        "is this houjin currently 適格?" lookup. The current partial
--        index on houjin_bangou alone forces a per-row table fetch to
--        read registered_date, which on 4M rows is ~80 ms even with
--        WAL hot.
--
--     2. Prefecture × active rollups — the public stats page surfaces
--        "適格事業者 by prefecture" and the daily_stats cron rebuilds
--        prefecture × kind × active counts. The current single-column
--        prefecture index doesn't cover registered_date, forcing a
--        sort step.
--
-- This migration adds two covering indexes that let the planner answer
-- both queries from the index alone.
--
-- Idempotency:
--   * Pure CREATE INDEX IF NOT EXISTS — re-running is a no-op.
--   * Adds storage (~80-120 MB at 4M rows). The migration 019 estimate
--     of 400-600 MB total index footprint already accounted for this.
--
-- Post-load housekeeping:
--   * The cron driver runs ANALYZE invoice_registrants after every full
--     load (and every delta) so SQLite's planner picks these new
--     indexes. Manual VACUUM is recommended after the very first
--     4M-row monthly bulk lands (one-shot ~5-10 min reclaim).
--
-- What this is NOT:
--   * Not a (status, last_modified) status-proxy index — invoice_registrants
--     uses (revoked_date, expired_date) for the active flag and
--     last_updated_nta for upstream timestamp. Migration 019's
--     idx_invoice_registrants_active already covers the active filter;
--     adding a status-proxy column would be a denormalization with
--     sync-bug risk (the column would have to be maintained on every
--     UPSERT).

PRAGMA foreign_keys = ON;

-- 1. (houjin_bangou, registered_date DESC) — covers the 360-degree
--    "is this houjin 適格 today, and since when?" lookup. Partial because
--    sole-proprietors lack a houjin_bangou and would otherwise inflate
--    the index by ~50% with NULL entries the planner can't use anyway.
CREATE INDEX IF NOT EXISTS idx_invoice_registrants_houjin_registered
    ON invoice_registrants(houjin_bangou, registered_date DESC)
    WHERE houjin_bangou IS NOT NULL;

-- 2. (prefecture, registered_date DESC) — covers the prefecture rollup
--    + "newest in 都道府県" listing. Partial filter on NOT NULL keeps
--    foreign / unmapped rows out (a thin slice but keeps the index lean).
CREATE INDEX IF NOT EXISTS idx_invoice_registrants_prefecture_registered
    ON invoice_registrants(prefecture, registered_date DESC)
    WHERE prefecture IS NOT NULL;

-- 3. (last_updated_nta) — supports incremental delta replay queries
--    ("rows that NTA touched after timestamp X") used by the
--    invoice_load_log audit cron. Partial NOT NULL because legacy
--    pre-2024 rows ship with NULL last_updated_nta.
CREATE INDEX IF NOT EXISTS idx_invoice_registrants_last_updated
    ON invoice_registrants(last_updated_nta)
    WHERE last_updated_nta IS NOT NULL;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
