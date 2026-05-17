-- target_db: autonomath
-- rollback: wave24_216_am_pdf_watch_log
DROP VIEW IF EXISTS v_am_pdf_watch_funnel;
DROP INDEX IF EXISTS ix_am_pdf_watch_log_textract_job_id;
DROP INDEX IF EXISTS ix_am_pdf_watch_log_content_hash;
DROP INDEX IF EXISTS ix_am_pdf_watch_log_detected_at;
DROP INDEX IF EXISTS ix_am_pdf_watch_log_kg_status;
DROP INDEX IF EXISTS ix_am_pdf_watch_log_textract_status;
DROP INDEX IF EXISTS ix_am_pdf_watch_log_source_kind;
DROP TABLE IF EXISTS am_pdf_watch_log;
