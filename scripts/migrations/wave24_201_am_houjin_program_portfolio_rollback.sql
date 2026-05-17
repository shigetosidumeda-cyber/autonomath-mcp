-- target_db: autonomath
-- migration: wave24_201_am_houjin_program_portfolio_rollback
-- generated_at: 2026-05-17
-- author: D2 audit Schema Sync 2026-05-17 (missing rollback fill, N2 lane)
-- idempotent: every DROP uses IF EXISTS; rollback is destructive — only
--             run when explicitly invoked, NOT auto-applied by entrypoint.sh
--             (the *_rollback.sql suffix excludes it from the migration loop).
--
-- Reverses scripts/migrations/wave24_201_am_houjin_program_portfolio.sql.

DROP VIEW  IF EXISTS v_am_houjin_gap_top;

DROP INDEX IF EXISTS ux_am_hpp_houjin_program_method;
DROP INDEX IF EXISTS ix_am_hpp_deadline;
DROP INDEX IF EXISTS ix_am_hpp_program;
DROP INDEX IF EXISTS ix_am_hpp_houjin_unapplied;
DROP INDEX IF EXISTS ix_am_hpp_houjin_priority;
DROP INDEX IF EXISTS ix_am_hpp_houjin;

DROP TABLE IF EXISTS am_houjin_program_portfolio;
