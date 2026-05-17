-- target_db: autonomath
-- migration: wave24_182_contributor_trust_rollback
-- generated_at: 2026-05-17
-- author: D2 audit Schema Sync 2026-05-17 (missing rollback fill)
-- idempotent: every DROP uses IF EXISTS; rollback is destructive — only
--             run when explicitly invoked, NOT auto-applied by entrypoint.sh
--             (the *_rollback.sql suffix excludes it from the migration loop).
--
-- Reverses scripts/migrations/wave24_182_contributor_trust.sql.

PRAGMA foreign_keys = OFF;

DROP VIEW  IF EXISTS v_contributor_trust_verified;
DROP VIEW  IF EXISTS v_contributor_trust_cohort;

DROP INDEX IF EXISTS idx_contributor_trust_cohort_score;
DROP INDEX IF EXISTS idx_contributor_trust_uniq;

DROP TABLE IF EXISTS contributor_trust_meta;
DROP TABLE IF EXISTS contributor_trust;

PRAGMA foreign_keys = ON;
