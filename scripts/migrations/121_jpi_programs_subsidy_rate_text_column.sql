-- target_db: autonomath
-- migration 121_jpi_programs_subsidy_rate_text_column (autonomath mirror of 121)
--
-- Why this exists:
--   `autonomath.db.jpi_programs` mirrors `data/jpintel.db.programs` after
--   the migration 032 unification. The D5 cleaner (scripts/etl/
--   fix_subsidy_rate_text_values.py) updates both tables in lock-step.
--   Companion to 121_subsidy_rate_text_column.sql (jpintel target) — see
--   that file for the full rationale.
--
-- Schema additions:
--   jpi_programs.subsidy_rate_text TEXT
--     Mirror of `programs.subsidy_rate_text` over in jpintel.db.
--
-- Idempotency:
--   `ALTER TABLE ADD COLUMN` is not natively IF NOT EXISTS in SQLite;
--   the entrypoint.sh autonomath self-heal loop tolerates duplicate-column
--   errors per the existing convention (sqlite3 < file does not abort on
--   first error; bookkeeping records the file as applied either way).
--
-- DOWN:
--   No down — additive, NULL-defaulted, ignored by every existing read.

PRAGMA foreign_keys = ON;

ALTER TABLE jpi_programs ADD COLUMN subsidy_rate_text TEXT;

-- Bookkeeping is recorded by entrypoint.sh into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
