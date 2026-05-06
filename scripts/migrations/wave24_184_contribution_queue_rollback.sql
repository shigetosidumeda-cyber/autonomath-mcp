-- target_db: autonomath
-- migration: wave24_184_contribution_queue_rollback
-- generated_at: 2026-05-07
-- author: DEEP-28 customer-contributed eligibility corpus + DEEP-31 form
-- idempotent: every DROP uses IF EXISTS; rollback is destructive — only
--             run when explicitly invoked, NOT auto-applied by entrypoint.sh
--             (the *_rollback.sql suffix excludes it from the migration loop).
--
-- Reverses scripts/migrations/wave24_184_contribution_queue.sql.

PRAGMA foreign_keys = OFF;

DROP VIEW  IF EXISTS v_contribution_queue_per_program;
DROP VIEW  IF EXISTS v_contribution_queue_pending_count;

DROP INDEX IF EXISTS idx_contribution_queue_api_key;
DROP INDEX IF EXISTS idx_contribution_queue_houjin_hash;
DROP INDEX IF EXISTS idx_contribution_queue_submitted_at;
DROP INDEX IF EXISTS idx_contribution_queue_status_program;

DROP TABLE IF EXISTS contribution_queue;

PRAGMA foreign_keys = ON;
