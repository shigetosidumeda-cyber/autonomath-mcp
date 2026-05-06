-- target_db: autonomath
-- migration 159_am_id_bridge_rollback
DROP INDEX IF EXISTS ix_id_bridge_kind;
DROP INDEX IF EXISTS ix_id_bridge_b;
DROP INDEX IF EXISTS ix_id_bridge_a;
DROP TABLE IF EXISTS am_id_bridge;
