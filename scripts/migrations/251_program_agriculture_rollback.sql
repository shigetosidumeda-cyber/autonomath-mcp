-- target_db: autonomath
-- rollback: 251_program_agriculture
-- generated_at: 2026-05-12

BEGIN;

DROP VIEW IF EXISTS v_program_agriculture_density;
DROP TABLE IF EXISTS am_program_agriculture_ingest_log;
DROP INDEX IF EXISTS idx_program_agri_deadline;
DROP INDEX IF EXISTS idx_program_agri_bureau;
DROP INDEX IF EXISTS idx_program_agri_program_id;
DROP INDEX IF EXISTS idx_program_agri_type;
DROP INDEX IF EXISTS ux_program_agri_maff_id;
DROP TABLE IF EXISTS am_program_agriculture;

COMMIT;
