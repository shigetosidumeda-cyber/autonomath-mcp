-- target_db: autonomath
-- rollback: 239_am_knowledge_graph_vec_index

BEGIN;

DROP INDEX IF EXISTS idx_am_entities_vec_embed_log_at;
DROP INDEX IF EXISTS idx_am_entities_vec_embed_log_kind;
DROP INDEX IF EXISTS idx_am_entities_vec_refresh_log_mode;
DROP INDEX IF EXISTS idx_am_entities_vec_refresh_log_started;
DROP TABLE IF EXISTS am_entities_vec_embed_log;
DROP TABLE IF EXISTS am_entities_vec_refresh_log;

COMMIT;
