-- target_db: autonomath
-- ROLLBACK for migration 206_entity_id_bridge_v3
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS idx_entity_id_bridge_v3_created_at;
DROP INDEX IF EXISTS idx_entity_id_bridge_v3_canonical_only;
DROP INDEX IF EXISTS idx_entity_id_bridge_v3_canonical;
DROP TABLE IF EXISTS entity_id_bridge_v3;
