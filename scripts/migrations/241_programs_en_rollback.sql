-- target_db: jpintel
-- rollback: 241_programs_en

BEGIN;
DROP INDEX IF EXISTS idx_programs_translation_refresh_started;
DROP TABLE IF EXISTS programs_translation_refresh_log;
DROP INDEX IF EXISTS idx_programs_translation_review_program;
DROP INDEX IF EXISTS idx_programs_translation_review_pending;
DROP TABLE IF EXISTS programs_translation_review_queue;
DROP INDEX IF EXISTS idx_programs_title_en_present;
DROP INDEX IF EXISTS idx_programs_translation_status;
COMMIT;
