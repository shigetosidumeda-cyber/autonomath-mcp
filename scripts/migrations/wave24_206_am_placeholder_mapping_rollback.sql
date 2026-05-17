-- target_db: autonomath
-- rollback: wave24_206_am_placeholder_mapping
DROP VIEW IF EXISTS v_am_placeholder_by_tool;
DROP INDEX IF EXISTS ix_am_placeholder_value_kind;
DROP INDEX IF EXISTS ix_am_placeholder_sensitive;
DROP INDEX IF EXISTS ix_am_placeholder_tool;
DROP TABLE IF EXISTS am_placeholder_mapping;
