-- target_db: autonomath
-- rollback for migration 215_cross_link_graph_v2 (Wave 15 F1 perf indexes).
--
-- Drops the two indexes added by 215. No data side effects.

DROP INDEX IF EXISTS ix_am_relation_tgt_type_conf;
DROP INDEX IF EXISTS ix_am_relation_type_conf;
