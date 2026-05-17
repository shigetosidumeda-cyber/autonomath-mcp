-- target_db: autonomath
-- Rollback companion for wave24_200_am_artifact_templates.sql.

DROP VIEW IF EXISTS v_am_artifact_templates_latest;
DROP INDEX IF EXISTS ix_am_artifact_templates_segment_type;
DROP INDEX IF EXISTS ix_am_artifact_templates_type;
DROP INDEX IF EXISTS ix_am_artifact_templates_segment;
DROP TABLE IF EXISTS am_artifact_templates;
