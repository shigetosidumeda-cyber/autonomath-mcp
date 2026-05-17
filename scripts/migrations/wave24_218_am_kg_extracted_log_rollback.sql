-- target_db: autonomath
-- rollback for: wave24_218_am_kg_extracted_log

PRAGMA foreign_keys = ON;

DROP INDEX IF EXISTS ix_am_kg_extracted_log_mode;
DROP INDEX IF EXISTS ix_am_kg_extracted_log_lane_started;
DROP TABLE IF EXISTS am_kg_extracted_log;
