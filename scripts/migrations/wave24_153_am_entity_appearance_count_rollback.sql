-- target_db: autonomath
-- Rollback companion for wave24_153_am_entity_appearance_count.
-- Manual-review only. The entrypoint loop excludes *_rollback.sql files
-- from boot-time idempotent migrations.

DROP INDEX IF EXISTS ix_appearance_count_count;
DROP TABLE IF EXISTS am_entity_appearance_count;
DROP VIEW IF EXISTS v_houjin_appearances;
