-- target_db: autonomath
-- migration 196_entity_id_bridge (ROLLBACK companion)
-- entrypoint.sh §4 self-heal loop excludes *_rollback.sql files.
-- This is operator-run only.

DROP INDEX IF EXISTS ux_entity_id_bridge_natural_key;
DROP INDEX IF EXISTS idx_entity_id_bridge_validity;
DROP INDEX IF EXISTS idx_entity_id_bridge_law;
DROP INDEX IF EXISTS idx_entity_id_bridge_procurement;
DROP INDEX IF EXISTS idx_entity_id_bridge_permit;
DROP INDEX IF EXISTS idx_entity_id_bridge_edinet;
DROP INDEX IF EXISTS idx_entity_id_bridge_invoice;
DROP INDEX IF EXISTS idx_entity_id_bridge_houjin;
DROP TABLE IF EXISTS entity_id_bridge;
