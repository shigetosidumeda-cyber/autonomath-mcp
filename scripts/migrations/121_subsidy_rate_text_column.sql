-- target_db: jpintel
-- migration 121_subsidy_rate_text_column (D5 follow-up: preserve display text)
--
-- Why this exists:
--   The D5 ETL (scripts/etl/fix_subsidy_rate_text_values.py) cleaned 10 rows
--   in `programs` whose REAL `subsidy_rate` column had been polluted with
--   text values like '30%', '2/3', '10/10', '定額', '価格連動(...70% or 100%)'.
--   The cleaner now writes parsed numeric maxima (or NULL for fixed-only
--   tokens like 定額) back into the REAL column.
--
--   Discarding the original display text from the DB destroyed information
--   useful for human-readable surfaces (per-program SEO pages, tax pack
--   workpapers, due-diligence kits): "2/3" is materially different from
--   "1/2 or 定額" even though both parse to the same numeric. Reviewers,
--   税理士 顧問先 packs, and audit-seal exports want the original phrasing.
--
--   This migration adds a sibling TEXT column so the cleaner can preserve
--   the display string alongside the numeric. The numeric column keeps its
--   REAL invariant (so range filters, tier scoring, and OpenAPI types do
--   not break), and read paths that want the human-readable form pull
--   `subsidy_rate_text`.
--
-- Schema additions:
--   programs.subsidy_rate_text TEXT
--     The original display string (e.g. '2/3', '定額', '1/2 or 定額').
--     Populated only for the 10 historical rows touched by the D5 cleaner;
--     future rows that come in as text get the same dual-write treatment
--     by the ETL.
--
-- Idempotency:
--   `ALTER TABLE ADD COLUMN` is not natively IF NOT EXISTS in SQLite;
--   migrate.py's tolerant ADD COLUMN handler catches "duplicate column
--   name" errors so re-runs on an already-migrated DB are no-ops.
--
-- DOWN:
--   No down — the column is additive, NULL-defaulted, and ignored by
--   every existing read path. To remove, drop and rebuild the table
--   (SQLite DROP COLUMN landed in 3.35; production ships 3.46+).

PRAGMA foreign_keys = ON;

ALTER TABLE programs ADD COLUMN subsidy_rate_text TEXT;

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
