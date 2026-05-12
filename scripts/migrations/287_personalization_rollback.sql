-- target_db: autonomath
-- migration: 287_personalization_rollback
-- generated_at: 2026-05-12
-- author: Wave 47 — Dim H personalization preference rollback
-- idempotent: every DROP uses IF EXISTS; safe to re-run.
--
-- Rolls back migration 287_personalization. Drops the view first
-- (depends on profile + log tables), then the log (FK -> profile),
-- then the profile table itself.
--
-- NOTE: This rollback does NOT drop am_personalization_score
-- (migration 264) or its dependents. The two layers are intentionally
-- decoupled — 264 holds derived scores, 287 holds upstream preference
-- inputs + downstream audit. Roll back independently.

PRAGMA foreign_keys = ON;

BEGIN;

DROP VIEW IF EXISTS v_personalization_recent_recs;

DROP INDEX IF EXISTS idx_am_pers_rec_type_score;
DROP INDEX IF EXISTS idx_am_pers_rec_profile_served;
DROP TABLE IF EXISTS am_personalization_recommendation_log;

DROP INDEX IF EXISTS idx_am_personalization_profile_token;
DROP TABLE IF EXISTS am_personalization_profile;

COMMIT;
