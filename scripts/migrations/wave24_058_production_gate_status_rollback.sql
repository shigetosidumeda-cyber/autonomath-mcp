-- target_db: jpintel
-- migration: wave24_058_production_gate_status_rollback
-- generated_at: 2026-05-17
-- author: D2 audit Schema Sync 2026-05-17 (missing rollback fill)
-- idempotent: every DROP uses IF EXISTS; rollback is destructive — only
--             run when explicitly invoked, NOT auto-applied by entrypoint.sh
--             (the *_rollback.sql suffix excludes it from the migration loop).
--
-- Reverses scripts/migrations/wave24_058_production_gate_status.sql.

DROP VIEW  IF EXISTS v_production_gate_latest;

DROP INDEX IF EXISTS idx_pgs_status;
DROP INDEX IF EXISTS idx_pgs_blocker;
DROP INDEX IF EXISTS idx_pgs_date;

DROP TABLE IF EXISTS production_gate_status;
