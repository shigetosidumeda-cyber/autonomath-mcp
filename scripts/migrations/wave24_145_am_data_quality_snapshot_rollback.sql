-- target_db: autonomath
-- Rollback for wave24_145_am_data_quality_snapshot.sql
DROP INDEX IF EXISTS idx_am_data_quality_snapshot_at;
DROP TABLE IF EXISTS am_data_quality_snapshot;
