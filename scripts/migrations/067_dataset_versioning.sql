-- migration 067: dataset versioning (R8)
--
-- target_db: jpintel.db
--
-- Background:
--   Strategy R8 — bitemporal row-level versioning so callers can pin a
--   query to a historical "as of" date and replay the exact state of the
--   dataset at that timestamp. Drives the legal-evidence (法廷証拠) value
--   prop for tax accountants / 行政書士 who need 申告時点の制度状態 fixed
--   for audit. Design: analysis_wave18/_r8_dataset_versioning_2026-04-25.md.
--
--   This adds two columns to each of the 8 main jpintel.db tables:
--     - valid_from   : ISO 8601 timestamp when the row's content became
--                      authoritative. Backfilled from source_fetched_at /
--                      fetched_at / updated_at (best-available column).
--     - valid_until  : ISO 8601 timestamp when the row was superseded.
--                      NULL = currently authoritative.
--
--   Append-only updates (writers must close the prior row's valid_until
--   and INSERT a new row) are documented as the canonical pattern in
--   docs/compliance/data_governance.md. This migration only lays the
--   schema + index + backfill — writer changes land in the ingest CLIs.
--
-- Tables covered (8):
--   programs, case_studies, loan_programs, enforcement_cases,
--   laws, tax_rulesets, court_decisions, bids
--
-- Idempotency:
--   ALTER TABLE ... ADD COLUMN is not idempotent in SQLite, so we wrap
--   each ADD in a duplicate-column tolerant pattern via PRAGMA / try-catch
--   at the application layer. This file uses naked ALTERs because the
--   migration runner records `id -> applied_at` and never re-applies a
--   recorded migration. If the migration is interrupted mid-script, fix
--   forward by removing the schema_migrations row and dropping any
--   already-added column, then re-apply.
--
-- DOWN (commented — versioning columns must persist for legal-evidence
-- reproducibility; rollback would lose the audit trail):
--   -- ALTER TABLE programs DROP COLUMN valid_from;
--   -- ALTER TABLE programs DROP COLUMN valid_until;
--   -- ...repeat per table...
--   -- DROP INDEX IF EXISTS ix_programs_valid;
--   -- ...
--
-- Performance:
--   Composite index (valid_from, valid_until) supports the canonical
--   range predicate `valid_from <= ? AND (valid_until IS NULL OR
--   valid_until > ?)` with a single index seek per row family. NULL
--   valid_until is the live-row hot path; the index leads with the
--   sortable column so live-only queries also benefit.

PRAGMA foreign_keys = ON;

-- ============================================================================
-- 1) programs (uses source_fetched_at)
-- ============================================================================
ALTER TABLE programs ADD COLUMN valid_from TEXT;
ALTER TABLE programs ADD COLUMN valid_until TEXT;
UPDATE programs
   SET valid_from = COALESCE(source_fetched_at, updated_at)
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_programs_valid
    ON programs(valid_from, valid_until);

-- ============================================================================
-- 2) case_studies (uses fetched_at)
-- ============================================================================
ALTER TABLE case_studies ADD COLUMN valid_from TEXT;
ALTER TABLE case_studies ADD COLUMN valid_until TEXT;
UPDATE case_studies
   SET valid_from = fetched_at
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_case_studies_valid
    ON case_studies(valid_from, valid_until);

-- ============================================================================
-- 3) loan_programs (uses fetched_at)
-- ============================================================================
ALTER TABLE loan_programs ADD COLUMN valid_from TEXT;
ALTER TABLE loan_programs ADD COLUMN valid_until TEXT;
UPDATE loan_programs
   SET valid_from = fetched_at
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_loan_programs_valid
    ON loan_programs(valid_from, valid_until);

-- ============================================================================
-- 4) enforcement_cases (uses fetched_at)
-- ============================================================================
ALTER TABLE enforcement_cases ADD COLUMN valid_from TEXT;
ALTER TABLE enforcement_cases ADD COLUMN valid_until TEXT;
UPDATE enforcement_cases
   SET valid_from = fetched_at
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_enforcement_cases_valid
    ON enforcement_cases(valid_from, valid_until);

-- ============================================================================
-- 5) laws (uses fetched_at NOT NULL)
-- ============================================================================
ALTER TABLE laws ADD COLUMN valid_from TEXT;
ALTER TABLE laws ADD COLUMN valid_until TEXT;
UPDATE laws
   SET valid_from = fetched_at
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_laws_valid
    ON laws(valid_from, valid_until);

-- ============================================================================
-- 6) tax_rulesets (uses fetched_at NOT NULL)
-- ============================================================================
ALTER TABLE tax_rulesets ADD COLUMN valid_from TEXT;
ALTER TABLE tax_rulesets ADD COLUMN valid_until TEXT;
UPDATE tax_rulesets
   SET valid_from = fetched_at
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_tax_rulesets_valid
    ON tax_rulesets(valid_from, valid_until);

-- ============================================================================
-- 7) court_decisions (uses fetched_at NOT NULL)
-- ============================================================================
ALTER TABLE court_decisions ADD COLUMN valid_from TEXT;
ALTER TABLE court_decisions ADD COLUMN valid_until TEXT;
UPDATE court_decisions
   SET valid_from = fetched_at
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_court_decisions_valid
    ON court_decisions(valid_from, valid_until);

-- ============================================================================
-- 8) bids (uses fetched_at NOT NULL)
-- ============================================================================
ALTER TABLE bids ADD COLUMN valid_from TEXT;
ALTER TABLE bids ADD COLUMN valid_until TEXT;
UPDATE bids
   SET valid_from = fetched_at
 WHERE valid_from IS NULL;
CREATE INDEX IF NOT EXISTS ix_bids_valid
    ON bids(valid_from, valid_until);

-- Bookkeeping is recorded by scripts/migrate.py into schema_migrations(id, checksum, applied_at).
-- Do NOT INSERT here.
