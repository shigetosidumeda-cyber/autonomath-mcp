-- target_db: autonomath
-- rollback: 240_law_en_full

BEGIN;
DROP INDEX IF EXISTS ix_am_law_translation_refresh_log_lang;
DROP INDEX IF EXISTS ix_am_law_translation_refresh_log_started;
DROP TABLE IF EXISTS am_law_translation_refresh_log;
DROP INDEX IF EXISTS ix_am_law_translation_review_queue_canonical;
DROP INDEX IF EXISTS ix_am_law_translation_review_queue_pending;
DROP TABLE IF EXISTS am_law_translation_review_queue;
DROP INDEX IF EXISTS ix_am_law_translation_progress_gap;
DROP INDEX IF EXISTS ix_am_law_translation_progress_lang;
DROP TABLE IF EXISTS am_law_translation_progress;
DROP INDEX IF EXISTS ix_am_law_title_en_present;
DROP INDEX IF EXISTS ix_am_law_body_en_present;
COMMIT;
